using System.Diagnostics;

namespace FootballAssistant.GameBridge;

// Independent staged UI candidate only; ordinary production/probe never enables this reader.
internal readonly record struct UiSmokeBounds(float X, float Y, float Width, float Height)
{
    internal bool PositiveFinite => float.IsFinite(X) && float.IsFinite(Y) && float.IsFinite(Width) &&
        float.IsFinite(Height) && Width > 0 && Height > 0;
}
internal sealed record UiResolveResult(bool Success, string StopReason, double ElapsedMs, string StoppedStage, int NativeOperations, UiSmokeDiagnostics? Diagnostics = null);
internal sealed record UiSmokeResult(string? Text, string StopReason, int Nodes, int NativeOperations,
    double ElapsedMs, string StoppedStage, bool RootResolved, bool TextGetterSucceeded, string? ErrorType = null, UiSmokeDiagnostics? Diagnostics = null);
internal sealed class UiSmokeStopped : Exception { internal UiSmokeStopped(string reason) : base(reason) { } }

// Fixed allowlisted labels and numeric aggregates only: never object identities, text or paths.
// Stage time includes guard time; do not add the two totals. MaxMs is a contiguous stage
// interval, NOT an individual getter duration. Prechecks are not native invocation counts.
internal sealed record UiSmokeStageDiagnostics(string Stage, int Intervals, double TotalMs, double MaxMs,
    int PrechecksCompleted, int PrechecksFailed, int GuardCalls, int GuardFailures, double GuardTotalMs, double GuardMaxMs);
internal sealed record UiSmokeDiagnostics(int SchemaVersion, double ElapsedMs, UiSmokeStageDiagnostics[] Stages);

// Every export/invoke/memory access retains its existing fresh gate and reservation.
internal sealed class UiSmokeBudget
{
    private static readonly string[] StageNames = { "before_resolution", "resolve_first_panel", "first_panel_root",
        "resolve_ui_classes", "resolve_ui_methods", "visible", "world_bounds", "text_type", "text_getter",
        "child_count", "child_index", "unknown" };
    private struct StageCounters
    {
        internal int Intervals, PrechecksCompleted, PrechecksFailed, GuardCalls, GuardFailures;
        internal double TotalMs, MaxMs, GuardTotalMs, GuardMaxMs;
    }
    private readonly StageCounters[] counters = new StageCounters[12];
    private readonly Func<double> elapsedMilliseconds;
    private readonly Action verifyGrantAndWindow;
    private readonly double maximumMilliseconds;
    private readonly int maximumOperations;
    private int stageIndex;
    private double stageStarted; // Stopwatch starts before budget construction; account for setup too.
    internal int Operations { get; private set; }
    internal string Stage
    {
        get => StageNames[stageIndex];
        set
        {
            var next = Array.IndexOf(StageNames, value);
            if (next < 0) next = StageNames.Length - 1;
            if (next == stageIndex) return;
            var now = elapsedMilliseconds();
            AddInterval(ref counters[stageIndex], now - stageStarted);
            stageStarted = now; stageIndex = next;
        }
    }
    private static void AddInterval(ref StageCounters counter, double elapsed)
    {
        counter.Intervals++; counter.TotalMs += elapsed;
        counter.MaxMs = Math.Max(counter.MaxMs, elapsed);
    }
    internal double ElapsedMs => elapsedMilliseconds();
    internal UiSmokeBudget(Func<double> elapsedMilliseconds, Action verifyGrantAndWindow,
        double maximumMilliseconds = 100, int maximumOperations = 384)
    { this.elapsedMilliseconds = elapsedMilliseconds; this.verifyGrantAndWindow = verifyGrantAndWindow;
      this.maximumMilliseconds = maximumMilliseconds; this.maximumOperations = maximumOperations; }
    internal void Check()
    {
        ref var counter = ref counters[stageIndex];
        try
        {
            if (elapsedMilliseconds() > maximumMilliseconds) throw new UiSmokeStopped("time_budget");
            if (Operations >= maximumOperations) throw new UiSmokeStopped("native_call_budget");
            var start = elapsedMilliseconds();
            counter.GuardCalls++;
            try { verifyGrantAndWindow(); }
            catch { counter.GuardFailures++; throw; }
            finally
            {
                var elapsed = elapsedMilliseconds() - start;
                counter.GuardTotalMs += elapsed;
                counter.GuardMaxMs = Math.Max(counter.GuardMaxMs, elapsed);
            }
            counter.PrechecksCompleted++;
        }
        catch { counter.PrechecksFailed++; throw; }
    }
    internal void BeforeNative() { Check(); Operations++; }

    // Called only at completion, never between an unrooted return and gcNew. Copy fixed
    // counters so repeated snapshots do not double-count. Serialization stays off callback.
    internal UiSmokeDiagnostics Snapshot()
    {
        var now = elapsedMilliseconds();
        var stages = new UiSmokeStageDiagnostics[StageNames.Length];
        for (var index = 0; index < stages.Length; index++)
        {
            var c = counters[index];
            if (index == stageIndex) AddInterval(ref c, now - stageStarted);
            stages[index] = new(StageNames[index], c.Intervals, c.TotalMs, c.MaxMs,
                c.PrechecksCompleted, c.PrechecksFailed, c.GuardCalls, c.GuardFailures, c.GuardTotalMs, c.GuardMaxMs);
        }
        return new(1, now, stages);
    }
}

internal interface IWindowsUiSmokeBackend : IDisposable
{
    // Production implementation must be constructed only from the verified existing module lease.
    string VerifiedModuleHash { get; }
    nint ResolveFirstPanelRoot(UiSmokeBudget budget);
    bool Visible(nint element, UiSmokeBudget budget);
    UiSmokeBounds Bounds(nint element, UiSmokeBudget budget);
    bool IsTextElement(nint element, UiSmokeBudget budget);
    string ReadText(nint element, int maximumCodeUnits, UiSmokeBudget budget);
    int ChildCount(nint element, UiSmokeBudget budget);
    nint Child(nint element, int index, UiSmokeBudget budget);
}

internal static class WindowsSmokeReader
{
    // No host calls this. A future private backend factory must provide only a verified lease.
    // The fake interface is for tests, not a capability that may be accepted from configuration.
    internal static UiSmokeResult? TryReadAuthorized(WindowsSmokePolicy policy, SmokeRequest request,
        IWindowsUiSmokeBackend backend, Func<WindowsThreadIdentity> freshIdentity, Func<DateTimeOffset> now,
        CancellationToken cancellationToken = default, Func<double>? elapsedForTest = null)
    {
        if (request.Stage != SmokeStage.UiText || !policy.MatchesModuleHash(backend.VerifiedModuleHash)) return null;
        cancellationToken.ThrowIfCancellationRequested();
        var grant = policy.TryConsume(request, freshIdentity(), now());
        if (grant is null) return null;
        try
        {
            if (!policy.TryBeginCall(grant, freshIdentity(), now())) return null;
            return ReadOne(backend, () =>
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!policy.CheckStartedUi(grant, freshIdentity(), now())) throw new UiSmokeStopped("grant_or_window_changed");
            }, elapsedForTest);
        }
        finally { policy.CompleteUi(grant); }
    }

    // Core separated for traversal fixtures; it cannot authorize a native backend by itself.
    internal static UiSmokeResult ReadOne(IWindowsUiSmokeBackend backend, Action verifyGrantAndWindow,
        Func<double>? elapsedForTest = null)
    {
        var watch = Stopwatch.StartNew(); // Includes all class/getter/panel resolution.
        var budget = new UiSmokeBudget(elapsedForTest ?? (() => watch.Elapsed.TotalMilliseconds), verifyGrantAndWindow);
        var nodes = 0;
        var bounded = false;
        var rootResolved = false;
        var textGetterSucceeded = false;
        UiSmokeResult Finish(string? text, string reason, string? errorType = null)
        {
            var diagnostics = budget.Snapshot();
            return new(text, reason, nodes, budget.Operations, diagnostics.ElapsedMs, budget.Stage,
                rootResolved, textGetterSucceeded, errorType, diagnostics);
        }
        try
        {
            budget.Check();
            budget.Stage = "resolve_first_panel";
            var root = backend.ResolveFirstPanelRoot(budget);
            if (root == 0) return Finish(null, "root_unavailable");
            rootResolved = true;
            // Lazy DFS obtains one child at a time, not an eager list of 512 child objects.
            var stack = new Stack<(nint Element, int Depth, int NextChild, int ChildLimit)>();
            stack.Push((root, 0, -1, 0));
            while (stack.Count > 0)
            {
                budget.Check();
                var frame = stack.Pop();
                if (frame.NextChild < 0)
                {
                    if (nodes >= 32) return Finish(null, "node_budget");
                    nodes++;
                    budget.Stage = "visible";
                    if (!backend.Visible(frame.Element, budget)) continue; // Hidden ancestors prune descendants.
                    // Bounds gate text only, not descendant traversal. Avoid a boxed Rect getter
                    // and temporary GC root for non-text containers; retain every native gate.
                    budget.Stage = "text_type";
                    if (backend.IsTextElement(frame.Element, budget))
                    {
                        budget.Stage = "world_bounds";
                        var bounds = backend.Bounds(frame.Element, budget);
                        // Invalid parent bounds suppress parent text only; visible children may still be valid.
                        if (bounds.PositiveFinite)
                        {
                            budget.Stage = "text_getter";
                            var text = backend.ReadText(frame.Element, 128, budget);
                            textGetterSucceeded = true;
                            if (text.Length > 128) throw new InvalidOperationException("UI adapter violated bounded string contract.");
                            if (!string.IsNullOrWhiteSpace(text)) return Finish(text, "one_text");
                        }
                    }
                    budget.Stage = "child_count";
                    var count = backend.ChildCount(frame.Element, budget);
                    if (count < 0) throw new InvalidOperationException("Negative child count rejected.");
                    if (frame.Depth >= 8) { bounded |= count > 0; continue; }
                    bounded |= count > 8;
                    frame = (frame.Element, frame.Depth, 0, Math.Min(count, 8));
                }
                if (frame.NextChild >= frame.ChildLimit) continue;
                budget.Check();
                budget.Stage = "child_index";
                var child = backend.Child(frame.Element, frame.NextChild, budget);
                stack.Push((frame.Element, frame.Depth, frame.NextChild + 1, frame.ChildLimit));
                if (child != 0) stack.Push((child, frame.Depth + 1, -1, 0));
            }
            return Finish(null, bounded ? "bounded_no_text" : "no_eligible_text");
        }
        catch (UiSmokeStopped stopped) { return Finish(null, stopped.Message); }
        catch (Exception error) { return Finish(null, "backend_failure", error.GetType().Name); }
    }
}
