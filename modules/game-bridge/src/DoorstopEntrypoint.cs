using System.Diagnostics;
using System.Threading.Channels;
using System.Text.Json;
using System.Security.Cryptography;
using FootballAssistant.GameBridge;

namespace Doorstop;

// Doorstop 4 hosts this entry directly in CoreCLR. The optional BepInEx Plugin
// remains available separately; this path needs no generated Unity assemblies.
public static class Entrypoint
{
    private static IDisposable? runtime;
    private static int started;

    public static void Start()
    {
        if (Interlocked.Exchange(ref started, 1) != 0) return;
        try
        {
            // Windows is permanently probe-only in this candidate. No environment switch enables reads.
            runtime = OperatingSystem.IsWindows() ? new WindowsProbeRuntime() : new BridgeRuntime();
            AppDomain.CurrentDomain.ProcessExit += (_, _) => Stop();
        }
        catch (Exception error) { Console.Error.WriteLine($"[FootballAssistant] Startup unavailable ({error.GetType().Name}: {error.Message})"); }
    }

    public static void Stop() => runtime?.Dispose();
}

internal sealed class BridgeRuntime : IDisposable
{
    private readonly Channel<string> diagnostics = Channel.CreateBounded<string>(new BoundedChannelOptions(100) { SingleReader = true, FullMode = BoundedChannelFullMode.DropOldest });
    private readonly SnapshotPublisher publisher;
    private readonly InspectionPublisher inspections;
    private readonly MacMainThreadTimer scheduler;
    private readonly object captureGate = new();
    private readonly NativeObserverClient? nativeObserver;
    private readonly NativePacketClient? nativePackets;
    private readonly string privateRoot;
    private readonly string managedBuildSha;
    private readonly string gameAssembly;
    private readonly string sessionId = Guid.NewGuid().ToString();
    private NativeUiReader? reader;
    private readonly UiCaptureControl uiControl;
    private readonly CancellationTokenSource uiControlStop = new();
    private int failures;
    private bool mainThreadLogged;
    private int disposed;
    private sealed record InstallCheckpoint(DateTimeOffset ExpiresAt);
    private InstallCheckpoint? installCheckpoint;
    private int checkpointConsumed;

    public BridgeRuntime()
    {
        if (OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows candidate is probe-only; UI reads are disabled.");
        privateRoot = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_PRIVATE_ROOT") ?? throw new InvalidOperationException("Explicit private root is required.");
        managedBuildSha = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Entrypoint).Assembly.Location))).ToLowerInvariant();
        var runtimeFile = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_RUNTIME_FILE") ?? throw new InvalidOperationException("Explicit runtime connection file is required.");
        gameAssembly = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_ASSEMBLY") ?? throw new InvalidOperationException("Explicit GameAssembly path is required.");
        var logPath = Path.Combine(privateRoot, "logs", "bridge-bootstrap.log");
        _ = Task.Run(async () =>
        {
            await foreach (var line in diagnostics.Reader.ReadAllAsync())
            {
                try { await File.AppendAllTextAsync(logPath, line + Environment.NewLine); }
                catch (IOException) { Console.Error.WriteLine("[FootballAssistant] Private diagnostics write unavailable."); }
            }
        });
        publisher = new SnapshotPublisher(() => ConnectionSettings.Read(runtimeFile), Trace);
        inspections = new InspectionPublisher(privateRoot, runtimeFile, sessionId, Trace);
        if (Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_ENABLE_NATIVE_OBSERVER") == "1")
        {
            try
            {
                nativeObserver = new NativeObserverClient(privateRoot, Trace);
                try { nativePackets = new NativePacketClient(privateRoot, NativeObserverClient.ShimHash, Trace); }
                catch (Exception error) { Trace("Native packet channel unavailable (" + error.GetType().Name + "); header observation remains independent."); }
                _ = Task.Run(DrainNativeObserver);
            }
            catch (Exception error) { Trace("Native observer unavailable (" + error.GetType().Name + "); UI/registry readers continue."); }
        }
        File.WriteAllText(Path.Combine(privateRoot, "diagnostics", "host-session.json"), JsonSerializer.Serialize(new
        {
            pid = Environment.ProcessId, session_id = sessionId, adapter_version = ObservationFactory.AdapterVersion,
            managed_build_sha256 = managedBuildSha,
            game_plugin_sha256 = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_PLUGIN_SHA256"),
            observer_sha256 = NativeObserverClient.ShimHash,
            native_packet_abi_version = nativePackets is null ? (int?)null : 1,
            native_observer_enabled = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_ENABLE_NATIVE_OBSERVER") == "1"
        }));
        uiControl = new UiCaptureControl(privateRoot, Environment.ProcessId, sessionId, managedBuildSha);
        scheduler = new MacMainThreadTimer(Capture);
        _ = Task.Run(PollUiControl);
        Trace($"Own CoreCLR entry started; pid={Environment.ProcessId}; scheduler=CF-main-runloop; session={sessionId}.");
    }

    private void Trace(string text) => diagnostics.Writer.TryWrite($"{DateTimeOffset.UtcNow:O} {text}");

    private void Capture()
    {
        if (Volatile.Read(ref disposed) != 0 || failures >= 3 || !MainThreadGuard.IsCurrent() || !Monitor.TryEnter(captureGate)) return;
        try
        {
            if (Volatile.Read(ref disposed) != 0) return;
            if (!mainThreadLogged) { mainThreadLogged = true; Trace("OS main thread verified by pthread_main_np."); }
            reader ??= new NativeUiReader(gameAssembly);
            var checkpoint = Volatile.Read(ref installCheckpoint);
            if (nativeObserver is not null && nativeObserver.CanAttempt && checkpoint is not null && DateTimeOffset.UtcNow <= checkpoint.ExpiresAt && Interlocked.CompareExchange(ref checkpointConsumed, 1, 0) == 0)
            {
                try { nativeObserver.InstallAtMainMenuCheckpoint(); }
                catch (Exception error) { Trace("Native observer explicit checkpoint failed (" + error.GetType().Name + "); other readers continue."); }
            }
            var selection = uiControl.BeginCapture(DateTimeOffset.UtcNow);
            var text = reader.Capture(selection);
            if (text is UiCapture capture) uiControl.CompleteCapture(selection, capture, DateTimeOffset.UtcNow);
            if (text.Count == 0 && text is not UiCapture) Trace("Capture: no eligible UI tree text yet; no empty fact set published.");
            else
            {
                var build = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_BUILD") ?? (text.Count > 0 ? reader.ReadApplicationVersion() : null);
                var observation = ObservationFactory.Create(text, build, sessionId);
                var queued = publisher.Offer(observation);
                Trace($"Capture: raw_ui_tree_text_count={text.Count}; queued={queued}; partial=true; user_visibility_not_guaranteed.");
            }
            failures = 0;
            try
            {
                var budget = Stopwatch.StartNew();
                var registries = reader.ProbeExistingIdentifierRegistries();
                var enumerations = reader.AdvanceRegistryEnumerations(budget);
                inspections.Offer(reader.ReadProofs(), registries, enumerations, reader.GcHandleDiagnostic);
            }
            catch (Exception error) { Trace("Independent registry probe unavailable (" + error.GetType().Name + "); UI stream continues."); }
        }
        catch (Exception error)
        {
            failures++;
            Trace($"Capture unavailable ({error.GetType().Name}: {error.Message}); consecutive_failures={failures}.");
        }
        finally { Monitor.Exit(captureGate); }
    }

    // Independent of native observer and of the UI thread; never schedules an extra capture.
    private async Task PollUiControl()
    {
        while (!uiControlStop.IsCancellationRequested)
        {
            try
            {
                uiControl.Poll(DateTimeOffset.UtcNow);
                uiControl.WriteStatus();
            }
            catch (Exception error) { Trace("UI control status unavailable (" + error.GetType().Name + ")."); }
            try { await Task.Delay(1000, uiControlStop.Token); }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task DrainNativeObserver()
    {
        var directory = Path.Combine(privateRoot, "diagnostics", "native-channel");
        Directory.CreateDirectory(directory);
        while (Volatile.Read(ref disposed) == 0)
        {
            try
            {
                // This is a one-process/session operator signal after media has
                // confirmed the fresh main menu. UI tree strings are not a gate.
                var checkpointPath = Path.Combine(privateRoot, "control", "native-observer-checkpoint.json");
                if (Volatile.Read(ref checkpointConsumed) == 0 && File.Exists(checkpointPath) && new FileInfo(checkpointPath).Length <= 4096)
                {
                    using var document = JsonDocument.Parse(await File.ReadAllTextAsync(checkpointPath));
                    var signal = document.RootElement;
                    var requested = signal.GetProperty("requested_at").GetDateTimeOffset();
                    var current = DateTimeOffset.UtcNow;
                    if (signal.GetProperty("pid").GetInt32() == Environment.ProcessId && signal.GetProperty("session_id").GetString() == sessionId &&
                        signal.GetProperty("managed_build_sha256").GetString() == managedBuildSha &&
                        signal.GetProperty("game_plugin_sha256").GetString() == Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_PLUGIN_SHA256") &&
                        signal.GetProperty("checkpoint").GetString() == "fresh_main_menu_before_career" &&
                        requested <= current && current - requested <= TimeSpan.FromSeconds(30))
                        Volatile.Write(ref installCheckpoint, new InstallCheckpoint(requested.AddSeconds(30)));
                }
                var now = DateTimeOffset.UtcNow;
                var frame = new { session_id = sessionId, captured_at = now.ToString("O"), synthetic = false, snapshot = nativeObserver!.DrainSnapshot() };
                var json = JsonSerializer.Serialize(frame);
                var temporary = Path.Combine(privateRoot, "diagnostics", "native-observer.json.tmp");
                await File.WriteAllTextAsync(temporary, json);
                File.Move(temporary, Path.Combine(privateRoot, "diagnostics", "native-observer.json"), true);
                // Preserve each drained batch privately; cumulative drop counters
                // still describe any bounded native-queue observation gaps.
                await File.WriteAllTextAsync(Path.Combine(directory, now.ToString("yyyyMMddTHHmmssfffffff") + ".json"), json);
                try { nativePackets?.Tick(sessionId, managedBuildSha, nativeObserver.IsInstalled); }
                catch (Exception error) { Trace("Native one-shot packet drain unavailable (" + error.GetType().Name + "); headers/UI continue."); }
            }
            catch (Exception error) { Trace("Native diagnostic drain unavailable (" + error.GetType().Name + ")."); }
            await Task.Delay(1000);
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        uiControlStop.Cancel();
        scheduler.Dispose();
        nativeObserver?.StopCapture();
        publisher.Dispose();
        inspections.Dispose();
        Trace("Bridge stopped; future native reads cancelled; pending private diagnostics may drain.");
        diagnostics.Writer.TryComplete();
        void ReleaseReader()
        {
            lock (captureGate) { reader?.Dispose(); reader = null; }
        }
        // Stop never blocks the UI on a callback or network request.
        if (Monitor.TryEnter(captureGate))
        {
            try { reader?.Dispose(); reader = null; }
            finally { Monitor.Exit(captureGate); }
        }
        else _ = Task.Run(ReleaseReader);
    }
}
