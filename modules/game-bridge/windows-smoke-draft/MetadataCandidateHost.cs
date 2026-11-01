using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Channels;

namespace FootballAssistant.GameBridge;

// Exactly one policy and lease for this Doorstop session. No UI stage or native readers.
internal sealed class MetadataCandidateHost : IDisposable
{
    private readonly MetadataCandidateConfiguration configuration;
    private readonly WindowsSmokePolicy policy;
    private readonly uint entryThread;
    private readonly int pid = Environment.ProcessId;
    private readonly string session = Guid.NewGuid().ToString("D"), bridgeHash;
    private readonly Win32ProbePlatform platform = new();
    private readonly Channel<object> evidence = Channel.CreateBounded<object>(new BoundedChannelOptions(64)
        { SingleReader = true, FullMode = BoundedChannelFullMode.DropOldest });
    private readonly CancellationTokenSource cancel = new();
    private WindowsLoadedModuleLease? lease;
    private SmokeRequest? request;
    private nuint timer;
    private int stopped, entered, attempted;
    private long ticks;

    internal MetadataCandidateHost(string assemblyPath)
    {
        configuration = CandidateConfiguration.Read(assemblyPath); // Absent config => no timer/no module query.
        using (var process = System.Diagnostics.Process.GetCurrentProcess())
        {
            if (configuration.RecordedAt >= process.StartTime.ToUniversalTime() || configuration.RecordedAt > DateTimeOffset.UtcNow)
                throw new InvalidOperationException("File identity record must predate this game process launch.");
        }
        entryThread = platform.ThreadId;
        bridgeHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant();
        policy = new WindowsSmokePolicy(new(pid, session, bridgeHash, VerifiedWindowsBuild.GameAssemblySha256,
            configuration.WindowClass, entryThread));
        Directory.CreateDirectory(configuration.PrivateRoot);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(configuration.PrivateRoot);
        // Session is written BEFORE preparation/request handling. No startup native IL2CPP call.
        WritePrivate("session.json", new { schema_version = 1, pid, session_id = session, bridge_sha256 = bridgeHash,
            game_sha256 = VerifiedWindowsBuild.GameAssemblySha256, exe_sha256 = VerifiedWindowsBuild.ExecutableSha256,
            window_class = configuration.WindowClass, entry_tid = entryThread, mode = "metadata_once_awaiting_request", ui_enabled = false });
        _ = Task.Run(WriteEvidence);
        timer = platform.Start(Tick, 1000);
        if (timer == 0) { evidence.Writer.TryComplete(); throw new InvalidOperationException("Metadata candidate timer unavailable."); }
        _ = Task.Run(PrepareAndPoll);
    }

    private void WritePrivate(string name, object value)
    {
        var path = Path.Combine(configuration.PrivateRoot, name);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        // Only this host writes session/status. Root creates request separately with atomic replace.
        File.WriteAllText(path, JsonSerializer.Serialize(value));
    }
    private void Record(object value) => evidence.Writer.TryWrite(value);
    private async Task WriteEvidence()
    {
        var path = Path.Combine(configuration.PrivateRoot, "metadata-evidence.jsonl");
        await foreach (var item in evidence.Reader.ReadAllAsync())
        {
            try
            {
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
                await File.AppendAllTextAsync(path, JsonSerializer.Serialize(item) + Environment.NewLine);
            }
            catch { /* Diagnostics never escape onto the game callback. */ }
        }
    }

    private async Task PrepareAndPoll()
    {
        try
        {
            // Disk hashing/PE checks run off the main thread. No IL2CPP exports invoked here.
            var prepared = WindowsLoadedModuleLease.Acquire(configuration.Module);
            if (Volatile.Read(ref stopped) != 0) { prepared.Dispose(); return; }
            Volatile.Write(ref lease, prepared);
            WritePrivate("module-status.json", new { at = DateTimeOffset.UtcNow, state = "ready", pid, session_id = session,
                bridge_sha256 = bridgeHash, game_sha256 = VerifiedWindowsBuild.GameAssemblySha256,
                exe_sha256 = VerifiedWindowsBuild.ExecutableSha256, game_path = configuration.Module.AbsolutePath,
                volume_serial = configuration.Module.VolumeSerial, file_index = configuration.Module.FileIndex, il2cpp_calls = 0 });
            Record(new { at = DateTimeOffset.UtcNow, phase = "module_verified_no_il2cpp_calls", pid, session_id = session });
            string? lastRejected = null;
            while (!cancel.IsCancellationRequested && Volatile.Read(ref attempted) == 0)
            {
                var path = Path.Combine(configuration.PrivateRoot, CandidateConfiguration.RequestName);
                try { Volatile.Write(ref request, CandidateConfiguration.ReadRequest(path)); lastRejected = null; }
                catch (FileNotFoundException) { Volatile.Write(ref request, null); }
                catch (Exception error)
                {
                    Volatile.Write(ref request, null);
                    if (lastRejected != error.GetType().Name)
                        Record(new { at = DateTimeOffset.UtcNow, phase = "request_rejected", error = error.GetType().Name, pid, session_id = session });
                    lastRejected = error.GetType().Name;
                }
                await Task.Delay(250, cancel.Token);
            }
        }
        catch (OperationCanceledException) when (cancel.IsCancellationRequested) { }
        catch (Exception error) { Record(new { at = DateTimeOffset.UtcNow, phase = "module_preparation_failed_no_il2cpp_calls", error = error.Message, pid, session_id = session }); }
    }

    private void Tick(nuint id)
    {
        if (Interlocked.Exchange(ref entered, 1) != 0) return;
        try
        {
            if (id == 0 || id != timer) return;
            if (Volatile.Read(ref stopped) != 0) { CancelOnOwner(); return; }
            if (Volatile.Read(ref attempted) != 0) return;
            var identity = MainThreadGuard.ReadWindowsIdentity(entryThread);
            var window = policy.SelectWindow(identity);
            Record(new { at = DateTimeOffset.UtcNow, phase = "waiting_for_authorized_metadata_request", tick = ++ticks,
                pid, session_id = session, entry_tid = entryThread, callback_tid = identity.CurrentThreadId,
                scan = identity.WindowScanStatus, selected_hwnd = window, windows = identity.WindowCandidates, ui_enabled = false });
            var ready = Volatile.Read(ref lease);
            var pending = Volatile.Read(ref request);
            if (ready is null || pending is null || window is null) return;
            // Policy independently validates/consumes request and re-scans again inside RunMetadata.
            // Rejected/stale/mismatched requests cannot cause native calls.
            try
            {
                var result = ready.RunMetadata(policy, pending, cancel.Token);
                if (result is null)
                {
                    if (policy.MetadataAttempted)
                    {
                        Interlocked.Exchange(ref attempted, 1);
                        Record(new { at = DateTimeOffset.UtcNow, phase = "metadata_grant_consumed_no_call_no_retry", pid,
                            session_id = session, nonce = pending.Nonce, ui_enabled = false });
                    }
                    return;
                }
                Interlocked.Exchange(ref attempted, 1);
                Record(new { at = DateTimeOffset.UtcNow, phase = "metadata_success", pid, session_id = session,
                    bridge_sha256 = bridgeHash, game_sha256 = VerifiedWindowsBuild.GameAssemblySha256,
                    nonce = pending.Nonce, entry_tid = entryThread, callback_tid = platform.ThreadId, hwnd = window,
                    domain_present = result.DomainPresent, assembly_count = result.AssemblyCount, ui_enabled = false });
            }
            catch (Exception error)
            {
                Interlocked.Exchange(ref attempted, 1);
                Record(new { at = DateTimeOffset.UtcNow, phase = "metadata_failed_no_retry", pid, session_id = session,
                    nonce = pending.Nonce, error = error.GetType().Name, message = error.Message, ui_enabled = false });
            }
        }
        catch (Exception error) { Record(new { at = DateTimeOffset.UtcNow, phase = "callback_error_no_call", error = error.GetType().Name }); }
        finally { Volatile.Write(ref entered, 0); }
    }

    private void CancelOnOwner()
    {
        if (platform.ThreadId != entryThread) return;
        if (timer != 0 && platform.Kill(timer)) timer = 0;
    }
    public void Dispose()
    {
        if (Interlocked.Exchange(ref stopped, 1) != 0) return;
        cancel.Cancel();
        // No blocking main-thread lease disposal. Delegate remains rooted by Win32ProbePlatform.
        if (Interlocked.Exchange(ref entered, 1) == 0)
        {
            try { CancelOnOwner(); }
            finally { Volatile.Write(ref entered, 0); }
        }
        // Reference/file handles may live to process exit rather than racing an in-flight query.
        evidence.Writer.TryComplete();
    }
}
