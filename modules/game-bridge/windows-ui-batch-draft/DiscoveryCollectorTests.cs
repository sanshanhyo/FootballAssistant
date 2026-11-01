using FootballAssistant.GameBridge;

// Synthetic topology and owned fixture memory only. No Windows module, live UI or latency evidence.
internal static class DiscoveryCollectorTests
{
    private static void Check(bool value, string label) { if (!value) throw new Exception("Discovery collector: " + label); }
    internal static void Run()
    {
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context = new SmokeContext(12, "discovery-fixture", new string('a', 64), new string('b', 64), "FixtureWindow", 34);
        var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false)
        { WindowScanStatus = "complete", WindowScanCount = 1, WindowCandidates = new[]
            { new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureWindow", true, 0, true, true, 10, 10, 0) } };
        DiscoveryPolicy Policy(string focus = "0/6") => new(new(context, Guid.NewGuid(), 0, focus, at, at.AddSeconds(120), true));
        DiscoveryRequest Request(DiscoveryPolicy policy) => new(3, policy.Approval.Nonce, policy.ApprovalSha256);
        DiscoveryResult Capture(DiscoveryPolicy policy, BatchTreeFixture fixture,
            Func<WindowsThreadIdentity>? fresh = null, CancellationToken cancellation = default, Func<double>? elapsed = null) =>
            DiscoveryCollector.Run(policy, Request(policy), () => new BatchNativeBackend(context.GameHash, fixture.Bind),
                fresh ?? (() => identity), () => at, cancellation, elapsed ?? (() => 0))!;
        void Clean(BatchTreeFixture fixture, DiscoveryPolicy policy, DiscoveryResult result)
        {
            Check(policy.Terminal && fixture.LiveRoots == 0 && fixture.RootCreates == fixture.RootFrees,
                "one-shot finishes terminal with no retained fixture roots");
            Check(result.NativeOperations == policy.TotalOperations && result.ElapsedMilliseconds == policy.TotalMilliseconds &&
                result.NativeOperations <= 2048 && result.TotalRoots <= 512 && result.PeakRoots <= 64 && result.Nodes <= 96,
                "actual accounted results obey fixed operation/root/node ceilings");
            Check(!result.PageIdentityVerified && result.Observations.Length <= 8 &&
                result.Observations.All(t => t.Text.Length <= 128) && result.Observations.Sum(t => t.Text.Length) <= 1024,
                "bounded raw diagnostics never claim page identity or business facts");
        }
        foreach (var depth in new[] { 21, 31 })
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(depth);
            var policy = Policy(); var freshChecks = 0;
            var result = Capture(policy, fixture, () => { freshChecks++; return identity; });
            Check(result.Status == "raw_diagnostics" && result.Reason == "approved_prefix_exhausted" &&
                !result.TraversalBounded && result.Observations.Length == 4 &&
                result.Observations.Select(t => t.Text).SequenceEqual(Enumerable.Range(0, 4).Select(i => "synthetic-field-" + i)) &&
                result.Observations.Select(t => t.Path).SequenceEqual(Enumerable.Range(0, 4).Select(i => fixture.BodyPath + "/" + i)),
                "approved actual0/6 subtree emits exactlyfour synthetic leaves in DFS order");
            Check(result.NativeOperations == (depth == 21 ? 626 : 826) &&
                result.TotalRoots == (depth == 21 ? 89 : 119) && result.PeakRoots == depth + 1 &&
                result.Nodes == depth + 5 && freshChecks == result.NativeOperations + result.Nodes + 3,
                "exact source-derived discovery costs include prepare, ancestors, every fresh guard and final guard");
            Check(fixture.PanelOpens == 1 && fixture.PanelIndices.SequenceEqual(new[] { 0 }) &&
                fixture.ChildIndices.Take(2).SequenceEqual(new[] { 0, 6 }), "one panel and exact focus edges, no sibling prefetch");
            Clean(fixture, policy, result);
            Console.WriteLine($"Discovery container depth{depth}: operations={result.NativeOperations}, nodes={result.Nodes}, roots={result.TotalRoots}, peak={result.PeakRoots}; fake native exports, injected zero elapsed.");
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(32);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "raw_diagnostics" && result.TraversalBounded && result.Observations.Length == 0 &&
                result.Nodes == 33 && !fixture.Invocations.Contains("get_text"),
                "globaldepth32 container is visited but its depth33 text children are not obtained/read");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2, 12);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "raw_diagnostics" && result.TraversalBounded && result.Observations.Length == 8 &&
                fixture.Invocations.Count(x => x == "get_text") == 8 &&
                fixture.ChildIndices.SequenceEqual(new[] { 0, 6 }.Concat(Enumerable.Range(0, 8))),
                "eight-text/first-eight width cap never fetches the ninth sibling");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2, 9);
            var container = fixture.Children[103][0]; var body = fixture.Children[container][6];
            foreach (var leaf in fixture.Children[body].Take(8)) fixture.HiddenNodes.Add(leaf);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "raw_diagnostics" && result.TraversalBounded && result.Observations.Length == 0 &&
                fixture.ChildIndices.SequenceEqual(new[] { 0, 6 }.Concat(Enumerable.Range(0, 8))) &&
                !fixture.Invocations.Contains("get_text"), "width cap is independent of text cap; visible ninth child remains unread");
            Clean(fixture, policy, result);
        }
        foreach (var hidden in new[] { true, false })
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var container = fixture.Children[103][0];
            if (hidden) fixture.HiddenNodes.Add(container); else fixture.Children[container].RemoveAt(6);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0 &&
                result.Reason == (hidden ? "discovery_ancestor_hidden" : "discovery_focus_unavailable") &&
                fixture.ChildIndices.SequenceEqual(new[] { 0 }) && !fixture.Invocations.Contains("get_text"),
                "hidden/out-of-range focus ancestor fails closed without alternate branch");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture { CycleBody = true }; fixture.BuildDiscovery(2, 0);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "raw_diagnostics" && result.TraversalBounded && result.Observations.Length == 0 &&
                result.Nodes == 33, "cyclic child relation remains bounded by globaldepth32");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2, 0);
            var body = fixture.Children[fixture.Children[103][0]][6];
            nint next = 50000;
            void Branch(nint parent, int depth)
            {
                for (var index = 0; index < 8; index++)
                {
                    var child = next++; fixture.Children[child] = new(); fixture.Children[parent].Add(child);
                    if (depth == 0) fixture.HiddenNodes.Add(child); else Branch(child, depth - 1);
                }
            }
            Branch(body, 2);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "raw_diagnostics" && result.TraversalBounded && result.Nodes == 96 &&
                result.NativeOperations < 1792 && result.Observations.Length == 0,
                "cheap hidden leaves exercise node96 cooperative cap before work-operation cap");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy(); var checks = 0;
            using var cancelled = new CancellationTokenSource();
            var result = Capture(policy, fixture, () => { if (++checks == 40) cancelled.Cancel(); return identity; }, cancelled.Token);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0 && policy.Consumed,
                "mid-request cancellation consumes one attempt and discards observations");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy();
            var result = Capture(policy, fixture, () => fixture.Invocations.Contains("get_text")
                ? identity with { WindowScanStatus = "incomplete" } : identity);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0 &&
                fixture.Invocations.Count(x => x == "get_text") == 1,
                "fresh ownership failure after provisional text clears all raw output");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy();
            var result = Capture(policy, fixture, elapsed: () => fixture.RootCreates > 0 && fixture.LiveRoots == 0 ? 1001 : 0);
            Check(result.Status == "terminal_failure" && result.Observations.Length == 0 && result.ElapsedMilliseconds == 1001 &&
                policy.TotalMilliseconds == 1001, "cleanup/final-check elapsed overrun is charged and output denied, never subtracted");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2, 0);
            var body = fixture.Children[fixture.Children[103][0]][6];
            nint next = 60000;
            void Dense(nint parent, int depth)
            {
                for (var index = 0; index < 8; index++)
                {
                    var child = next++; fixture.Children[child] = new(); fixture.Children[parent].Add(child);
                    if (depth > 0) Dense(child, depth - 1);
                }
            }
            Dense(body, 2);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "raw_diagnostics" && result.TraversalBounded && result.Nodes < 96 &&
                result.NativeOperations >= 1792 && result.NativeOperations < 2048 && result.Observations.Length == 0,
                "dense visible tree reaches1792 cooperative work boundary before96 nodes, not a hard budget failure");
            Clean(fixture, policy, result);
        }
        foreach (var finalElapsed in new[] { 801.0, 1001.0 })
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy();
            var result = Capture(policy, fixture, elapsed: () => fixture.Invocations.Contains("get_text") ? finalElapsed : 0);
            Check(finalElapsed == 801 ? result.Status == "raw_diagnostics" && result.TraversalBounded && result.Observations.Length == 1
                : result.Status == "terminal_failure" && result.Observations.Length == 0,
                "cooperative800ms stop can retain bounded raw diagnostics; hard1000ms overrun discards all");
            Check(policy.TotalMilliseconds == finalElapsed, "all elapsed time is charged without subtracting overhead");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture { FailFirstFree = true }; fixture.BuildDiscovery(2);
            var policy = Policy(); var result = Capture(policy, fixture);
            Check(result.Status == "terminal_failure" && result.Reason == "discovery_cleanup_failure" &&
                result.Observations.Length == 0, "uncertain cleanup failure denies output and terminates even if fake free removed handle");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy();
            var result = Capture(policy, fixture, () => fixture.RootCreates > 0 && fixture.LiveRoots == 0
                ? identity with { WindowScanStatus = "incomplete" } : identity);
            Check(result.Status == "terminal_failure" && result.Reason == "discovery_final_guard_failed" &&
                result.Observations.Length == 0, "final fresh ownership check after cleanup can deny provisional observations");
            Clean(fixture, policy, result);
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy(); var threw = false;
            DateTimeOffset FaultingClock()
            {
                if (fixture.Invocations.Contains("get_text") && fixture.LiveRoots == 0)
                    throw new InvalidOperationException("Synthetic final clock failure.");
                return at;
            }
            try
            {
                DiscoveryCollector.Run(policy, Request(policy), () => new BatchNativeBackend(context.GameHash, fixture.Bind),
                    () => identity, FaultingClock, elapsedForTest: () => 0);
            }
            catch (InvalidOperationException) { threw = true; }
            Check(threw && policy.Terminal && policy.TotalOperations > 0 && fixture.LiveRoots == 0 &&
                fixture.RootCreates == fixture.RootFrees, "post-consume clock exception cannot skip terminal accounting or cleanup");
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.BuildDiscovery(2);
            var policy = Policy(); var request = Request(policy); var factories = 0;
            BatchNativeBackend Factory() { factories++; return new(context.GameHash, fixture.Bind); }
            var result = DiscoveryCollector.Run(policy, request, Factory, () => identity, () => at, elapsedForTest: () => 0)!;
            Check(DiscoveryCollector.Run(policy, request, Factory, () => identity, () => at, elapsedForTest: () => 0) is null &&
                factories == 1 && fixture.LiveRoots == 0, "same approval never starts a second request or keeps native pointers alive");
            using var nextFixture = new BatchTreeFixture(); nextFixture.BuildDiscovery(2);
            var nextPolicy = Policy(); var nextResult = Capture(nextPolicy, nextFixture);
            Check(nextResult.Status == "raw_diagnostics" && nextResult.Request.Nonce != result.Request.Nonce &&
                nextFixture.PanelOpens == 1, "independent new approval rebuilds its own panel and fresh backend");
            Clean(fixture, policy, result); Clean(nextFixture, nextPolicy, nextResult);
        }
        Console.WriteLine("PASS one-shot discovery collector synthetic fixtures only; raw observations are not verified page/player data.");
    }
}
