namespace FootballAssistant.GameBridge;

// Synthetic policy checks only: no host, window enumeration, game DLL or UI action.
internal static class BatchPolicyTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new Exception("Batch policy fixture: " + message); }
    internal static void Run()
    {
        var now = DateTimeOffset.Parse("2026-11-01T00:00:00Z");
        var context = new SmokeContext(12, "batch-fixture", new string('a', 64), new string('b', 64), "FixtureWindow", 34);
        var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false)
        {
            WindowScanStatus = "complete", WindowScanCount = 1,
            WindowCandidates = new[] { new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureWindow", true, 0, true, true, 10, 10, 0) }
        };
        BatchApproval Approval(bool enabled = false, BatchLimits? limits = null) => new(context, Guid.NewGuid(), Guid.NewGuid(), 0, "0/6",
            new("0/3", BatchPolicy.Digest("TEST identity anchor")), new("0/4", BatchPolicy.Digest("TEST page anchor")),
            now, now.AddSeconds(120), limits ?? new(), enabled);
        BatchRequest Request(BatchPolicy policy, DateTimeOffset? at = null, int sequence = 1, string? cursor = null) => new(2,
            Guid.NewGuid(), policy.Approval.BatchId, sequence, policy.Approval.PageEpoch, context.Pid, context.Session,
            context.BridgeHash, context.GameHash, context.ConfirmedWindowClass, policy.Approval.PanelIndex,
            policy.Approval.SubtreePath, policy.ApprovalSha256, BatchPolicy.ComputeCursorHash(cursor ?? (sequence == 1 ? "" : "0/1;2")),
            at ?? now, (at ?? now).AddSeconds(30), cursor ?? (sequence == 1 ? "" : "0/1;2"));
        void ConstructorRejects(BatchApproval approval, string reason)
        {
            var rejected = false;
            try { _ = new BatchPolicy(approval); } catch (ArgumentException) { rejected = true; }
            Check(rejected, reason);
        }

        var disabledApproval = Approval();
        var disabled = new BatchPolicy(disabledApproval);
        disabledApproval = disabledApproval with { ModeEnabled = true };
        Check(disabled.TryBegin(Request(disabled), identity, now) is null && disabled.RequestsConsumed == 0,
            "default-off approval cannot be enabled by replacing caller record");
        foreach (var invalid in new[] { "/", "0/", "/0", "00", "01", "-1", "+1", "1.0", "512", "0//1", "０", "0\n", string.Join("/", Enumerable.Repeat("0", 49)) })
        {
            Check(!BatchPolicy.ValidPath(invalid), "canonical path rejects " + invalid.Length);
            ConstructorRejects(Approval(true) with { SubtreePath = invalid }, "invalid allowed subtree rejected");
        }
        Check(BatchPolicy.ValidPath("") && BatchPolicy.ValidPath(string.Join("/", Enumerable.Repeat("511", 48))) &&
            BatchPolicy.IsWithinSubtree("0/6/0", "0/6") && !BatchPolicy.IsWithinSubtree("0/60", "0/6"),
            "canonical bounds and segment-aware subtree containment");
        var valid = Approval(true);
        var maxAnchorApproval = valid with { Anchor1 = valid.Anchor1 with { Path = string.Join("/", Enumerable.Repeat("511", 16)) } };
        Check(new BatchPolicy(maxAnchorApproval).Approval.Anchor1.Path.Split('/').Length == 16, "anchor16 boundary accepted");
        ConstructorRejects(valid with { Anchor2 = valid.Anchor1 }, "two distinct anchors required");
        ConstructorRejects(valid with { Anchor1 = valid.Anchor1 with { TextSha256 = BatchPolicy.EmptyCursorSha256 } }, "empty anchor rejected");
        ConstructorRejects(valid with { Anchor1 = valid.Anchor1 with { TextSha256 = new string('A', 64) } }, "hash canonical lowercase required");
        ConstructorRejects(valid with { Anchor1 = valid.Anchor1 with { Path = string.Join("/", Enumerable.Repeat("0", 17)) } }, "anchor maximum16 edges");
        ConstructorRejects(valid with { PageEpoch = Guid.Empty }, "explicit page epoch required");
        ConstructorRejects(valid with { ExpiresAt = now.AddSeconds(121) }, "maximum batch lifetime120 seconds");
        foreach (var limits in new[] { new BatchLimits(MaximumRequests: 5), new BatchLimits(RequestOperations: 2049),
            new BatchLimits(RequestMilliseconds: 1000.001), new BatchLimits(TotalOperations: 8193),
            new BatchLimits(TotalMilliseconds: 4000.001), new BatchLimits(CooldownSeconds: 1.999),
            new BatchLimits(RequestMilliseconds: double.NaN), new BatchLimits(TotalMilliseconds: double.PositiveInfinity) })
            ConstructorRejects(valid with { Limits = limits }, "draft ceilings cannot increase");

        var binding = new BatchPolicy(Approval(true));
        var correct = Request(binding);
        foreach (var invalid in new[] { correct with { SchemaVersion = 1 }, correct with { Nonce = Guid.Empty },
            correct with { BatchId = Guid.NewGuid() }, correct with { Sequence = 0 }, correct with { PageEpoch = Guid.NewGuid() },
            correct with { Pid = 13 }, correct with { Session = "stale" }, correct with { BridgeHash = new string('c', 64) },
            correct with { GameHash = new string('c', 64) }, correct with { ConfirmedWindowClass = "Other" },
            correct with { PanelIndex = 1 }, correct with { SubtreePath = "0/4" },
            correct with { ApprovalSha256 = new string('0', 64) }, correct with { CursorSha256 = new string('0', 64) },
            correct with { Cursor = "0" }, correct with { Cursor = new string('0', 16385) },
            correct with { CreatedAt = now.AddSeconds(1) }, correct with { ExpiresAt = now },
            correct with { ExpiresAt = now.AddSeconds(31) } })
            Check(binding.TryBegin(invalid, identity, now) is null && binding.RequestsConsumed == 0,
                "mismatched request cannot admit any work");
        var granted = binding.TryBegin(correct, identity, now)!;
        Check(granted is not null && binding.RequestsConsumed == 1 && granted.MaximumOperations == 2048 &&
            granted.MaximumMilliseconds == 1000 && binding.CheckActive(granted, identity, now), "explicit bound request begins");
        Check(binding.TryBegin(Request(binding), identity, now) is null && binding.RequestsConsumed == 1,
            "one active request, no concurrent or duplicate admission");
        correct = correct with { SubtreePath = "0/4", PageEpoch = Guid.NewGuid() };
        Check(granted!.Request.SubtreePath == "0/6" && binding.CheckActive(granted, identity, now),
            "replacement of external request cannot alter immutable grant");
        var cursor2 = BatchPolicy.ComputeCursorHash("0/1;2");
        Check(binding.Finish(granted, 300, 150, true, false, cursor2, now.AddMilliseconds(150)) == BatchCompletion.Continue,
            "post-anchor-valid normal chunk can continue");
        Check(binding.TryBegin(Request(binding, now.AddSeconds(1), 2), identity, now.AddSeconds(1)) is null,
            "cooldown prevents immediate additional capture");
        var secondRequest = Request(binding, now.AddSeconds(3), 2);
        Check(binding.TryBegin(secondRequest with { Nonce = granted.Request.Nonce }, identity, now.AddSeconds(3)) is null,
            "nonce replay rejected despite new sequence/cursor");
        Check(binding.TryBegin(secondRequest with { CursorSha256 = BatchPolicy.EmptyCursorSha256 }, identity, now.AddSeconds(3)) is null,
            "stale numeric cursor digest cannot restart old subtree");
        var second = binding.TryBegin(secondRequest, identity, now.AddSeconds(3))!;
        Check(binding.Finish(second, 200, 100, true, true, null, now.AddSeconds(3.1)) == BatchCompletion.Complete &&
            binding.Terminal && binding.TotalOperations == 500 && binding.TotalMilliseconds == 250,
            "completed page group is terminal with full aggregate accounting");
        Check(binding.TryBegin(Request(binding, now.AddSeconds(6), 3), identity, now.AddSeconds(6)) is null,
            "completion cannot autonomously start another page epoch");

        foreach (var badIdentity in new[] { identity with { CurrentThreadId = 35 }, identity with { InstallerThreadId = 35 },
            identity with { WindowScanStatus = "truncated" }, identity with { WindowScanCount = 2 },
            identity with { WindowScanCount = 2, WindowCandidates = new[] { identity.WindowCandidates![0], identity.WindowCandidates[0] with { Hwnd = 57 } } } })
        {
            var p = new BatchPolicy(Approval(true));
            var g = p.TryBegin(Request(p), identity, now)!;
            Check(!p.CheckActive(g, badIdentity, now) && p.Terminal, "fresh ownership failure terminates batch");
            Check(p.Finish(g, 23, 12, false, false, null, now) == BatchCompletion.Terminal && p.TotalOperations == 23,
                "failed ownership attempt still charges work");
        }
        var forged = new BatchPolicy(Approval(true));
        var original = forged.TryBegin(Request(forged), identity, now)!;
        Check(!forged.CheckActive(original with { Request = original.Request with { SubtreePath = "0/4" } }, identity, now) &&
            forged.Terminal, "forged active grant cannot change subtree");
        forged.Finish(original, 11, 10, false, false, null, now);
        Check(forged.TotalOperations == 11, "original grant remains accountable after forged check");
        var stoppedIdle = new BatchPolicy(Approval(true));
        stoppedIdle.Stop();
        Check(stoppedIdle.TryBegin(Request(stoppedIdle), identity, now) is null && stoppedIdle.Terminal,
            "explicit user stop also prevents work while no grant is active");
        var canceled = new BatchPolicy(Approval(true));
        var canceledGrant = canceled.TryBegin(Request(canceled), identity, now)!;
        Check(!canceled.CheckActive(canceledGrant, identity, now, new CancellationToken(true)) && canceled.Terminal,
            "cancellation stops batch rather than authorizing next chunk");
        canceled.Finish(canceledGrant, 5, 4, false, false, null, now);
        var expired = new BatchPolicy(Approval(true));
        var expiringGrant = expired.TryBegin(Request(expired), identity, now)!;
        Check(!expired.CheckActive(expiringGrant, identity, now.AddSeconds(30)), "request expiry remains fresh at each boundary");
        expired.Finish(expiringGrant, 1, 1, false, false, null, now.AddSeconds(30));

        foreach (var end in new[] { (Ops: 80, Ms: 40d, Anchors: false), (Ops: 2049, Ms: 40d, Anchors: true),
            (Ops: 80, Ms: 1000.01, Anchors: true) })
        {
            var p = new BatchPolicy(Approval(true)); var g = p.TryBegin(Request(p), identity, now)!;
            Check(p.Finish(g, end.Ops, end.Ms, end.Anchors, false, cursor2, now.AddMilliseconds(end.Ms)) == BatchCompletion.Terminal &&
                p.TotalOperations == end.Ops && p.TotalMilliseconds == end.Ms, "anchor failure or overshoot cannot publish continuation; overhead charged");
        }
        var remaining = new BatchPolicy(Approval(true, new BatchLimits(TotalOperations: 3000, TotalMilliseconds: 1200)));
        var first = remaining.TryBegin(Request(remaining), identity, now)!;
        Check(remaining.Finish(first, 2000, 900, true, false, cursor2, now.AddMilliseconds(900)) == BatchCompletion.Continue,
            "first chunk consumes aggregate allocation");
        var last = remaining.TryBegin(Request(remaining, now.AddSeconds(3), 2), identity, now.AddSeconds(3))!;
        Check(last.MaximumOperations == 1000 && last.MaximumMilliseconds == 300,
            "next grant cannot exceed remaining batch operations/time");
        Check(remaining.Finish(last, 1001, 301, true, true, null, now.AddSeconds(3.301)) == BatchCompletion.Terminal &&
            remaining.TotalOperations == 3001 && remaining.TotalMilliseconds == 1201,
            "aggregate overshoot retained, not subtracted or reported complete");

        var finite = new BatchPolicy(Approval(true));
        for (var index = 1; index <= 4; index++)
        {
            var at = now.AddSeconds(index * 3);
            var g = finite.TryBegin(Request(finite, at, index, index == 1 ? "" : (index - 1).ToString()), identity, at)!;
            var outcome = finite.Finish(g, 10, 5, true, false, BatchPolicy.ComputeCursorHash(index.ToString()), at.AddMilliseconds(5));
            Check(outcome == (index == 4 ? BatchCompletion.Terminal : BatchCompletion.Continue), "request count bounds continuation");
        }
        Check(finite.RequestsConsumed == 4 && finite.Terminal, "four requests is a hard finite batch limit");

        var atLimits = new BatchPolicy(Approval(true));
        for (var index = 1; index <= 4; index++)
        {
            var at = now.AddSeconds(index * 4);
            var g = atLimits.TryBegin(Request(atLimits, at, index, index == 1 ? "" : (index - 1).ToString()), identity, at)!;
            var result = atLimits.Finish(g, 2048, 1000, true, index == 4,
                BatchPolicy.ComputeCursorHash(index.ToString()), at.AddSeconds(1));
            Check(result == (index == 4 ? BatchCompletion.Complete : BatchCompletion.Continue),
                "exact per-request and cumulative boundaries are admitted, never enlarged");
        }
        Check(atLimits.TotalOperations == 8192 && atLimits.TotalMilliseconds == 4000 && atLimits.Terminal,
            "exact final aggregate cap accounted");
        var forgedFinish = new BatchPolicy(Approval(true));
        var realGrant = forgedFinish.TryBegin(Request(forgedFinish), identity, now)!;
        Check(forgedFinish.Finish(realGrant with { MaximumOperations = 4096 }, 1, 1, true, true, null, now) == BatchCompletion.Rejected,
            "forged completion cannot grant output or enlarge budget");
        Check(forgedFinish.Finish(realGrant, 3, 2, false, false, null, now) == BatchCompletion.Terminal &&
            forgedFinish.TotalOperations == 3, "real outstanding grant is accounted after forged finish");
        Check(forgedFinish.Finish(realGrant, 3, 2, true, true, null, now) == BatchCompletion.Rejected &&
            forgedFinish.TotalOperations == 3, "completion replay never double-charges or reopens batch");
        var backward = new BatchPolicy(Approval(true));
        var backwardGrant = backward.TryBegin(Request(backward), identity, now)!;
        Check(!backward.CheckActive(backwardGrant, identity, now.AddTicks(-1)), "backward wall clock fails closed");
        backward.Finish(backwardGrant, 1, 1, false, false, null, now);
        // Pure JSON decoding tests; no filesystem or runtime activation.
        var codecPolicy = new BatchPolicy(Approval(true));
        var codecRequest = Request(codecPolicy);
        var json = System.Text.Json.JsonSerializer.Serialize(new
        {
            schema_version = codecRequest.SchemaVersion, nonce = codecRequest.Nonce, batch_id = codecRequest.BatchId,
            sequence = codecRequest.Sequence, page_epoch = codecRequest.PageEpoch, pid = codecRequest.Pid,
            session_id = codecRequest.Session, bridge_sha256 = codecRequest.BridgeHash, game_sha256 = codecRequest.GameHash,
            window_class = codecRequest.ConfirmedWindowClass, panel_index = codecRequest.PanelIndex,
            subtree_path = codecRequest.SubtreePath, approval_sha256 = codecRequest.ApprovalSha256,
            cursor_sha256 = codecRequest.CursorSha256, created_at = codecRequest.CreatedAt,
            expires_at = codecRequest.ExpiresAt, cursor = codecRequest.Cursor
        });
        Check(BatchRequestCodec.Parse(json) == codecRequest, "strict schema2 roundtrip preserves immutable binding");
        void InvalidJson(string candidate, string reason)
        {
            var rejected = false;
            try { BatchRequestCodec.Parse(candidate); }
            catch (Exception error) when (error is InvalidOperationException or System.Text.Json.JsonException or ArgumentException)
            { rejected = true; }
            Check(rejected, reason);
        }
        string Changed(string name, string token)
        {
            var node = System.Text.Json.Nodes.JsonNode.Parse(json)!.AsObject();
            node[name] = System.Text.Json.Nodes.JsonNode.Parse(token);
            return node.ToJsonString();
        }
        InvalidJson(json[..^1] + ",\"nonce\":\"" + codecRequest.Nonce + "\"}", "duplicate schema property rejects");
        InvalidJson(json[..^1] + ",\"mode_enabled\":true}", "request cannot enable mode or add properties");
        var missing = System.Text.Json.Nodes.JsonNode.Parse(json)!.AsObject(); missing.Remove("cursor");
        InvalidJson(missing.ToJsonString(), "cursor is explicit and required in schema2");
        InvalidJson("[]", "root must be request object");
        foreach (var field in new[] { "schema_version", "pid", "sequence", "panel_index" })
            foreach (var token in new[] { "-0", "-1", "1.0", "1e0", "true", "null", "\"1\"", "2147483648" })
                InvalidJson(Changed(field, token), "integer fields reject noncanonical or out-of-range tokens");
        InvalidJson(Changed("schema_version", "1"), "old schema cannot enter batch codec");
        InvalidJson(Changed("pid", "0"), "PID positive");
        InvalidJson(Changed("sequence", "5"), "request sequence bounded by finite ceiling");
        InvalidJson(Changed("panel_index", "32"), "panel index upper bound");
        foreach (var field in new[] { "session_id", "window_class", "subtree_path", "cursor", "bridge_sha256", "created_at" })
            InvalidJson(Changed(field, "null"), "null is not an omitted/default string");
        InvalidJson(Changed("nonce", "\"00000000-0000-0000-0000-000000000000\""), "empty UUID rejected");
        InvalidJson(Changed("nonce", "\"ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB\""), "UUID canonical case enforced");
        InvalidJson(Changed("page_epoch", "\"not-a-uuid\""), "page epoch UUID required");
        InvalidJson(Changed("created_at", "\"yesterday\""), "timestamp ISO syntax enforced");
        InvalidJson(Changed("created_at", "\"2026-11-01T00:00:00\""), "timestamp must carry explicit offset");
        InvalidJson(Changed("bridge_sha256", "\"" + new string('A', 64) + "\""), "hash canonical lowercase enforced");
        InvalidJson(Changed("subtree_path", "\"0/00\""), "subtree numeric syntax enforced");
        InvalidJson(Changed("cursor", "\"" + new string('0', 16385) + "\""), "cursor character bound enforced");
        InvalidJson(json.Replace("batch-fixture", new string('漢', 11000)), "UTF8 bytes bounded even when UTF16 length is smaller");
        InvalidJson(json + new string(' ', 32768), "whole request byte limit enforced");
        var cursorBoundary = BatchRequestCodec.Parse(Changed("cursor", "\"" + new string('0', 16384) + "\""));
        Check(cursorBoundary.Cursor.Length == 16384 && codecPolicy.TryBegin(cursorBoundary, identity, now) is null,
            "codec size boundary is not authorization; policy rejects mismatched cursor hash");
        Console.WriteLine("PASS finite batch policy synthetic checks only; no host or game calls.");
    }
}
