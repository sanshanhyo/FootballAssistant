using System.Diagnostics;
using System.Globalization;

namespace FootballAssistant.GameBridge;

// Deliberately NOT BatchText/BatchChunkResult: these are unverified UI observations,
// not player facts, anchors or an atomic page snapshot. No conversion/merge API.
internal sealed record DiscoveryText(string Path, string Text);
internal sealed record DiscoveryResult(string Status, string Reason, DiscoveryText[] Observations,
    int NativeOperations, double ElapsedMilliseconds, int Nodes, int TotalRoots, int PeakRoots,
    bool TraversalBounded, DiscoveryRequest Request, int PanelIndex, string FocusPath)
{
    public bool PageIdentityVerified => false;
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
            BatchNativeBackend? backend = null;
            try
            {
                budget.Check();
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
                void Visit(BatchObject node, int depth, string path)
                {
                    if (StopWork()) return;
                    Charge();
                    if (!backend.Visible(node, budget)) return;
                    if (backend.IsTextElement(node, budget) && backend.Bounds(node, budget).PositiveFinite)
                    {
                        // Complete text only. No silently truncated name/anchor candidates.
                        var text = backend.ReadAnchorText(node, budget);
                        if (!string.IsNullOrWhiteSpace(text)) texts.Add(new(path, text));
                    }
                    if (StopWork()) return;
                    var count = backend.ChildCount(node, budget);
                    if (count > 8 || (depth >= MaximumDepth && count > 0)) bounded = true;
                    if (depth >= MaximumDepth) return;
                    // Single-pass child0-first DFS. Root stack <=33 plus transient boxes;
                    // no sibling prefetch, pointer cursor or handle survives this request.
                    for (var index = 0; index < Math.Min(count, 8); index++)
                    {
                        if (StopWork()) break;
                        using var child = backend.Child(node, index, budget);
                        if (child is null) throw new UiSmokeStopped("discovery_child_unavailable");
                        Visit(child, depth + 1, Join(path, index));
                    }
                }
                BatchObject? current = backend.OpenPanel(policy.Approval.PanelIndex, budget);
                if (current is null) throw new UiSmokeStopped("discovery_panel_unavailable");
                try
                {
                    var edges = policy.Approval.FocusPath.Length == 0 ? Array.Empty<int>() :
                        policy.Approval.FocusPath.Split('/').Select(x => int.Parse(x, CultureInfo.InvariantCulture)).ToArray();
                    foreach (var index in edges)
                    {
                        Charge();
                        if (!backend.Visible(current, budget)) throw new UiSmokeStopped("discovery_ancestor_hidden");
                        if (index >= backend.ChildCount(current, budget)) throw new UiSmokeStopped("discovery_focus_unavailable");
                        var child = backend.Child(current, index, budget);
                        if (child is null) throw new UiSmokeStopped("discovery_focus_unavailable");
                        current.Dispose(); current = child;
                    }
                    Visit(current, edges.Length, policy.Approval.FocusPath);
                }
                finally { current?.Dispose(); }
                success = true;
                reason = bounded ? "bounded_raw_diagnostics" : "approved_prefix_exhausted";
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
            var spent = elapsed();
            success = policy.Finish(grant, budget.Operations, spent, success, now());
            accounted = true;
            if (!success)
            {
                observations = Array.Empty<DiscoveryText>();
                if (reason is "bounded_raw_diagnostics" or "approved_prefix_exhausted") reason = "discovery_accounting_rejected";
            }
            return new(success ? "raw_diagnostics" : "terminal_failure", reason, observations,
                budget.Operations, spent, nodes, roots, peak, bounded, request,
                policy.Approval.PanelIndex, policy.Approval.FocusPath);
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
