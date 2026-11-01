using System.Diagnostics;
using System.Globalization;

namespace FootballAssistant.GameBridge;

// Deliberately NOT BatchText/BatchChunkResult: these are unverified UI observations,
// not player facts, anchors or an atomic page snapshot. No conversion/merge API.
internal sealed record DiscoveryText(string Path, string Text);
// Existing reads only. Depth -1 means no panel root was obtained; child count -1 means
// the current attempted edge has no completed count read. Stage identifies an attempt,
// not a completed native call or an inferred cause. No object identity or raw UI data.
internal sealed record DiscoveryFocusDiagnostic(int ResolvedDepth, int AttemptedEdge,
    int RequestedChildIndex, int ObservedChildCount, int Stage);
internal readonly record struct DiscoveryFocusEdge(int Depth, int RequestedChildIndex,
    int ObservedChildCount, int Stage);
// Numeric existing-read topology; -1 means unknown/not read. Stages: entered1,
// visibility2, type3, count4. Parent -1/edge -1 denotes the selected subtree root.
internal readonly record struct DiscoveryTopologyNode(int ParentRecordIndex, int ChildEdge,
    int GlobalDepth, int Visible, int TextElement, int ChildCount, int Stage);
internal sealed record DiscoveryResult(string Status, string Reason, DiscoveryText[] Observations,
    int NativeOperations, double ElapsedMilliseconds, int Nodes, int TotalRoots, int PeakRoots,
    bool TraversalBounded, DiscoveryRequest Request, int PanelIndex, string FocusPath)
{
    public bool PageIdentityVerified => false;
    public string SelectionProfile { get; init; } = "single";
    public DiscoveryFocusDiagnostic? FocusDiagnostic { get; init; }
    public DiscoveryFocusEdge[]? FocusEdges { get; init; }
    public DiscoveryTopologyNode[]? Topology { get; init; }
}

// Shared host publication boundary: never expose rejected raw text, even if only
// outer semantic validation failed after a successful capture. Numeric diagnostics
// are explicitly separate so a null result cannot erase the failure location.
internal sealed record DiscoveryPublication(
    [property: System.Text.Json.Serialization.JsonPropertyName("result")] DiscoveryResult? Result,
    [property: System.Text.Json.Serialization.JsonPropertyName("focus_diagnostic")] DiscoveryFocusDiagnostic? FocusDiagnostic,
    [property: System.Text.Json.Serialization.JsonPropertyName("focus_edges")] DiscoveryFocusEdge[]? FocusEdges = null,
    [property: System.Text.Json.Serialization.JsonPropertyName("topology")] DiscoveryTopologyNode[]? Topology = null)
{
    internal static DiscoveryPublication Create(DiscoveryResult? result, bool accepted) =>
        new(accepted ? result : null, result?.FocusDiagnostic, result?.FocusEdges, result?.Topology);
}

internal static class DiscoveryCollector
{
    internal const int MaximumDepth = 32, MaximumNodes = 96, MaximumTexts = 8;
    // Cooperative stop, not a larger budget or a guarantee that cleanup finishes in time.
    // Native safety failures and actual hard-budget exceptions always discard observations.
    private const int WorkOperations = 1792;
    private const double WorkMilliseconds = 800;

    internal static DiscoveryResult? Run(DiscoveryPolicy policy, DiscoveryRequest request,
        Func<BatchNativeBackend> createBackend, Func<WindowsThreadIdentity> freshIdentity,
        Func<DateTimeOffset> now, CancellationToken cancellation = default, Func<double>? elapsedForTest = null)
        => RunCore(policy, request, createBackend, freshIdentity, now, cancellation, elapsedForTest, targetedRow: false);

    internal static DiscoveryResult? RunCore(DiscoveryPolicy policy, DiscoveryRequest request,
        Func<BatchNativeBackend> createBackend, Func<WindowsThreadIdentity> freshIdentity,
        Func<DateTimeOffset> now, CancellationToken cancellation, Func<double>? elapsedForTest, bool targetedRow)
    {
        // Admission full-scan time is part of this request, not hidden pre-budget work.
        var started = Stopwatch.GetTimestamp();
        var grant = policy.TryBegin(request, freshIdentity(), now());
        if (grant is null) return null;
        var accounted = false;
        UiSmokeBudget? budget = null; Func<double>? elapsed = null;
        try
        {
            elapsed = elapsedForTest ?? (() => Stopwatch.GetElapsedTime(started).TotalMilliseconds);
            budget = new UiSmokeBudget(elapsed, () =>
            {
                cancellation.ThrowIfCancellationRequested();
                if (!policy.CheckActive(grant, freshIdentity(), now(), cancellation))
                    throw new UiSmokeStopped("discovery_grant_changed");
            }, 1000, 2048);
            var texts = new List<DiscoveryText>(MaximumTexts);
            var nodes = 0; var roots = 0; var peak = 0; var bounded = false;
            var success = false; var reason = "diagnostic_failure";
            var focusDepth = -1; var focusEdge = -1; var focusIndex = -1;
            var focusCount = -1; var focusStage = 0;
            // One fixed candidate only. Value-type slots allocated before any native invocation.
            var alignment = policy.Approval.SelectionProfile == "tactics_alignment_candidate";
            var siblingDepth = policy.Approval.SelectionProfile switch {
                "tactics_sibling12" => 12, "tactics_sibling7" => 7, "tactics_sibling4" => 4, _ => -1 };
            var sibling = siblingDepth >= 0;
            var topology = sibling ? new DiscoveryTopologyNode[MaximumNodes] : null;
            var topologyCount = 0;
            var focusTrace = alignment || sibling ? new DiscoveryFocusEdge[35] : null;
            var focusTraceCount = 0;
            void TraceFocus()
            {
                if (focusTrace is null) return;
                if (focusEdge is < 0 or >= 35) throw new UiSmokeStopped("alignment_trace_bound");
                focusTrace[focusEdge] = new(focusDepth, focusIndex, focusCount, focusStage);
                focusTraceCount = focusEdge + 1;
            }
            BatchNativeBackend? backend = null;
            try
            {
                budget.Check();
                if ((!targetedRow && policy.Approval.SelectionProfile != "single") ||
                    targetedRow && (policy.Approval.PanelIndex != 0 ||
                    policy.Approval.FocusPath != TargetedDiscoveryCollector.TargetFocus(policy.Approval.SelectionProfile)))
                    throw new UiSmokeStopped("target_scope_mismatch");
                backend = createBackend();
                if (backend.VerifiedModuleHash != policy.Approval.Context.GameHash)
                    throw new UiSmokeStopped("discovery_module_mismatch");
                backend.Prepare(budget);
                void Charge()
                {
                    budget.Check();
                    if (nodes >= MaximumNodes) throw new UiSmokeStopped("discovery_node_budget");
                    nodes++;
                }
                bool StopWork()
                {
                    if (texts.Count >= MaximumTexts || nodes >= MaximumNodes ||
                        budget.Operations >= WorkOperations || elapsed() >= WorkMilliseconds)
                    { bounded = true; return true; }
                    return false;
                }
                void Visit(BatchObject node, int depth, string path, int parentRecord = -1, int childEdge = -1)
                {
                    if (StopWork()) return;
                    Charge();
                    var record = topology is null ? -1 : topologyCount++;
                    var visible = -1; var textElement = -1; var childCount = -1; var stage = 1;
                    void TraceNode() {
                        if (topology is not null) topology[record] = new(parentRecord, childEdge,
                            depth, visible, textElement, childCount, stage);
                    }
                    TraceNode();
                    visible = backend.Visible(node, budget) ? 1 : 0; stage = 2; TraceNode();
                    if (visible == 0) { if (sibling) bounded = true; return; }
                    textElement = backend.IsTextElement(node, budget) ? 1 : 0; stage = 3; TraceNode();
                    if (textElement == 1 && backend.Bounds(node, budget).PositiveFinite)
                    {
                        // Complete text only. No silently truncated name/anchor candidates.
                        var text = backend.ReadAnchorText(node, budget);
                        if (!string.IsNullOrWhiteSpace(text)) texts.Add(new(path, text));
                    }
                    if (StopWork()) return;
                    var count = backend.ChildCount(node, budget);
                    childCount = count; stage = 4; TraceNode();
                    var maximumDepth = sibling ? TargetedDiscoveryCollector.MaximumDepth : MaximumDepth;
                    if (count > 8 || (depth >= maximumDepth && count > 0)) bounded = true;
                    if (depth >= maximumDepth) return;
                    // Single-pass child0-first DFS. Global depth32 (fixed probe48);
                    // scoped root stack plus transient boxes remains below live64.
                    // no sibling prefetch, pointer cursor or handle survives this request.
                    for (var index = 0; index < Math.Min(count, 8); index++)
                    {
                        if (StopWork()) break;
                        using var child = backend.Child(node, index, budget);
                        if (child is null) throw new UiSmokeStopped("discovery_child_unavailable");
                        Visit(child, depth + 1, Join(path, index), record, index);
                    }
                }
                void VisitTargets(BatchObject node, int depth, string path, int[][] suffixes)
                {
                    // This is a fixed selector trie, never a caller-provided list or DFS fallback.
                    if (depth > TargetedDiscoveryCollector.MaximumDepth || StopWork())
                        throw new UiSmokeStopped("target_work_limit");
                    Charge();
                    if (!backend.Visible(node, budget)) throw new UiSmokeStopped("target_hidden");
                    if (suffixes.Any(suffix => suffix.Length == 0))
                    {
                        if (!backend.IsTextElement(node, budget) || !backend.Bounds(node, budget).PositiveFinite)
                            throw new UiSmokeStopped("target_text_unavailable");
                        var text = backend.ReadAnchorText(node, budget);
                        if (string.IsNullOrWhiteSpace(text)) throw new UiSmokeStopped("target_text_unavailable");
                        texts.Add(new(path, text));
                    }
                    var indices = suffixes.Where(suffix => suffix.Length > 0)
                        .Select(suffix => suffix[0]).Distinct().OrderBy(index => index).ToArray();
                    if (indices.Length == 0) return;
                    if (depth >= TargetedDiscoveryCollector.MaximumDepth)
                        throw new UiSmokeStopped("target_depth_budget"); // Never obtain a depth49 child.
                    var count = backend.ChildCount(node, budget);
                    foreach (var index in indices)
                    {
                        if (StopWork()) throw new UiSmokeStopped("target_work_limit");
                        if (index >= count) throw new UiSmokeStopped("target_child_unavailable");
                        var remaining = suffixes.Where(suffix => suffix.Length > 0 && suffix[0] == index)
                            .Select(suffix => suffix.Skip(1).ToArray()).ToArray();
                        using var child = backend.Child(node, index, budget);
                        if (child is null) throw new UiSmokeStopped("target_child_unavailable");
                        VisitTargets(child, depth + 1, Join(path, index), remaining);
                    }
                }
                focusStage = 1; // Opening panel; no resolved prefix until it returns a root.
                BatchObject? current = backend.OpenPanel(policy.Approval.PanelIndex, budget);
                if (current is null) throw new UiSmokeStopped("discovery_panel_unavailable");
                focusDepth = 0;
                try
                {
                    var edges = policy.Approval.FocusPath.Length == 0 ? Array.Empty<int>() :
                        policy.Approval.FocusPath.Split('/').Select(x => int.Parse(x, CultureInfo.InvariantCulture)).ToArray();
                    foreach (var index in edges)
                    {
                        focusEdge = focusDepth; focusIndex = index; focusCount = -1;
                        focusStage = 2; // Ancestor charge/visibility precheck or call.
                        TraceFocus();
                        Charge();
                        if (!backend.Visible(current, budget)) throw new UiSmokeStopped("discovery_ancestor_hidden");
                        focusStage = 3; TraceFocus();
                        focusCount = backend.ChildCount(current, budget); TraceFocus();
                        // This is a hypothesis gate, not semantic identity. Never inspect a sibling.
                        if (alignment && focusDepth == 14 && focusCount != 1)
                            throw new UiSmokeStopped("alignment_parent_shape_changed");
                        if (sibling && focusDepth == siblingDepth && focusCount != 2)
                            throw new UiSmokeStopped("sibling_parent_shape_changed");
                        if (index >= focusCount) throw new UiSmokeStopped("discovery_focus_unavailable");
                        focusStage = 4; TraceFocus();
                        var child = backend.Child(current, index, budget);
                        if (child is null) throw new UiSmokeStopped("discovery_focus_unavailable");
                        current.Dispose(); current = child;
                        focusStage = 5; TraceFocus();
                        focusDepth++;
                    }
                    focusStage = 5; // Exact approved focus resolved; later failure is outside focus traversal.
                    focusEdge = -1; focusIndex = -1; focusCount = -1;
                    if (targetedRow && !sibling)
                        VisitTargets(current, edges.Length, policy.Approval.FocusPath, TargetedDiscoveryCollector.CreateTargets(policy.Approval.SelectionProfile));
                    else Visit(current, edges.Length, policy.Approval.FocusPath);
                }
                finally { current?.Dispose(); }
                success = true;
                reason = targetedRow && !sibling ? (policy.Approval.SelectionProfile == "single" ?
                    "approved_row_targets_complete" : "approved_group_targets_complete") :
                    bounded ? "bounded_raw_diagnostics" : "approved_prefix_exhausted";
            }
            catch (Exception error)
            {
                reason = error is UiSmokeStopped stopped ? stopped.Message :
                    error is OperationCanceledException ? "discovery_cancelled" : "discovery_backend_failure";
            }
            finally
            {
                if (backend is not null)
                {
                    roots = backend.TotalAllocated; peak = backend.PeakLiveRoots;
                    try { backend.Dispose(); }
                    catch { success = false; reason = "discovery_cleanup_failure"; }
                }
            }
            // Includes fresh identity check and its elapsed time after all root cleanup.
            try { budget.Check(); }
            catch { success = false; reason = "discovery_final_guard_failed"; }
            var observations = texts.ToArray();
            var traceSnapshot = focusTrace is null ? null : focusTrace.Take(focusTraceCount).ToArray();
            var topologySnapshot = topology is null ? null : topology.Take(topologyCount).ToArray();
            var spent = elapsed();
            success = policy.Finish(grant, budget.Operations, spent, success, now());
            accounted = true;
            if (!success)
            {
                observations = Array.Empty<DiscoveryText>();
                if (reason is "bounded_raw_diagnostics" or "approved_prefix_exhausted" or "approved_row_targets_complete" or "approved_group_targets_complete") reason = "discovery_accounting_rejected";
            }
            return new(success ? "raw_diagnostics" : "terminal_failure", reason, observations,
                budget.Operations, spent, nodes, roots, peak, bounded, request,
                policy.Approval.PanelIndex, policy.Approval.FocusPath) {
                    SelectionProfile = policy.Approval.SelectionProfile,
                    FocusDiagnostic = new(focusDepth, focusEdge, focusIndex, focusCount, focusStage),
                    FocusEdges = traceSnapshot,
                    Topology = topologySnapshot
                };
        }
        finally
        {
            if (!accounted)
            {
                policy.Stop();
                double spent;
                try { spent = elapsed?.Invoke() ?? Stopwatch.GetElapsedTime(started).TotalMilliseconds; }
                catch { spent = Stopwatch.GetElapsedTime(started).TotalMilliseconds; }
                DateTimeOffset ended;
                try { ended = now(); } catch { ended = DateTimeOffset.UtcNow; }
                policy.Finish(grant, budget?.Operations ?? 0, spent, false, ended);
            }
        }
    }
    private static string Join(string path, int index) => path.Length == 0 ? index.ToString(CultureInfo.InvariantCulture) :
        path + "/" + index.ToString(CultureInfo.InvariantCulture);
}
