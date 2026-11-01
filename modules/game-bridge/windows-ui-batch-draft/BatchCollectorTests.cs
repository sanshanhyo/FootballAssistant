using FootballAssistant.GameBridge;

internal static class BatchCollectorTests
{
    private static void Check(bool value, string label) { if (!value) throw new Exception(label); }
    internal static void Run()
    {
        var start = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context = new SmokeContext(12, "batch-fixture", new string('a', 64), new string('b', 64), "FixtureWindow", 34);
        var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false)
        { WindowScanStatus = "complete", WindowScanCount = 1, WindowCandidates = new[]
            { new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureWindow", true, 0, true, true, 10, 10, 0) } };
        BatchApproval Approval(string body) => new(context, Guid.NewGuid(), Guid.NewGuid(), 0, body,
            new(BatchTreeFixture.Anchor1Path, BatchPolicy.Digest("fixture-page")),
            new(BatchTreeFixture.Anchor2Path, BatchPolicy.Digest("fixture-subject")),
            start, start.AddSeconds(120), new(), true);
        BatchRequest Request(BatchPolicy policy, int sequence, string cursor, DateTimeOffset at) => new(
            2, Guid.NewGuid(), policy.Approval.BatchId, sequence, policy.Approval.PageEpoch,
            context.Pid, context.Session, context.BridgeHash, context.GameHash, context.ConfirmedWindowClass,
            0, policy.Approval.SubtreePath, policy.ApprovalSha256, BatchPolicy.ComputeCursorHash(cursor),
            at, at.AddSeconds(30), cursor);
        foreach (var depth in new[] { 21, 32 })
        {
            var body = "2" + string.Concat(Enumerable.Repeat("/0", depth - 1));
            var policy = new BatchPolicy(Approval(body));
            var cursor = ""; var texts = new List<BatchText>(); var operations = 0; var chunks = 0;
            BatchChunkResult? last = null;
            for (var sequence = 1; sequence <= 4; sequence++)
            {
                using var fixture = new BatchTreeFixture(); fixture.Build(depth);
                var at = start.AddSeconds(sequence * 3);
                var freshChecks = 0;
                last = BatchCollector.Run(policy, Request(policy, sequence, cursor, at),
                    () => new BatchNativeBackend(context.GameHash, fixture.Bind), () => { freshChecks++; return identity; }, () => at, elapsedForTest: () => 0)!;
                chunks++; operations += last.NativeOperations;
                var expectedOperations = depth == 21 ? new[] { 1820 } : new[] { 1871, 1904, 1855 };
                var expectedRoots = depth == 21 ? new[] { 293 } : new[] { 305, 310, 303 };
                var expectedNodes = depth == 21 ? new[] { 90 } : new[] { 95, 96, 94 };
                Check(sequence <= expectedOperations.Length && last.NativeOperations == expectedOperations[sequence - 1] &&
                    last.TotalRoots == expectedRoots[sequence - 1] && last.PeakRoots == 3 &&
                    last.Nodes == expectedNodes[sequence - 1] && freshChecks == last.NativeOperations + last.Nodes + 3,
                    "full anchored collector exact synthetic accounting (including prepare/final guard, no cached guard)");

                Check(last.AnchorsValidated && last.Status is BatchCompletion.Continue or BatchCompletion.Complete,
                    "deep synthetic page chunk passes both anchors and policy");
                Check(last.NativeOperations <= 2048 && last.TotalRoots <= 512 && last.PeakRoots <= 64 &&
                    last.Nodes <= 128 && fixture.LiveRoots == 0 && fixture.RootCreates == fixture.RootFrees,
                    "deep chunk caps and all-root cleanup");
                Check(last.Texts.Length <= 8 && last.Texts.Sum(t => t.Text.Length) <= 1024 &&
                    last.Texts.All(t => BatchPolicy.IsWithinSubtree(t.Path, body)),
                    "bounded fields remain within approved subtree");
                texts.AddRange(last.Texts);
                if (last.Status == BatchCompletion.Complete) break;
                Check(!string.IsNullOrEmpty(last.NextCursor), "continuation is explicit numeric cursor with progress");
                cursor = last.NextCursor!;
            }
            Check(last!.Status == BatchCompletion.Complete && texts.Count == 4 &&
                texts.Select(t => t.Text).Distinct().Count() == 4 && texts.Select(t => t.Path).Distinct().Count() == 4 &&
                operations == policy.TotalOperations && policy.Terminal,
                "finite same-session chunks collect exactlyfour synthetic fields once, not a player identity");
            Console.WriteLine($"Batch depth{depth}: chunks={chunks}, reserved_total={operations}, fields={texts.Count}; fake native exports, elapsed injected0 (NOT timing evidence).");
        }
        {
            using var fixture = new BatchTreeFixture { ChangePostAnchor = true }; fixture.Build(21);
            var policy = new BatchPolicy(Approval(fixture.BodyPath));
            var result = BatchCollector.Run(policy, Request(policy, 1, "", start),
                () => new BatchNativeBackend(context.GameHash, fixture.Bind), () => identity, () => start, elapsedForTest: () => 0)!;
            Check(result.Status == BatchCompletion.Terminal && result.Texts.Length == 0 && result.NextCursor is null &&
                !result.AnchorsValidated && policy.Terminal && fixture.LiveRoots == 0,
                "changed post-anchor discards all provisional fields and continuation");
        }
        {
            using var fixture = new BatchTreeFixture { CycleBody = true }; fixture.Build(32);
            var policy = new BatchPolicy(Approval(fixture.BodyPath)); var cursor = "";
            for (var sequence = 1; sequence <= 4 && !policy.Terminal; sequence++)
            {
                var at = start.AddSeconds(sequence * 3);
                var result = BatchCollector.Run(policy, Request(policy, sequence, cursor, at),
                    () => new BatchNativeBackend(context.GameHash, fixture.Bind), () => identity, () => at, elapsedForTest: () => 0)!;
                Check(result.Nodes <= 128 && result.NativeOperations <= 2048 && result.Texts.Length == 0 &&
                    fixture.LiveRoots == 0, "cyclic graph stays bounded and cleans roots");
                cursor = result.NextCursor ?? "";
            }
            Check(policy.Terminal, "cycles cannot create an unbounded batch");
        }
        foreach (var failAt in new[] { 1, 30, 100, 500, 1500 })
        {
            using var fixture = new BatchTreeFixture(); fixture.Build(21);
            var policy = new BatchPolicy(Approval(fixture.BodyPath)); var checks = 0;
            var result = BatchCollector.Run(policy, Request(policy, 1, "", start),
                () => new BatchNativeBackend(context.GameHash, fixture.Bind),
                () => ++checks == failAt ? identity with { WindowScanStatus = "failed" } : identity,
                () => start, elapsedForTest: () => 0);
            if (result is not null)
                Check(result.Status == BatchCompletion.Terminal && result.Texts.Length == 0 && !result.AnchorsValidated,
                    "guard loss in any collection phase discards output");
            Check(policy.Terminal && fixture.LiveRoots == 0 && fixture.RootFrees == fixture.RootCreates,
                "guard failure terminates and cleans all retained objects");
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.Build(21);
            var policy = new BatchPolicy(Approval(fixture.BodyPath));
            var result = BatchCollector.Run(policy, Request(policy, 1, "", start),
                () => new BatchNativeBackend(context.GameHash, fixture.Bind), () => identity, () => start,
                elapsedForTest: () => fixture.PanelOpens >= 5 && fixture.LiveRoots == 0 ? 1001 : 0)!;
            Check(result.Status == BatchCompletion.Terminal && result.Texts.Length == 0 && fixture.LiveRoots == 0,
                "elapsed overrun including cleanup never publishes stale provisional output");
        }
        {
            using var fixture = new BatchTreeFixture(); fixture.Build(21);
            var policy = new BatchPolicy(Approval(fixture.BodyPath)); var threw = false;
            DateTimeOffset FaultingClock()
            {
                if (fixture.PanelOpens >= 5 && fixture.LiveRoots == 0) throw new InvalidOperationException("fixture finalization clock");
                return start;
            }
            try
            {
                BatchCollector.Run(policy, Request(policy, 1, "", start),
                    () => new BatchNativeBackend(context.GameHash, fixture.Bind), () => identity, FaultingClock, elapsedForTest: () => 0);
            }
            catch (InvalidOperationException) { threw = true; }
            Check(threw && policy.Terminal && policy.TotalOperations > 0 && fixture.LiveRoots == 0,
                "post-consume finalization exception still accounts and terminates after root cleanup");
        }
        Console.WriteLine("PASS batch collector synthetic fixtures only; no real module/host, no latency claim.");
    }
}
