using FootballAssistant.GameBridge;

// Owned synthetic buffers and delegate exports only; not measured Windows/game evidence.
internal static class TargetedDiscoveryCollectorTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new Exception("Targeted discovery: " + message); }
    internal static void Run()
    {
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context = new SmokeContext(12, "targeted-fixture", new string('a', 64), new string('b', 64), "FixtureWindow", 34);
        var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false)
        { WindowScanStatus = "complete", WindowScanCount = 1, WindowCandidates = new[]
            { new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureWindow", true, 0, true, true, 10, 10, 0) } };
        DiscoveryPolicy Policy() => new(new(context, Guid.NewGuid(), 0, BatchTreeFixture.GoalkeeperCategoryPath,
            at, at.AddSeconds(120), true));
        DiscoveryRequest Request(DiscoveryPolicy policy) => new(3, policy.Approval.Nonce, policy.ApprovalSha256);
        DiscoveryResult Capture(DiscoveryPolicy policy, BatchTreeFixture fixture,
            Func<WindowsThreadIdentity>? fresh = null, CancellationToken cancellation = default, Func<double>? elapsed = null) =>
            TargetedDiscoveryCollector.Run(policy, Request(policy), () => new BatchNativeBackend(context.GameHash, fixture.Bind),
                fresh ?? (() => identity), () => at, cancellation, elapsed ?? (() => 0))!;
        void Clean(BatchTreeFixture fixture, DiscoveryPolicy policy, DiscoveryResult result)
        {
            Check(policy.Terminal && policy.Consumed && fixture.LiveRoots == 0 && fixture.RootCreates == fixture.RootFrees,
                "request terminal and every owned synthetic handle released once");
            Check(result.NativeOperations == policy.TotalOperations && result.ElapsedMilliseconds == policy.TotalMilliseconds &&
                result.NativeOperations <= 2048 && result.TotalRoots <= 512 && result.PeakRoots <= 64 && result.Nodes <= 96,
                "same fixed operation/node/live/total root bounds and cleanup accounting");
            Check(!result.PageIdentityVerified && result.Observations.Length <= 3,
                "three raw target observations at most; no page/business identity claim");
        }
        var paths = new[] { BatchTreeFixture.GoalkeeperTitlePath, BatchTreeFixture.GoalkeeperLabelPath,
            BatchTreeFixture.GoalkeeperValuePath };
        Check(BatchTreeFixture.GoalkeeperCategoryPath.Split('/').Length == 25 &&
            paths.Select(p => p.Split('/').Length).SequenceEqual(new[] { 26, 39, 44 }), "independent literal fixture path depths");
        Check(TargetedDiscoveryCollector.IsAllowedTargetPath(BatchTreeFixture.GoalkeeperCategoryPath + string.Concat(Enumerable.Repeat("/0", 23))) &&
            !TargetedDiscoveryCollector.IsAllowedTargetPath(BatchTreeFixture.GoalkeeperCategoryPath + string.Concat(Enumerable.Repeat("/0", 24))),
            "pure global-depth validator accepts48/rejects49; no arbitrary native plan hook");
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            var policy = Policy(); var checks = 0;
            var result = Capture(policy, fixture, () => { checks++; return identity; });
            Check(result.Status == "raw_diagnostics" && result.Reason == "approved_row_targets_complete" && !result.TraversalBounded &&
                result.Observations.Select(o => o.Path).SequenceEqual(paths) &&
                result.Observations.Select(o => o.Text).SequenceEqual(new[] { "TEST-GROUP", "TEST-ATTRIBUTE", "17" }),
                "exact three selected leaves, no invented game label/value or sibling fallback");
            // Prepare27 + OpenPanel21 + visible345 + childCount323 + child193 + type6 + bounds22 + text24.
            Check(result.NativeOperations == 961 && result.Nodes == 49 && result.TotalRoots == 153 && result.PeakRoots == 21 &&
                fixture.Invocations.Count == 153 && checks == 1013,
                "exact fresh-check/operation/native-return/root cost including25 ancestors and full cleanup");
            Check(fixture.ObjectClassReads == 257 && fixture.UnboxReads == 99 && fixture.MethodLookups == 14 &&
                fixture.AssignableChecks == 3 && fixture.StringLengthReads == 3 && fixture.StringCharReads == 3 &&
                fixture.RootCreates == 153 && fixture.RootTargets == 153 && fixture.RootFrees == 153,
                "exact native export counts: no all-node text checks, duplicate getters or retained roots");
            Check(fixture.PanelOpens == 1 && fixture.PanelIndices.SequenceEqual(new[] { 0 }) &&
                fixture.TextReads.SequenceEqual(paths.Select(fixture.NodeAt)), "one panel, exactly selected getters");
            var expectedEdges = new List<(nint Parent, int Index)>();
            void Visit(string prefix)
            {
                var edges = paths.Where(p => prefix.Length == 0 || p.StartsWith(prefix + "/", StringComparison.Ordinal))
                    .Select(p => p[(prefix.Length == 0 ? 0 : prefix.Length + 1)..].Split('/')[0])
                    .Select(int.Parse).Distinct().OrderBy(x => x).ToArray();
                foreach (var edge in edges)
                {
                    expectedEdges.Add((fixture.NodeAt(prefix), edge));
                    var next = prefix.Length == 0 ? edge.ToString() : prefix + "/" + edge;
                    if (!paths.Contains(next)) Visit(next);
                }
            }
            Visit("");
            Check(expectedEdges.Count == 48 && fixture.ChildEdges.SequenceEqual(expectedEdges),
                "every obtained edge is in target trie exactly once; no skipped sibling or second-row reads");
            Check(!fixture.ChildEdges.Contains((fixture.NodeAt(BatchTreeFixture.GoalkeeperCategoryPath + "/2/0/0/0"), 1)),
                "actual available row1 is never fetched");
            Clean(fixture, policy, result);
            var before = fixture.RootCreates;
            Check(TargetedDiscoveryCollector.Run(policy, Request(policy), () => throw new Exception("Replay must not bind exports"),
                () => identity, () => at, elapsedForTest: () => 0) is null && fixture.RootCreates == before,
                "same approval cannot read again or resurrect roots");
            Console.WriteLine("Targeted synthetic row0: operations=961 nodes=49 roots=153 peak=21 guards=1013; no live latency claim.");
        }
        foreach (var failure in new[] { "ancestor_hidden", "target_hidden", "missing_target", "nontext_target", "getter", "box_type", "long_text", "utf16", "cleanup" })
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            switch (failure)
            {
                case "ancestor_hidden": fixture.HiddenNodes.Add(fixture.NodeAt("0/6")); break;
                case "target_hidden": fixture.HiddenNodes.Add(fixture.NodeAt(BatchTreeFixture.GoalkeeperLabelPath)); break;
                case "missing_target": fixture.Children[fixture.NodeAt(BatchTreeFixture.GoalkeeperValuePath[..BatchTreeFixture.GoalkeeperValuePath.LastIndexOf('/')])].Clear(); break;
                case "nontext_target": fixture.SetNodeText(BatchTreeFixture.GoalkeeperLabelPath, null); break;
                case "getter": fixture.ThrowingTextNodes.Add(fixture.NodeAt(BatchTreeFixture.GoalkeeperValuePath)); break;
                case "box_type": fixture.WrongBoxType = true; break;
                case "long_text": fixture.SetNodeText(BatchTreeFixture.GoalkeeperLabelPath, new string('x', 129)); break;
                case "utf16": fixture.SetNodeText(BatchTreeFixture.GoalkeeperLabelPath, "\ud800"); break;
                case "cleanup": fixture.FailFirstFree = true; break;
            }
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0,
                failure + " invalidates whole requested target set, never substitutes sibling/partial facts");
            if (failure == "getter") Check(fixture.TextReads.Count == 3, "late getter failure discards earlier title and label");
            if (failure == "cleanup") Check(result.Reason == "discovery_cleanup_failure", "uncertain cleanup is terminal");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            var policy = Policy(); var result = Capture(policy, fixture,
                () => fixture.RootCreates > 0 && fixture.LiveRoots == 0 ? identity with { WindowScanStatus = "incomplete" } : identity);
            Check(fixture.TextReads.Count == 3 && result.Status == "terminal_failure" && result.Observations.Length == 0,
                "final fresh guard after all three reads and root cleanup discards all outputs");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            var policy = Policy(); var result = Capture(policy, fixture,
                elapsed: () => fixture.RootCreates > 0 && fixture.LiveRoots == 0 ? 1001 : 0);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0 && result.ElapsedMilliseconds >= 1001,
                "post-cleanup elapsed overrun is charged, never returned as successful partial data");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            var policy = Policy(); var result = Capture(policy, fixture,
                elapsed: () => fixture.TextReads.Count > 0 ? 801 : 0);
            Check(fixture.TextReads.Count == 1 && result.Status == "terminal_failure" &&
                result.Reason == "target_work_limit" && result.Observations.Length == 0 &&
                result.ElapsedMilliseconds == 801 && result.NativeOperations < 961,
                "cooperative800ms stop after first target discards it; never leaks an incomplete target set");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            using var cancellation = new CancellationTokenSource(); var policy = Policy();
            var result = Capture(policy, fixture, () => { if (fixture.TextReads.Count > 0) cancellation.Cancel(); return identity; }, cancellation.Token);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0, "cancellation after native text read clears whole output");
            Clean(fixture, policy, result);
        }
        // A separate approval reconstructs its own tree/backend; fixture pointers may numerically
        // repeat but no native handle/cache/object from the prior request is reused.
        for (var i = 0; i < 2; i++)
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildGoalkeeperRow0();
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(fixture.PanelOpens == 1 && fixture.RootCreates == 153 && result.Observations.Length == 3,
                "each new approved request creates fresh backend and handles");
            Clean(fixture, policy, result);
        }
    }
}
