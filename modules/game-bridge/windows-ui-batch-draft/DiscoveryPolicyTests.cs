namespace FootballAssistant.GameBridge;

internal static class DiscoveryPolicyTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new Exception("Discovery policy fixture: " + message); }
    internal static void Run()
    {
        var now = DateTimeOffset.Parse("2026-11-01T00:00:00Z");
        var context = new SmokeContext(12, "discovery-fixture", new string('a', 64), new string('b', 64), "FixtureWindow", 34);
        var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false)
        {
            WindowScanStatus = "complete", WindowScanCount = 1,
            WindowCandidates = new[] { new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureWindow", true, 0, true, true, 10, 10, 0) }
        };
        DiscoveryApproval Approval(bool enabled = true) => new(context, Guid.NewGuid(), 0, "0/3", now, now.AddSeconds(120), enabled);
        DiscoveryRequest Request(DiscoveryPolicy policy) => new(3, policy.Approval.Nonce, policy.ApprovalSha256);
        void Reject(DiscoveryApproval value)
        {
            var rejected = false;
            try { _ = new DiscoveryPolicy(value); } catch (ArgumentException) { rejected = true; }
            Check(rejected, "invalid approval rejected");
        }
        var offApproval = Approval(false);
        var off = new DiscoveryPolicy(offApproval);
        offApproval = offApproval with { ModeEnabled = true };
        Check(off.TryBegin(Request(off), identity, now) is null && !off.Consumed, "default off and immutable approval");
        foreach (var path in new[] { "/", "0/", "00", "01", "512", "-1", "+1", "0//1", "０", "1.0", string.Join("/", Enumerable.Repeat("0", 33)) })
        { Check(!DiscoveryPolicy.ValidPath(path), "noncanonical path"); Reject(Approval() with { FocusPath = path }); }
        Check(DiscoveryPolicy.ValidPath("") && DiscoveryPolicy.ValidPath(string.Join("/", Enumerable.Repeat("511", 32))), "32 edges and index511 accepted");
        Reject(Approval() with { Nonce = Guid.Empty });
        Reject(Approval() with { PanelIndex = -1 }); Reject(Approval() with { PanelIndex = 32 });
        Reject(Approval() with { ExpiresAt = now }); Reject(Approval() with { ExpiresAt = now.AddSeconds(121) });
        Reject(Approval() with { Context = context with { EntryThread = 0 } });
        var binding = new DiscoveryPolicy(Approval());
        var request = Request(binding);
        foreach (var invalid in new[] { request with { SchemaVersion = 2 }, request with { Nonce = Guid.Empty },
            request with { Nonce = Guid.NewGuid() }, request with { ApprovalSha256 = new string('0', 64) } })
            Check(binding.TryBegin(invalid, identity, now) is null && !binding.Consumed, "unauthenticated mismatch does not admit");
        foreach (var replacement in new[] { binding.Approval with { PanelIndex = 1 }, binding.Approval with { FocusPath = "0/4" },
            binding.Approval with { Context = context with { Session = "other" } },
            binding.Approval with { Context = context with { GameHash = new string('c', 64) } },
            binding.Approval with { Context = context with { BridgeHash = new string('c', 64) } },
            binding.Approval with { Context = context with { Pid = 13 } },
            binding.Approval with { Context = context with { EntryThread = 35 } },
            binding.Approval with { Context = context with { ConfirmedWindowClass = "Other" } },
            binding.Approval with { ExpiresAt = now.AddSeconds(119) } })
            Check(new DiscoveryPolicy(replacement).ApprovalSha256 != binding.ApprovalSha256, "all approved fields digest bound");
        Check(binding.TryBegin(request, identity, now.AddTicks(-1)) is null, "not before approval");
        var grant = binding.TryBegin(request, identity, now)!;
        Check(grant is not null && grant.MaximumOperations == 2048 && grant.MaximumMilliseconds == 1000 && binding.Consumed, "fixed limits");
        request = request with { Nonce = Guid.NewGuid() };
        Check(grant!.Request.Nonce == binding.Approval.Nonce && binding.CheckActive(grant, identity, now), "grant immutable");
        Check(binding.TryBegin(Request(binding), identity, now) is null, "one active slot");
        Check(binding.Finish(grant, 2048, 1000, true, now.AddSeconds(1)) && binding.Terminal, "exact caps success terminal");
        Check(binding.TryBegin(Request(binding), identity, now.AddSeconds(2)) is null &&
            !binding.Finish(grant, 0, 0, true, now) && binding.TotalOperations == 2048, "replay and repeated accounting rejected");
        var window = identity.WindowCandidates![0];
        var invalidIdentities = new[] {
            identity with { CurrentThreadId = 35 }, identity with { InstallerThreadId = 35 }, identity with { ProcessId = 13 },
            identity with { WindowScanStatus = "truncated" }, identity with { WindowScanCount = 2 },
            identity with { WindowCandidates = new[] { window, window with { Hwnd = 57 } }, WindowScanCount = 2 },
            identity with { WindowCandidates = new[] { window with { OwnerTid = 35 } } },
            identity with { WindowCandidates = new[] { window with { OwnerStable = false } } },
            identity with { WindowCandidates = new[] { window with { ClassNameComplete = false } } },
            identity with { WindowCandidates = new[] { window with { VisibleStyle = false } } },
            identity with { WindowCandidates = new[] { window with { ClientRectAvailable = false } } },
            identity with { WindowCandidates = new[] { window with { ClientWidth = 0 } } }
        };
        foreach (var invalid in invalidIdentities)
        {
            var admission = new DiscoveryPolicy(Approval());
            Check(admission.TryBegin(Request(admission), invalid, now) is null && admission.Consumed && admission.Terminal &&
                admission.TryBegin(Request(admission), identity, now) is null, "failed admission consumes attempt");
            var guarded = new DiscoveryPolicy(Approval()); var g = guarded.TryBegin(Request(guarded), identity, now)!;
            Check(!guarded.CheckActive(g, invalid, now) && !guarded.Finish(g, 7, 5, true, now) && guarded.TotalOperations == 7,
                "every fresh guard failure terminal and accounted");
        }
        foreach (var failure in new[] { "failure", "operations", "time", "expiry", "backwards", "cancel", "stop", "forged", "forged_finish", "nan" })
        {
            var policy = new DiscoveryPolicy(Approval()); var g = policy.TryBegin(Request(policy), identity, now)!;
            if (failure == "cancel") Check(!policy.CheckActive(g, identity, now, new CancellationToken(true)), "cancel guard");
            if (failure == "stop") policy.Stop();
            if (failure == "forged") Check(!policy.CheckActive(g with { Window = 57 }, identity, now), "forged grant");
            if (failure == "forged_finish") Check(!policy.Finish(g with { MaximumOperations = 4096 }, 0, 0, true, now), "forged finish");
            Check(!policy.Finish(g, failure == "operations" ? 2049 : 7,
                failure == "time" ? 1000.01 : failure == "nan" ? double.NaN : 5,
                failure != "failure", failure == "expiry" ? now.AddSeconds(120) : failure == "backwards" ? now.AddTicks(-1) : now), "failure denies output");
            Check(policy.Terminal && policy.TryBegin(Request(policy), identity, now) is null, "no retry after failure");
            if (failure != "nan") Check(policy.TotalOperations == (failure == "operations" ? 2049 : 7), "actual cost including failures");
        }
        var stopped = new DiscoveryPolicy(Approval()); stopped.Stop();
        Check(stopped.TryBegin(Request(stopped), identity, now) is null, "idle stop");
        var expired = new DiscoveryPolicy(Approval());
        Check(expired.TryBegin(Request(expired), identity, now.AddSeconds(120)) is null && expired.Terminal, "expiry admission");
    }
}
