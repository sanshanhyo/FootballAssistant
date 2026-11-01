using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using FootballAssistant.GameBridge;

// Standalone own-window test process. No candidate host, module lease or game backend compiled.
var mode = args.Length == 1 && args[0] == "components" ? 1 : args.Length == 1 && args[0] == "baseline" ? 0 : -1;
var results = new List<object>();
var status = 0;
var errorCode = 0;
var failureStage = 0;
long[] initialObservation = Array.Empty<long>();
try
{
    if (mode < 0) throw new BenchmarkFailure(1);
    if (!OperatingSystem.IsWindows()) throw new BenchmarkFailure(2);
    foreach (var windowCount in new[] { 1, 8, 31 })
    {
        failureStage = 1;
        using var windows = new OwnedWindows(windowCount);
        failureStage = 2;
        var tid = MainThreadGuard.CurrentWindowsThreadId();
        var components = new GuardComponents();
        WindowsThreadIdentity Read() => mode == 0 ? MainThreadGuard.ReadWindowsScanIdentity(tid) :
            WindowsGuardComponentScan.Read(tid, components);
        // First collector call precedes policy setup. Only scenario 1 is process-cold;
        // later scenarios are first observations of a new fixture, not cold JIT runs.
        var firstStart = Stopwatch.GetTimestamp();
        var first = Read();
        var firstTicks = Stopwatch.GetTimestamp() - firstStart;
        var own = first.WindowCandidates?.SingleOrDefault(x => x.Hwnd == windows.Primary.ToInt64());
        failureStage = 3;
        initialObservation = new long[] { windowCount, first.WindowScanStatus == "complete" ? 1 : 0,
            own is null ? 0 : 1, own?.OwnerStable == true ? 1 : 0, own?.ClassNameComplete == true ? 1 : 0,
            own?.VisibleStyle == true ? 1 : 0, own?.ClientRectAvailable == true ? 1 : 0,
            own?.ClientWidth ?? -1, own?.ClientHeight ?? -1, first.WindowScanCount, own?.OwnerTid == tid ? 1 : 0 };
        Require(first.WindowScanStatus == "complete" && own is { OwnerStable: true, ClassNameComplete: true,
            VisibleStyle: true, ClientRectAvailable: true, ClientWidth: > 0, ClientHeight: > 0 } &&
            first.WindowScanCount == windowCount && own.OwnerTid == tid, 2);
        failureStage = 4;
        var context = new SmokeContext(Environment.ProcessId, "own-window-benchmark", new string('a', 64),
            new string('b', 64), own!.ClassName!, tid);
        var policy = new WindowsSmokePolicy(context);
        var coldPolicyStart = Stopwatch.GetTimestamp();
        var selected = policy.SelectWindow(first);
        var firstPolicyTicks = Stopwatch.GetTimestamp() - coldPolicyStart;
        Require(selected == windows.Primary.ToInt64() && !first.Matches(), 3);
        SmokeRequest Request(SmokeStage stage)
        {
            var now = DateTimeOffset.UtcNow;
            return new(Guid.NewGuid(), context.Pid, context.Session, context.BridgeHash, context.GameHash,
                context.ConfirmedWindowClass, stage, now, now.AddSeconds(30));
        }
        // Grants authorize only pure policy checks here. No native game operation exists in this project.
        var metadata = policy.TryConsume(Request(SmokeStage.Metadata), first, DateTimeOffset.UtcNow)!;
        Require(metadata is not null && policy.TryBeginCall(metadata, first, DateTimeOffset.UtcNow), 3);
        policy.CompleteMetadata(metadata!, true);
        var grant = policy.TryConsume(Request(SmokeStage.UiResolve), first, DateTimeOffset.UtcNow)!;
        Require(grant is not null && policy.TryBeginCall(grant, first, DateTimeOffset.UtcNow), 3);
        // Component copy must produce the exact policy evidence of the production collector.
        // Compare only stable owned fixtures; foreign window handles/details are never retained/output.
        var original = MainThreadGuard.ReadWindowsScanIdentity(tid);
        var instrumented = WindowsGuardComponentScan.Read(tid, new GuardComponents());
        Require(original.WindowScanStatus == instrumented.WindowScanStatus &&
            original.ProcessId == instrumented.ProcessId && original.CurrentThreadId == instrumented.CurrentThreadId &&
            original.InstallerThreadId == instrumented.InstallerThreadId &&
            original.WindowScanCount == instrumented.WindowScanCount &&
            original.WindowCandidates!.SequenceEqual(instrumented.WindowCandidates!) &&
            policy.SelectWindow(original) == policy.SelectWindow(instrumented), 4);
        // Warm both policy/collector paths before measured batches; these do not enter aggregates.
        for (var i = 0; i < 16; i++) Require(policy.CheckStartedResolve(grant!, Read(), DateTimeOffset.UtcNow), 3);
        components.Clear();
        const int samples = 128;
        var identityTicks = new long[samples]; var grantTicks = new long[samples];
        var policyTicks = new long[samples]; var fullTicks = new long[samples];
        var visited = new int[samples]; var owned = new int[samples];
        var allocatedBefore = GC.GetAllocatedBytesForCurrentThread();
        for (var i = 0; i < samples; i++)
        {
            var start = Stopwatch.GetTimestamp();
            var identity = Read();
            var identityEnd = Stopwatch.GetTimestamp();
            var permitted = policy.CheckStartedResolve(grant!, identity, DateTimeOffset.UtcNow);
            var grantEnd = Stopwatch.GetTimestamp();
            identityTicks[i] = identityEnd - start; grantTicks[i] = grantEnd - identityEnd;
            fullTicks[i] = grantEnd - start;
            var policyStart = Stopwatch.GetTimestamp();
            var window = policy.SelectWindow(identity);
            policyTicks[i] = Stopwatch.GetTimestamp() - policyStart;
            Require(permitted && window == windows.Primary.ToInt64(), 3);
            visited[i] = identity.WindowScanVisited; owned[i] = identity.WindowScanCount;
        }
        var allocated = GC.GetAllocatedBytesForCurrentThread() - allocatedBefore;
        var componentMicroseconds = components.Ticks.Select(Microseconds).ToArray();
        var componentCalls = components.Calls.ToArray();
        // Native deny checks, outside measurement; never inspect or change other-process windows.
        windows.ShowSecond();
        if (windowCount > 1)
        {
            var duplicate = Read();
            Require(duplicate.WindowScanStatus == "complete" && duplicate.WindowScanCount == windowCount &&
                duplicate.WindowCandidates!.Count(x => x.ClassName == context.ConfirmedWindowClass && x.VisibleStyle &&
                    x.OwnerStable && x.ClientRectAvailable && x.ClientWidth > 0 && x.ClientHeight > 0) == 2 &&
                policy.SelectWindow(duplicate) is null, 5);
        }
        windows.HideSecond();
        var workerIdentity = Task.Run(() => MainThreadGuard.ReadWindowsScanIdentity(tid)).GetAwaiter().GetResult();
        Require(workerIdentity.WindowScanStatus == "complete" && workerIdentity.WindowScanCount == windowCount &&
            workerIdentity.CurrentThreadId != tid && workerIdentity.InstallerThreadId == tid &&
            workerIdentity.ProcessId == (uint)Environment.ProcessId && policy.SelectWindow(workerIdentity) is null &&
            policy.SelectWindow(workerIdentity with { CurrentThreadId = tid }) == windows.Primary.ToInt64(), 5);
        policy.CompleteResolve(grant!, true);
        results.Add(new
        {
            owned_windows = windowCount, samples, first_identity_us = Microseconds(firstTicks),
            first_policy_us = Microseconds(firstPolicyTicks), process_cold = windowCount == 1 ? 1 : 0,
            identity = Summary(identityTicks), grant = Summary(grantTicks), policy = Summary(policyTicks),
            full_guard = Summary(fullTicks), loop_allocated_bytes = allocated,
            visited_min = visited.Min(), visited_max = visited.Max(), owned_min = owned.Min(), owned_max = owned.Max(),
            components_us = componentMicroseconds, component_calls = componentCalls
        });
    }
    using (var boundedWindows = new OwnedWindows(32))
    {
        var bounded = MainThreadGuard.ReadWindowsScanIdentity(MainThreadGuard.CurrentWindowsThreadId());
        Require(bounded.WindowScanStatus == "bounded" && bounded.WindowScanCount == 32 &&
            bounded.WindowCandidates?.Length == 32, 5);
    }
}
catch (BenchmarkFailure failure) { errorCode = failure.Code; status = errorCode == 2 ? 2 : 1; }
catch { status = 1; errorCode = 6; } // Never print OS exceptions, stack paths, identities or window data.
string Output() => JsonSerializer.Serialize(new { schema_version = 1, status, error_code = errorCode, mode,
    failure_stage = failureStage, initial_observation = initialObservation,
    stopwatch_frequency = Stopwatch.Frequency, scenarios = results });
var output = Output();
try
{
    if (mode >= 0) File.WriteAllText(mode == 0 ? "guard-benchmark-baseline.json" : "guard-benchmark-components.json", output);
}
catch { status = 1; errorCode = 8; output = Output(); }
Console.WriteLine(output);
Environment.ExitCode = status == 0 ? 0 : status == 2 ? 2 : 1;

static void Require(bool condition, int code) { if (!condition) throw new BenchmarkFailure(code); }
static long Microseconds(long ticks) => (long)Math.Round(ticks * 1_000_000.0 / Stopwatch.Frequency);
static object Summary(long[] values)
{
    var sorted = values.Order().ToArray();
    return new { min_us = Microseconds(sorted[0]), median_us = Microseconds(sorted[sorted.Length / 2]),
        p95_us = Microseconds(sorted[(int)Math.Ceiling(sorted.Length * .95) - 1]), max_us = Microseconds(sorted[^1]) };
}
sealed class BenchmarkFailure(int code) : Exception { internal int Code => code; }

sealed class OwnedWindows : IDisposable
{
    private readonly List<nint> windows = new();
    internal nint Primary => windows[0];
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern nint CreateWindowExW(uint exStyle, string className, string title, uint style,
        int x, int y, int width, int height, nint parent, nint menu, nint instance, nint parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DestroyWindow(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ShowWindow(nint window, int command);
    internal OwnedWindows(int count)
    {
        try
        {
            for (var i = 0; i < count; i++)
            {
                // No title; nonactivating visible popup, remaining windows hidden.
                var window = CreateWindowExW(0x08000000, "STATIC", "", 0x80000000 | (i == 0 ? 0x10000000u : 0),
                    0, 0, 64, 48, 0, 0, 0, 0);
                if (window == 0) throw new BenchmarkFailure(2);
                windows.Add(window);
            }
        }
        catch { Dispose(); throw; }
    }
    internal void ShowSecond() { if (windows.Count > 1) ShowWindow(windows[1], 4); }
    internal void HideSecond() { if (windows.Count > 1) ShowWindow(windows[1], 0); }
    public void Dispose()
    {
        var failed = false;
        foreach (var window in windows) if (!DestroyWindow(window)) failed = true;
        windows.Clear();
        if (failed) throw new BenchmarkFailure(7);
    }
}
