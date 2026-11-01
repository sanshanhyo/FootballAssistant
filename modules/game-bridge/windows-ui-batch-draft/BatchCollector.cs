using System.Diagnostics;

namespace FootballAssistant.GameBridge;

internal sealed record BatchText(string Path, string Text);
internal sealed record BatchSource(Guid BatchId, Guid PageEpoch, Guid Nonce, int Sequence,
    int Pid, string Session, string BridgeHash, string GameHash, string ApprovalSha256,
    int PanelIndex, string SubtreePath, DateTimeOffset StartedAt, DateTimeOffset EndedAt,
    bool PageIdentityVerified = false);
internal sealed record BatchChunkResult(BatchCompletion Status, string Reason, BatchText[] Texts,
    string? NextCursor, int NativeOperations, double ElapsedMilliseconds, int Nodes,
    int TotalRoots, int PeakRoots, bool AnchorsValidated, bool ChunkTraversalBounded, BatchSource Source);

// No scheduling, host registration or implicit fallback. All output remains provisional
// until post-anchor checks, mandatory cleanup and policy accounting have completed.
internal static class BatchCollector
{
    internal const int MaximumNodes = 128, MaximumDepth = 48, MaximumTexts = 8;
    private const int TailOperations = 768, TailNodes = 34;
    private const double TailMilliseconds = 350;

    internal static BatchChunkResult? Run(BatchPolicy policy, BatchRequest request,
        Func<BatchNativeBackend> createBackend, Func<WindowsThreadIdentity> freshIdentity,
        Func<DateTimeOffset> now, CancellationToken cancellation = default, Func<double>? elapsedForTest = null)
    {
        var grant = policy.TryBegin(request, freshIdentity(), now());
        if (grant is null) return null;
        var accountingStarted = Stopwatch.GetTimestamp();
        var accounted = false;
        UiSmokeBudget? accountingBudget = null;
        Func<double>? accountingElapsed = null;
        try
        {
            var watch = Stopwatch.StartNew();
            var startedAt = now();
            Func<double> elapsed = elapsedForTest ?? (() => watch.Elapsed.TotalMilliseconds);
            var budget = new UiSmokeBudget(elapsed, () =>
            {
                cancellation.ThrowIfCancellationRequested();
                if (!policy.CheckActive(grant, freshIdentity(), now(), cancellation))
                    throw new UiSmokeStopped("batch_grant_or_window_changed");
            }, grant.MaximumMilliseconds, grant.MaximumOperations);
            accountingBudget = budget; accountingElapsed = elapsed;
            var items = new List<BatchText>(MaximumTexts);
            var nodes = 0; var roots = 0; var peakRoots = 0;
            var validated = false; var complete = false; var bounded = false; var processed = 0; string? next = null;
            var reason = "batch_failure";
            BatchNativeBackend? backend = null;
            try
            {
                budget.Check();
                var approval = policy.Approval;
                var subtree = Parse(approval.SubtreePath);
                var pending = DecodeCursor(grant.Request.Cursor, subtree.Length);
                backend = createBackend();
                if (backend.VerifiedModuleHash != approval.Context.GameHash) throw new UiSmokeStopped("batch_module_mismatch");
                backend.Prepare(budget);
                void ChargeNode()
                {
                    budget.Check();
                    if (nodes >= MaximumNodes) throw new UiSmokeStopped("batch_node_budget");
                    nodes++;
                }
                // Every returned token is owned by the caller. Ancestors are released only
                // after the next object has been rooted by the adapter.
                BatchObject ResolvePanelPath(int[] path)
                {
                    BatchObject? current = backend.OpenPanel(approval.PanelIndex, budget);
                    if (current is null) throw new UiSmokeStopped("batch_panel_unavailable");
                    try
                    {
                        foreach (var index in path)
                        {
                            ChargeNode();
                            if (!backend.Visible(current, budget)) throw new UiSmokeStopped("batch_ancestor_hidden");
                            var count = backend.ChildCount(current, budget);
                            if (count < 0) throw new InvalidOperationException("Negative child count.");
                            if (index >= count) throw new UiSmokeStopped("batch_child_unavailable");
                            var child = backend.Child(current, index, budget);
                            if (child is null) throw new UiSmokeStopped("batch_child_unavailable");
                            current.Dispose(); current = child;
                        }
                        var result = current; current = null; return result;
                    }
                    finally { current?.Dispose(); }
                }
                string ReadAnchor(BatchAnchor anchor)
                {
                    using var value = ResolvePanelPath(Parse(anchor.Path));
                    ChargeNode();
                    if (!backend.Visible(value, budget) || !backend.IsTextElement(value, budget) ||
                        !backend.Bounds(value, budget).PositiveFinite)
                        throw new UiSmokeStopped("batch_anchor_unavailable");
                    var text = backend.ReadAnchorText(value, budget);
                    if (string.IsNullOrWhiteSpace(text) || BatchPolicy.Digest(text) != anchor.TextSha256)
                        throw new UiSmokeStopped("batch_anchor_changed");
                    return text;
                }
                ReadAnchor(approval.Anchor1); ReadAnchor(approval.Anchor2);
                using (var subtreeRoot = ResolvePanelPath(subtree))
                {
                    while (pending.Count > 0)
                    {
                        // This only stops work early; final validation remains subject to
                        // the unchanged overall request guard/deadline/reservation checks.
                        if (items.Count >= MaximumTexts ||
                            budget.Operations >= grant.MaximumOperations - TailOperations ||
                            elapsed() >= grant.MaximumMilliseconds - TailMilliseconds ||
                            nodes + Parse(pending[^1]).Length + 1 + TailNodes > MaximumNodes)
                        { reason = "chunk_work_limit"; break; }
                        var relative = pending[^1];
                        var path = Parse(relative);
                        BatchObject current = subtreeRoot; var ownsCurrent = false;
                        try
                        {
                            foreach (var index in path)
                            {
                                ChargeNode();
                                if (!backend.Visible(current, budget)) throw new UiSmokeStopped("batch_cursor_ancestor_hidden");
                                var count = backend.ChildCount(current, budget);
                                if (count < 0) throw new InvalidOperationException("Negative child count.");
                                if (index >= count) throw new UiSmokeStopped("batch_cursor_changed");
                                var child = backend.Child(current, index, budget);
                                if (child is null) throw new UiSmokeStopped("batch_cursor_changed");
                                if (ownsCurrent) current.Dispose();
                                current = child; ownsCurrent = true;
                            }
                            ChargeNode();
                            var depth = subtree.Length + path.Length;
                            var visible = backend.Visible(current, budget);
                            if (visible)
                            {
                                if (backend.IsTextElement(current, budget) && backend.Bounds(current, budget).PositiveFinite)
                                {
                                    var text = backend.ReadAnchorText(current, budget); // Same complete<=128 text contract; never project truncated fields.
                                    if (text.Length > 128) throw new InvalidOperationException("Text exceeded cap.");
                                    if (!string.IsNullOrWhiteSpace(text))
                                        items.Add(new(Join(approval.SubtreePath, relative), text));
                                }
                                var count = backend.ChildCount(current, budget);
                                if (count < 0) throw new InvalidOperationException("Negative child count.");
                                pending.RemoveAt(pending.Count - 1);
                                bounded |= count > 8 || (depth >= MaximumDepth && count > 0);
                                if (depth < MaximumDepth)
                                    for (var index = Math.Min(count, 8) - 1; index >= 0; index--)
                                        pending.Add(Join(relative, index.ToString(System.Globalization.CultureInfo.InvariantCulture)));
                            }
                            else pending.RemoveAt(pending.Count - 1);
                            processed++;
                        }
                        finally { if (ownsCurrent) current.Dispose(); }
                    }
                }
                if (processed == 0) throw new UiSmokeStopped("batch_no_work_allowance");
                complete = pending.Count == 0;
                next = complete ? null : EncodeCursor(pending);
                ReadAnchor(approval.Anchor1); ReadAnchor(approval.Anchor2);
                validated = true;
                if (complete) reason = "approved_prefix_complete"; // Never claims the whole UI/subtree was exhausted.
            }
            catch (Exception error)
            {
                reason = error is UiSmokeStopped stopped ? stopped.Message :
                    error is OperationCanceledException ? "batch_cancelled" : "batch_backend_failure";
            }
            finally
            {
                if (backend is not null)
                {
                    roots = backend.TotalAllocated; peakRoots = backend.PeakLiveRoots;
                    try { backend.Dispose(); if (backend.CleanupFailures > 0) { validated = false; reason = "batch_cleanup_failure"; } }
                    catch { validated = false; reason = "batch_cleanup_failure"; }
                }
            }
            try { budget.Check(); } // Revalidate ownership/cancellation after cleanup before releasing output.
            catch { validated = false; reason = "batch_final_guard_failed"; }
            var source = new BatchSource(grant.Request.BatchId, grant.Request.PageEpoch, grant.Request.Nonce,
                grant.Request.Sequence, grant.Request.Pid, grant.Request.Session, grant.Request.BridgeHash,
                grant.Request.GameHash, grant.Request.ApprovalSha256, grant.Request.PanelIndex,
                grant.Request.SubtreePath, startedAt, now());
            var output = items.ToArray();
            var nextDigest = next is null ? null : BatchPolicy.ComputeCursorHash(next);
            var totalElapsed = elapsed(); // Includes cleanup, source/cursor checks and output snapshot allocation.
            var status = policy.Finish(grant, budget.Operations, totalElapsed, validated, complete,
                nextDigest, now());
            accounted = true;
            if (status is not (BatchCompletion.Continue or BatchCompletion.Complete))
            { output = Array.Empty<BatchText>(); next = null; validated = false; if (reason is "approved_prefix_complete" or "chunk_work_limit") reason = "batch_accounting_rejected"; }
            return new(status, reason, output, next, budget.Operations, totalElapsed, nodes, roots, peakRoots, validated, bounded, source);
        }
        finally
        {
            // Finalization (clock/source/snapshot/hash) can also throw. A consumed grant
            // must still become terminal and charge work; no provisional facts escape.
            if (!accounted)
            {
                policy.Stop();
                double spent;
                try { spent = accountingElapsed?.Invoke() ?? Stopwatch.GetElapsedTime(accountingStarted).TotalMilliseconds; }
                catch { spent = Stopwatch.GetElapsedTime(accountingStarted).TotalMilliseconds; }
                DateTimeOffset finished;
                try { finished = now(); } catch { finished = DateTimeOffset.UtcNow; }
                policy.Finish(grant, accountingBudget?.Operations ?? 0, spent, false, false, null, finished);
            }
        }
    }

    private static int[] Parse(string path) => path.Length == 0 ? Array.Empty<int>() : path.Split('/').Select(int.Parse).ToArray();
    private static string Join(string prefix, string tail) => prefix.Length == 0 ? tail : tail.Length == 0 ? prefix : prefix + "/" + tail;
    private static List<string> DecodeCursor(string cursor, int subtreeDepth)
    {
        if (cursor.Length == 0) return new() { "" };
        var paths = cursor.Split(';');
        if (cursor.Length > 16384 || paths.Length > 337 || paths.Distinct(StringComparer.Ordinal).Count() != paths.Length)
            throw new UiSmokeStopped("batch_cursor_invalid");
        foreach (var path in paths)
            if (path.Length == 0 || !BatchPolicy.ValidPath(path) || Parse(path).Length + subtreeDepth > MaximumDepth ||
                Parse(path).Any(index => index > 7))
                throw new UiSmokeStopped("batch_cursor_invalid");
        return paths.ToList();
    }
    private static string EncodeCursor(List<string> paths)
    {
        var cursor = string.Join(';', paths);
        if (paths.Count > 337 || cursor.Length > 16384) throw new UiSmokeStopped("batch_cursor_budget");
        return cursor;
    }
}
