using System.Diagnostics;
using System.Globalization;

namespace FootballAssistant.GameBridge;

// Deliberately NOT BatchText/BatchChunkResult: these are unverified UI observations,
// not player facts, anchors or an atomic page snapshot. No conversion/merge API.
internal sealed record DiscoveryText(string Path, string Text);
internal sealed record DiscoveryDiagnosticText(string Path, string Text)
{
    public bool CurrentUiEligible => false;
}
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
    int GlobalDepth, int Visible, int TextElement, int ChildCount, int Stage,
    int BoundsEligible = -1, int TextReadCompleted = -1, int TextLength = -1,
    int RectXClass = -1, int RectYClass = -1, int WidthClass = -1, int HeightClass = -1);
internal sealed record DiscoveryResult(string Status, string Reason, DiscoveryText[] Observations,
    int NativeOperations, double ElapsedMilliseconds, int Nodes, int TotalRoots, int PeakRoots,
    bool TraversalBounded, DiscoveryRequest Request, int PanelIndex, string FocusPath)
{
    public bool PageIdentityVerified => false;
    public DiscoveryDiagnosticText[] DiagnosticTexts { get; init; } = Array.Empty<DiscoveryDiagnosticText>();
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
            var diagnosticTexts = new List<DiscoveryDiagnosticText>(7);
            var nodes = 0; var roots = 0; var peak = 0; var bounded = false;
            var success = false; var reason = "diagnostic_failure";
            var focusDepth = -1; var focusEdge = -1; var focusIndex = -1;
            var focusCount = -1; var focusStage = 0;
            // One fixed candidate only. Value-type slots allocated before any native invocation.
            var alignment = policy.Approval.SelectionProfile == "tactics_alignment_candidate";
            var siblingDepth = policy.Approval.SelectionProfile switch {
                "tactics_sibling12" => 12, "tactics_sibling7" => 7, "tactics_sibling4" => 4, _ => -1 };
            var census = policy.Approval.SelectionProfile == "tactics_root_census";
            var frontier = policy.Approval.SelectionProfile == "tactics_frontier35";
            var ineligible = policy.Approval.SelectionProfile == "tactics_ineligible_text7";
            var eligibility = ineligible || policy.Approval.SelectionProfile == "tactics_leaf_eligibility7";
            var remainingGate = policy.Approval.SelectionProfile switch {
                "tactics_remaining45_1" => (Depth:26, Count:2),
                "tactics_remaining46_1" or "tactics_remaining46_2" => (Depth:27, Count:3),
                "tactics_remaining56_1" or "tactics_remaining56_2" => (Depth:30, Count:3),
                _ => (Depth:-1, Count:-1) };
            var diagnostic = siblingDepth >= 0 || census || frontier || eligibility || remainingGate.Depth >= 0;
            var sibling = siblingDepth >= 0;
            var topology = diagnostic ? new DiscoveryTopologyNode[MaximumNodes] : null;
            var topologyCount = 0;
            var focusTrace = alignment || diagnostic ? new DiscoveryFocusEdge[35] : null;
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
                    if (texts.Count + diagnosticTexts.Count >= MaximumTexts || nodes >= MaximumNodes ||
                        budget.Operations >= WorkOperations || elapsed() >= WorkMilliseconds)
                    { bounded = true; return true; }
                    return false;
                }
                void Visit(BatchObject node, int depth, string path, int parentRecord = -1, int childEdge = -1, int[][]? eligibleTargets = null)
                {
                    if (StopWork()) return;
                    Charge();
                    var record = topology is null ? -1 : topologyCount++;
                    var visible = -1; var textElement = -1; var childCount = -1; var stage = 1;
                    var boundsEligible = -1; var textRead = -1; var textLength = -1;
                    var rectX = -1; var rectY = -1; var rectWidth = -1; var rectHeight = -1;
                    void TraceNode() {
                        if (topology is not null) topology[record] = new(parentRecord, childEdge,
                            depth, visible, textElement, childCount, stage, boundsEligible, textRead, textLength, rectX, rectY, rectWidth, rectHeight);
                    }
                    TraceNode();
                    visible = backend.Visible(node, budget) ? 1 : 0; stage = 2; TraceNode();
                    if (visible == 0) { if (diagnostic) bounded = true; return; }
                    var inspectLeaf = eligibleTargets is null || eligibleTargets.Any(suffix => suffix.Length == 0);
                    if (inspectLeaf) { textElement = backend.IsTextElement(node, budget) ? 1 : 0; stage = 3; TraceNode(); }
                    if (textElement == 1 || eligibleTargets is not null && inspectLeaf)
                    {
                        var bounds = backend.Bounds(node, budget);
                        boundsEligible = bounds.PositiveFinite ? 1 : 0;
                        rectX = ClassifyRect(bounds.X); rectY = ClassifyRect(bounds.Y);
                        rectWidth = ClassifyRect(bounds.Width); rectHeight = ClassifyRect(bounds.Height); TraceNode();
                    }
                    if (textElement == 1 && (boundsEligible == 1 || ineligible))
                    {
                        // Complete text only. No silently truncated name/anchor candidates.
                        textRead = 0; TraceNode();
                        var text = backend.ReadAnchorText(node, budget);
                        textRead = 1; textLength = text.Length; TraceNode();
                        if (ineligible) {
                            if (diagnosticTexts.Count >= 7) throw new UiSmokeStopped("diagnostic_text_limit");
                            diagnosticTexts.Add(new(path,text));
                        }
                        else if (!string.IsNullOrWhiteSpace(text)) texts.Add(new(path, text));
                    }
                    if (StopWork()) return;
                    var count = backend.ChildCount(node, budget);
                    childCount = count; stage = 4; TraceNode();
                    var maximumDepth = diagnostic ? TargetedDiscoveryCollector.MaximumDepth : MaximumDepth;
                    if (eligibleTargets is null && (count > 8 || (depth >= maximumDepth && count > 0))) bounded = true;
                    if (depth >= maximumDepth) return;
                    // Single-pass child0-first DFS. Global depth32 (fixed probe48);
                    // scoped root stack plus transient boxes remains below live64.
                    // no sibling prefetch, pointer cursor or handle survives this request.
                    var plannedIndices = eligibleTargets?.Where(suffix=>suffix.Length>0)
                        .Select(suffix=>suffix[0]).Distinct().OrderBy(index=>index).ToArray();
                    var indexCount = plannedIndices?.Length ?? Math.Min(count,8);
                    for (var ordinal=0; ordinal<indexCount; ordinal++)
                    {
                        var index = plannedIndices is null ? ordinal : plannedIndices[ordinal];
                        if (StopWork()) break;
                        if(index>=count) throw new UiSmokeStopped("eligibility_child_unavailable");
                        using var child = backend.Child(node, index, budget);
                        if (child is null) throw new UiSmokeStopped("discovery_child_unavailable");
                        Visit(child, depth + 1, Join(path, index), record, index, eligibleTargets is null ? null :
                            eligibleTargets.Where(suffix=>suffix.Length>0&&suffix[0]==index).Select(suffix=>suffix.Skip(1).ToArray()).ToArray());
                    }
                }
                void Census(BatchObject node, int depth)
                {
                    if (StopWork()) return;
                    Charge();
                    var rootRecord = topologyCount++;
                    topology![rootRecord] = new(-1,-1,depth,-1,-1,-1,1);
                    var visible = backend.Visible(node,budget) ? 1 : 0;
                    topology[rootRecord] = new(-1,-1,depth,visible,-1,-1,2);
                    if (visible == 0) { bounded = true; return; }
                    var count = backend.ChildCount(node,budget);
                    topology[rootRecord] = new(-1,-1,depth,1,-1,count,4);
                    if (count != 20) throw new UiSmokeStopped("census_root_shape_changed");
                    // Fixed census only: no recursive Visit, text getter, name or sibling prefetch.
                    for (var index=0; index<20; index++)
                    {
                        if (StopWork()) return;
                        using var child = backend.Child(node,index,budget);
                        if (child is null) throw new UiSmokeStopped("discovery_child_unavailable");
                        Charge();
                        var record=topologyCount++; var bounds=-1; var type=-1; var childCount=-1;
                        topology[record]=new(rootRecord,index,depth+1,-1,-1,-1,1);
                        var childVisible=backend.Visible(child,budget)?1:0;
                        topology[record]=new(rootRecord,index,depth+1,childVisible,-1,-1,2);
                        if(childVisible==0){bounded=true;continue;}
                        var rectangle=backend.Bounds(child,budget);
                        bounds=rectangle.PositiveFinite?1:0;
                        var x=ClassifyRect(rectangle.X);var y=ClassifyRect(rectangle.Y);
                        var width=ClassifyRect(rectangle.Width);var height=ClassifyRect(rectangle.Height);
                        topology[record]=new(rootRecord,index,depth+1,1,-1,-1,2,bounds,-1,-1,x,y,width,height);
                        type=backend.IsTextElement(child,budget)?1:0;
                        topology[record]=new(rootRecord,index,depth+1,1,type,-1,3,bounds,-1,-1,x,y,width,height);
                        childCount=backend.ChildCount(child,budget);
                        topology[record]=new(rootRecord,index,depth+1,1,type,childCount,4,bounds,-1,-1,x,y,width,height);
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
                        if (frontier && focusDepth == 21 && focusCount != 2)
                            throw new UiSmokeStopped("frontier_parent_shape_changed");
                        if (remainingGate.Depth == focusDepth && focusCount != remainingGate.Count)
                            throw new UiSmokeStopped("remaining_parent_shape_changed");
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
                    if (eligibility) Visit(current,edges.Length,policy.Approval.FocusPath,
                        eligibleTargets: TargetedDiscoveryCollector.CreateTargets(policy.Approval.SelectionProfile));
                    else if (census) Census(current,edges.Length);
                    else if (targetedRow && !diagnostic)
                        VisitTargets(current, edges.Length, policy.Approval.FocusPath, TargetedDiscoveryCollector.CreateTargets(policy.Approval.SelectionProfile));
                    else Visit(current, edges.Length, policy.Approval.FocusPath);
                }
                finally { current?.Dispose(); }
                success = true;
                reason = targetedRow && !diagnostic ? (policy.Approval.SelectionProfile == "single" ?
                    "approved_row_targets_complete" : "approved_group_targets_complete") :
                    bounded ? "bounded_raw_diagnostics" : ineligible ? "approved_ineligible_diagnostic_complete" : eligibility ? "approved_leaf_eligibility_complete" : "approved_prefix_exhausted";
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
            var diagnosticObservations = diagnosticTexts.ToArray();
            var traceSnapshot = focusTrace is null ? null : focusTrace.Take(focusTraceCount).ToArray();
            var topologySnapshot = topology is null ? null : topology.Take(topologyCount).ToArray();
            var spent = elapsed();
            success = policy.Finish(grant, budget.Operations, spent, success, now());
            accounted = true;
            if (!success)
            {
                observations = Array.Empty<DiscoveryText>();
                diagnosticObservations = Array.Empty<DiscoveryDiagnosticText>();
                if (reason is "approved_ineligible_diagnostic_complete" or "approved_leaf_eligibility_complete" or "bounded_raw_diagnostics" or "approved_prefix_exhausted" or "approved_row_targets_complete" or "approved_group_targets_complete") reason = "discovery_accounting_rejected";
            }
            return new(success ? "raw_diagnostics" : "terminal_failure", reason, observations,
                budget.Operations, spent, nodes, roots, peak, bounded, request,
                policy.Approval.PanelIndex, policy.Approval.FocusPath) {
                    SelectionProfile = policy.Approval.SelectionProfile,
                    DiagnosticTexts = diagnosticObservations,
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
    private static int ClassifyRect(float value) => float.IsNaN(value) ? 3 :
        float.IsPositiveInfinity(value) ? 4 : float.IsNegativeInfinity(value) ? 5 :
        value == 0 ? 0 : value > 0 ? 1 : 2;
    private static string Join(string path, int index) => path.Length == 0 ? index.ToString(CultureInfo.InvariantCulture) :
        path + "/" + index.ToString(CultureInfo.InvariantCulture);
}
