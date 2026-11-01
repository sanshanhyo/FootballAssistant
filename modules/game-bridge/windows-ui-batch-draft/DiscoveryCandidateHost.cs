using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Channels;

namespace FootballAssistant.GameBridge;

// Pure host admission state: retain ONE instance for the whole loaded session.
// It cannot be reset by replacing request files, by native failure, or by a new nonce.
internal sealed class DiscoverySessionGate
{
    private readonly SmokeContext context;
    private readonly object gate = new();
    private bool taken;
    internal DiscoverySessionGate(SmokeContext context) => this.context = context;
    internal bool Taken { get { lock (gate) return taken; } }
    internal DiscoveryPolicy? TryTake(DiscoveryHostRequest pending, DateTimeOffset now)
    {
        lock (gate)
        {
            if (taken) return null;
            var approval = DiscoveryCandidateConfiguration.TryApproval(pending, context, now);
            if (approval is null) return null;
            taken = true; // Consume before any native admission, including failure.
            return new DiscoveryPolicy(approval);
        }
    }
}

internal sealed class DiscoveryCandidateHost : IDisposable
{
    private readonly DiscoveryCandidateConfigurationData configuration;
    private readonly SmokeContext context;
    private readonly DiscoverySessionGate admission;
    private readonly Win32ProbePlatform platform = new();
    private readonly CancellationTokenSource cancel = new();
    private readonly Channel<object> evidence = Channel.CreateBounded<object>(new BoundedChannelOptions(16)
        { SingleReader = true, FullMode = BoundedChannelFullMode.DropOldest });
    private WindowsLoadedModuleLease? lease;
    private DiscoveryHostRequest? request;
    private nuint timer;
    private int stopped, entered, terminal;

    internal DiscoveryCandidateHost(string assemblyPath)
    {
        configuration = DiscoveryCandidateConfiguration.Read(assemblyPath);
        using (var process = System.Diagnostics.Process.GetCurrentProcess())
            if (configuration.RecordedAt >= process.StartTime.ToUniversalTime() || configuration.RecordedAt > DateTimeOffset.UtcNow)
                throw new InvalidOperationException("File identity record must predate game launch.");
        var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant();
        context = new(Environment.ProcessId, Guid.NewGuid().ToString("D"), hash,
            VerifiedWindowsBuild.GameAssemblySha256, configuration.WindowClass, platform.ThreadId);
        admission = new(context);
        Directory.CreateDirectory(configuration.PrivateRoot);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(configuration.PrivateRoot);
        WritePrivate("session.json", new { schema_version = 3, pid = context.Pid, session_id = context.Session,
            bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash,
            exe_sha256 = VerifiedWindowsBuild.ExecutableSha256, window_class = context.ConfirmedWindowClass,
            entry_tid = context.EntryThread, mode = "ui_discovery_once", discovery_enabled_by_default = false,
            panel_index = 0, focus_path = "0/6", allowed_scopes = new[] { "profile_body", "goalkeeper_row0" }, raw_diagnostics_only = true });
        WriteState();
        _ = Task.Run(WriteEvidence);
        timer = platform.Start(Tick, 1000);
        if (timer == 0) { evidence.Writer.TryComplete(); throw new InvalidOperationException("Discovery timer unavailable."); }
        _ = Task.Run(PrepareAndPoll);
    }
    private void WritePrivate(string name, object value)
    {
        var path = Path.Combine(configuration.PrivateRoot, name);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        File.WriteAllText(path, JsonSerializer.Serialize(value));
    }
    private void WriteState() => WritePrivate("discovery-state.json", new
    {
        pid = context.Pid, session_id = context.Session, bridge_sha256 = context.BridgeHash,
        game_sha256 = context.GameHash, consumed = admission.Taken, terminal = Volatile.Read(ref terminal) != 0
    });
    private void Record(object value) => evidence.Writer.TryWrite(value);
    private async Task WriteEvidence()
    {
        var path = Path.Combine(configuration.PrivateRoot, "discovery-evidence.jsonl");
        await foreach (var item in evidence.Reader.ReadAllAsync())
        {
            try
            {
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
                await File.AppendAllTextAsync(path, JsonSerializer.Serialize(item) + Environment.NewLine);
                WriteState();
            }
            catch { /* Private diagnostics must never escape onto native callback. */ }
        }
    }
    private async Task PrepareAndPoll()
    {
        try
        {
            // Only existing verified-file/loaded-module/PE checks, off main thread.
            // No IL2CPP export is invoked, metadata warmup or UI resolution performed.
            var prepared = WindowsLoadedModuleLease.Acquire(configuration.Module);
            if (Volatile.Read(ref stopped) != 0) { prepared.Dispose(); return; }
            Volatile.Write(ref lease, prepared);
            WritePrivate("module-status.json", new { state = "ready", pid = context.Pid, session_id = context.Session,
                bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash, il2cpp_calls = 0 });
            string? rejected = null;
            while (!cancel.IsCancellationRequested && Volatile.Read(ref terminal) == 0)
            {
                try
                {
                    Volatile.Write(ref request, DiscoveryCandidateConfiguration.ReadRequest(
                        Path.Combine(configuration.PrivateRoot, DiscoveryCandidateConfiguration.RequestName)));
                    rejected = null;
                }
                catch (FileNotFoundException) { Volatile.Write(ref request, null); }
                catch (Exception error)
                {
                    Volatile.Write(ref request, null);
                    if (rejected != error.GetType().Name)
                        Record(new { phase = "request_rejected_no_call", error = error.GetType().Name });
                    rejected = error.GetType().Name;
                }
                await Task.Delay(250, cancel.Token);
            }
        }
        catch (OperationCanceledException) when (cancel.IsCancellationRequested) { }
        catch (Exception error)
        {
            Volatile.Write(ref terminal, 1);
            Record(new { phase = "module_preparation_failed_no_call", error = error.GetType().Name });
        }
    }
    private void Tick(nuint id)
    {
        if (Interlocked.Exchange(ref entered, 1) != 0) return;
        try
        {
            if (id == 0 || id != timer) return;
            if (Volatile.Read(ref stopped) != 0 || Volatile.Read(ref terminal) != 0) { CancelOnOwner(); return; }
            var ready = Volatile.Read(ref lease);
            var pending = Volatile.Read(ref request);
            if (ready is null || pending is null) return; // No scan or IL2CPP work without an explicit request.
            var policy = admission.TryTake(pending, DateTimeOffset.UtcNow);
            if (policy is null) return;
            Volatile.Write(ref terminal, 1); // Exactly one attempt even if it fails before/inside admission.
            try
            {
                var token = new DiscoveryRequest(3, policy.Approval.Nonce, policy.ApprovalSha256);
                var result = ready.RunDiscoveryOnce(policy, token, cancel.Token);
                Record(new { phase = "single_shot_raw_discovery_result", pid = context.Pid, session_id = context.Session,
                    bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash, nonce = pending.Nonce,
                    entry_tid = context.EntryThread, callback_tid = platform.ThreadId, result,
                    page_identity_verified = false, business_facts = false, terminal = true });
            }
            catch (Exception error)
            {
                policy.Stop();
                Record(new { phase = "single_shot_failed_no_retry", nonce = pending.Nonce,
                    error = error.GetType().Name, page_identity_verified = false, terminal = true });
            }
            finally { CancelOnOwner(); }
        }
        catch (Exception error)
        {
            Volatile.Write(ref terminal, 1);
            Record(new { phase = "callback_failed_no_retry", error = error.GetType().Name });
        }
        finally { Volatile.Write(ref entered, 0); }
    }
    private void CancelOnOwner()
    {
        if (platform.ThreadId == context.EntryThread && timer != 0 && platform.Kill(timer)) timer = 0;
    }
    public void Dispose()
    {
        if (Interlocked.Exchange(ref stopped, 1) != 0) return;
        Volatile.Write(ref terminal, 1); cancel.Cancel();
        if (Interlocked.Exchange(ref entered, 1) == 0)
        {
            try { CancelOnOwner(); }
            finally { Volatile.Write(ref entered, 0); }
        }
        // Keep verified lease/file references until process exit rather than race in-flight calls.
        evidence.Writer.TryComplete();
    }
}
