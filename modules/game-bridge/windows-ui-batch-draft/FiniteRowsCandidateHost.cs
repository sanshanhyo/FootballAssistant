using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Channels;
namespace FootballAssistant.GameBridge;

// Complete snapshot replacement for three fixed private status files, not arbitrary filesystem access.
// Open handles see complete versions; Windows pathname lookup may transiently report not found.
// Path checks retain the existing best-effort owner-controlled-directory contract.
internal sealed class FinitePrivateFileWriter
{
    private readonly string root;
    private readonly object gate = new();
    internal FinitePrivateFileWriter(string root)
    { WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(root); this.root = root; }
    internal void Write(string name, object value)
    {
        if (name is not ("session.json" or "module-status.json" or "finite-rows-state.json"))
            throw new ArgumentException("Only fixed finite status filenames are permitted.");
        lock (gate)
        {
            var path = Path.Combine(root, name);
            var temporary = Path.Combine(root, name + "." + Guid.NewGuid().ToString("N") + ".tmp");
            var created = false;
            try
            {
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(temporary);
                var bytes = JsonSerializer.SerializeToUtf8Bytes(value);
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { created = true; stream.Write(bytes); stream.Flush(flushToDisk: true); }
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(temporary);
                // MoveFileEx(overwrite) on Windows can deny an open destination even
                // when its reader shares DELETE. ReplaceFile supports shared readers
                // and preserves destination ACLs; never ignore metadata/ACL errors.
                // No delete/copy fallback, permission bypass, or unbounded retry.
                if (File.Exists(path)) File.Replace(temporary, path, destinationBackupFileName: null);
                else File.Move(temporary, path);
            }
            finally
            {
                if (created)
                    try
                    { WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(temporary); File.Delete(temporary); }
                    catch { /* Cleanup failure never replaces the original failure or escapes shutdown. */ }
            }
        }
    }
}

// Retained once per loaded finite host; even an invalid presented manifest consumes admission.
internal sealed class FiniteRowsSessionGate
{
    private readonly SmokeContext context;
    private readonly object gate = new();
    private bool taken;
    internal FiniteRowsSessionGate(SmokeContext context) => this.context = context;
    internal bool Taken { get { lock (gate) return taken; } }
    internal FiniteRowsPolicy? TryTake(FiniteRowsHostManifest manifest, DateTimeOffset now)
    {
        lock (gate)
        {
            if (taken) return null;
            taken = true;
            var approval = FiniteRowsCandidateConfiguration.TryApproval(manifest, context, now);
            return approval is null ? null : new FiniteRowsPolicy(approval);
        }
    }
}

internal sealed class FiniteRowsCandidateHost : IDisposable
{
    private readonly FiniteRowsConfigurationData configuration;
    private readonly FinitePrivateFileWriter privateFiles;
    private readonly SmokeContext context;
    private readonly FiniteRowsSessionGate admission;
    private readonly Win32ProbePlatform platform = new();
    private readonly CancellationTokenSource cancel = new();
    private readonly object moduleStatusGate = new();
    private readonly long clockStarted = Stopwatch.GetTimestamp();
    private readonly Channel<object> evidence = Channel.CreateBounded<object>(new BoundedChannelOptions(32)
        { SingleReader = true, FullMode = BoundedChannelFullMode.DropOldest });
    private WindowsLoadedModuleLease? lease;
    private FiniteRowsHostManifest? manifest;
    private FiniteRowsPolicy? batch;
    // Bounded duplicate detection only; never merged player facts or retained UI objects.
    private readonly HashSet<(string Category, string Label)> seenLabels = new(35);
    private nuint timer;
    private int stopped, entered, terminal;
    private int lastSuccessfulChunk = -1, lastFailedChunk = -1;
    private string outcome = "running";
    private string? failureReason;
    private double Monotonic() => Stopwatch.GetElapsedTime(clockStarted).TotalMilliseconds;
    internal FiniteRowsCandidateHost(string assemblyPath)
    {
        configuration = FiniteRowsCandidateConfiguration.Read(assemblyPath);
        using (var process = Process.GetCurrentProcess())
            if (configuration.RecordedAt >= process.StartTime.ToUniversalTime() || configuration.RecordedAt > DateTimeOffset.UtcNow)
                throw new InvalidOperationException("File identity record must predate game launch.");
        var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant();
        context = new(Environment.ProcessId, Guid.NewGuid().ToString("D"), hash,
            VerifiedWindowsBuild.GameAssemblySha256, configuration.WindowClass, platform.ThreadId);
        admission = new(context);
        Directory.CreateDirectory(configuration.PrivateRoot);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(configuration.PrivateRoot);
        privateFiles = new(configuration.PrivateRoot);
        WritePrivate("session.json", new { schema_version = 4, mode = "goalkeeper_rows0_3", pid = context.Pid,
            session_id = context.Session, bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash,
            exe_sha256 = VerifiedWindowsBuild.ExecutableSha256, window_class = context.ConfirmedWindowClass,
            entry_tid = context.EntryThread, finite_rows_enabled_by_default = false, raw_diagnostics_only = true,
            allowed_scopes = new[] { "goalkeeper_rows0_3", "profile_rows0_3", "profile_all_rows", "tactics_current", "tactics_alignment_candidate", "tactics_sibling_inventory", "tactics_layout_diagnostic", "tactics_remaining_diagnostic", "tactics_ineligible_text7", "next_match_card", "schedule_rows0_9" }, maximum_chunks = 18, cooldown_ms = 2000,
            per_chunk_ms = 1000, per_chunk_units = 2048, total_ms = 18000, total_units = 36864,
            page_identity_verified = false, page_epoch_is_operator_assertion = true });
        WriteState(); _ = Task.Run(WriteEvidence);
        timer = platform.Start(Tick, 1000);
        if (timer == 0) { evidence.Writer.TryComplete(); throw new InvalidOperationException("Finite timer unavailable."); }
        _ = Task.Run(PrepareAndReadManifest);
    }
    private void WritePrivate(string name, object value) => privateFiles.Write(name, value);
    private void WriteState() => WritePrivate("finite-rows-state.json", new
    {
        pid = context.Pid, session_id = context.Session, bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash,
        consumed = admission.Taken, terminal = Volatile.Read(ref terminal) != 0,
        outcome = Volatile.Read(ref outcome), last_successful_chunk = Volatile.Read(ref lastSuccessfulChunk), last_failed_chunk = Volatile.Read(ref lastFailedChunk),
        failure_reason = Volatile.Read(ref failureReason), batch_id = batch?.Approval.BatchId, page_epoch = batch?.Approval.PageEpoch,
        chunks_consumed = batch?.ChunksConsumed ?? 0, total_units = batch?.TotalOperations ?? 0,
        total_elapsed_ms = batch?.TotalMilliseconds ?? 0, manifest_name = batch?.Approval.Manifest,
        declared_chunks = batch?.MaximumDeclaredChunks ?? 0, declared_units = batch?.MaximumDeclaredOperations ?? 0,
        declared_ms = batch?.MaximumDeclaredMilliseconds ?? 0
    });
    private void Record(object value) => evidence.Writer.TryWrite(value);
    private async Task WriteEvidence()
    {
        var path = Path.Combine(configuration.PrivateRoot, "finite-rows-evidence.jsonl");
        await foreach (var item in evidence.Reader.ReadAllAsync())
            try
            {
                WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
                await File.AppendAllTextAsync(path, JsonSerializer.Serialize(item) + Environment.NewLine);
                WriteState();
            }
            catch { /* No private writer exception crosses a native callback. */ }
    }
    private async Task PrepareAndReadManifest()
    {
        try
        {
            var prepared = WindowsLoadedModuleLease.Acquire(configuration.Module);
            lock (moduleStatusGate)
            {
                if (Volatile.Read(ref stopped) != 0) { prepared.Dispose(); return; }
                Volatile.Write(ref lease, prepared);
                WritePrivate("module-status.json", new { state = "ready", pid = context.Pid, session_id = context.Session,
                    bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash, il2cpp_calls = 0 });
            }
            while (!cancel.IsCancellationRequested && Volatile.Read(ref terminal) == 0)
            {
                try
                {
                    var read = FiniteRowsCandidateConfiguration.ReadRequest(Path.Combine(configuration.PrivateRoot,
                        FiniteRowsCandidateConfiguration.RequestName));
                    Volatile.Write(ref manifest, read);
                    return; // Retain ONE immutable manifest. Never reread/requeue/retry a replacement.
                }
                catch (FileNotFoundException) { }
                await Task.Delay(250, cancel.Token);
            }
        }
        catch (OperationCanceledException) when (cancel.IsCancellationRequested) { }
        catch (Exception error)
        {
            Fail("finite_preparation_or_manifest_failed_no_retry", error.GetType().Name);
        }
    }
    private void Tick(nuint id)
    {
        if (Interlocked.Exchange(ref entered, 1) != 0) return;
        try
        {
            if (id == 0 || id != timer) return;
            if (Volatile.Read(ref stopped) != 0 || Volatile.Read(ref terminal) != 0) { CancelOnOwner(); return; }
            var ready = Volatile.Read(ref lease); var pending = Volatile.Read(ref manifest);
            if (ready is null || pending is null) return; // No native scan without explicit immutable manifest.
            if (batch is null)
            {
                batch = admission.TryTake(pending, DateTimeOffset.UtcNow);
                if (batch is null) { Fail("finite_manifest_rejected_no_retry"); return; }
            }
            if (batch.Terminal || DateTimeOffset.UtcNow >= batch.Approval.ExpiresAt)
            { batch.Stop(); Fail("finite_terminal_or_expired"); return; }
            if (Monotonic() < batch.NotBeforeMonotonicMilliseconds) return; // No scan during cooldown.
            RunChunk(ready, batch);
            if (batch.Terminal) { Volatile.Write(ref terminal, 1); CancelOnOwner(); }
        }
        catch (Exception error)
        {
            batch?.Stop(); Fail("finite_callback_failed_no_retry", error.GetType().Name);
        }
        finally { Volatile.Write(ref entered, 0); }
    }
    private void RunChunk(WindowsLoadedModuleLease ready, FiniteRowsPolicy policy)
    {
        // Starts BEFORE outer admission/full-window scan, including all semantic and cleanup costs.
        var started = Stopwatch.GetTimestamp(); var startedMono = Monotonic(); var startedUtc = DateTimeOffset.UtcNow;
        var index = policy.NextChunkIndex;
        var nonce = policy.NonceAt(index);
        var request = new FiniteRowsRequest(4, policy.Approval.BatchId, policy.Approval.PageEpoch, index, nonce, policy.ApprovalSha256);
        var grant = policy.TryBegin(request, MainThreadGuard.ReadWindowsScanIdentity(context.EntryThread), startedUtc, startedMono);
        if (grant is null) { Volatile.Write(ref lastFailedChunk, index); Fail("finite_admission_failed_no_retry"); return; }
        DiscoveryPolicy? child = null; DiscoveryResult? result = null;
        string[] labels = Array.Empty<string>(); var valid = false; string? errorType = null; string? category = null; string? sourceKind = null;
        DateTimeOffset captureStartedUtc = DateTimeOffset.UtcNow, captureFinishedUtc;
        try
        {
            if (!FiniteCaptureSelection.TryGet(grant.SelectionProfile, out var selection) ||
                selection.RowStart != grant.RowStart || selection.RowCount != grant.RowCount)
                throw new InvalidOperationException("Finite selection profile mismatch.");
            category = selection.Category; sourceKind = selection.Kind;
            child = new DiscoveryPolicy(new(context, nonce, 0, selection.FocusRoot,
                policy.Approval.CreatedAt, policy.Approval.ExpiresAt, true, grant.SelectionProfile),
                () => policy.CheckActive(grant, DateTimeOffset.UtcNow, Monotonic(), cancel.Token), requiredWindow: grant.Window);
            var token = new DiscoveryRequest(3, nonce, child.ApprovalSha256);
            captureStartedUtc = DateTimeOffset.UtcNow;
            result = ready.RunDiscoveryOnce(child, token, cancel.Token);
            captureFinishedUtc = DateTimeOffset.UtcNow;
            if (sourceKind == "attributes")
            {
                valid = result is not null && GroupedDiscoveryValidation.TryValidate(result, grant.SelectionProfile, out labels);
                if (valid && (seenLabels.Count + labels.Length > 35 ||
                    labels.Any(label => seenLabels.Contains((category!, label))))) valid = false;
            }
            else valid = (sourceKind is "tactics_ineligible_probe" or "tactics_remaining_probe" or "tactics_frontier_probe" or "tactics_sibling_probe" or "tactics_alignment" or "tactics" or "next_match" or "schedule") &&
                result is not null && PageDiscoveryValidation.TryValidate(result, grant.SelectionProfile);
        }
        catch (Exception error)
        {
            captureFinishedUtc = DateTimeOffset.UtcNow;
            child?.Stop(); errorType = error.GetType().Name;
        }
        var operations = child?.TotalOperations ?? 0;
        var elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
        var accepted = policy.Finish(grant, operations, elapsed, valid, DateTimeOffset.UtcNow, Monotonic());
        if (accepted)
        {
            if (sourceKind == "attributes") foreach (var label in labels) seenLabels.Add((category!, label));
            Volatile.Write(ref lastSuccessfulChunk, index);
            if (policy.Terminal) Volatile.Write(ref outcome, "completed");
        }
        else
        {
            policy.Stop();
            Volatile.Write(ref lastFailedChunk, index);
            var reason = valid ? "finite_accounting_rejected" : result is null ? "finite_capture_unavailable" :
                result.Status != "raw_diagnostics" ? result.Reason : "finite_semantic_or_duplicate_validation_failed";
            Volatile.Write(ref failureReason, reason.Length <= 128 ? reason : "finite_capture_failed");
            Volatile.Write(ref outcome, cancel.IsCancellationRequested ? "cancelled" : "failed");
            Volatile.Write(ref terminal, 1);
        }
        if (policy.Terminal) Volatile.Write(ref terminal, 1);
        var publication = DiscoveryPublication.Create(result, accepted);
        Record(new { phase = "finite_rows_chunk_result", schema_version = 4, pid = context.Pid, session_id = context.Session,
            bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash, entry_tid = context.EntryThread,
            callback_tid = platform.ThreadId, batch_id = policy.Approval.BatchId, page_epoch = policy.Approval.PageEpoch,
            page_epoch_is_operator_assertion = true, chunk_index = index, nonce, selection_profile = grant.SelectionProfile,
            manifest_name = policy.Approval.Manifest, source_kind = sourceKind, category_key = category, row_start = grant.RowStart, row_count = grant.RowCount,
            declared_chunks = policy.MaximumDeclaredChunks, declared_units = policy.MaximumDeclaredOperations,
            declared_ms = policy.MaximumDeclaredMilliseconds,
            capture_started_at = captureStartedUtc, capture_finished_at = captureFinishedUtc,
            chunk_started_at = startedUtc, chunk_finished_at = DateTimeOffset.UtcNow,
            result = publication.Result, focus_diagnostic = publication.FocusDiagnostic, focus_edges = publication.FocusEdges, topology = publication.Topology, accepted, error = errorType, operations, elapsed_ms = elapsed,
            outcome = Volatile.Read(ref outcome), last_successful_chunk = Volatile.Read(ref lastSuccessfulChunk), last_failed_chunk = Volatile.Read(ref lastFailedChunk),
            failure_reason = Volatile.Read(ref failureReason),
            total_units = policy.TotalOperations, total_elapsed_ms = policy.TotalMilliseconds,
            page_identity_verified = false, snapshot_atomic = false, business_facts = false, terminal = policy.Terminal });
    }
    private void Fail(string phase, string? error = null)
    {
        Volatile.Write(ref terminal, 1);
        Volatile.Write(ref failureReason, phase);
        Volatile.Write(ref outcome, cancel.IsCancellationRequested ? "cancelled" : "failed");
        Record(new { phase, error, terminal = true, outcome = Volatile.Read(ref outcome), page_identity_verified = false });
        CancelOnOwner();
    }
    private void CancelOnOwner()
    { if (platform.ThreadId == context.EntryThread && timer != 0 && platform.Kill(timer)) timer = 0; }
    public void Dispose()
    {
        if (Interlocked.Exchange(ref stopped, 1) != 0) return;
        Volatile.Write(ref terminal, 1); cancel.Cancel(); batch?.Stop();
        if (Volatile.Read(ref outcome) == "running") Volatile.Write(ref outcome, "cancelled");
        try
        {
            lock (moduleStatusGate)
                WritePrivate("module-status.json", new { state = "stopped", pid = context.Pid, session_id = context.Session,
                    bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash });
            WriteState();
        }
        catch { /* Shutdown diagnostics never escape a callback or become game actions. */ }
        if (Interlocked.Exchange(ref entered, 1) == 0)
        { try { CancelOnOwner(); } finally { Volatile.Write(ref entered, 0); } }
        // Verified lease retained until process exit, never raced against in-flight callbacks.
        evidence.Writer.TryComplete();
    }
}
