namespace FootballAssistant.GameBridge;

internal static class DiscoverySessionGateTests
{
    private static void Check(bool value, string message) { if (!value) throw new Exception("Discovery host gate: " + message); }
    internal static void Run()
    {
        var now = DateTimeOffset.Parse("2026-11-01T00:00:00Z");
        var context = new SmokeContext(12, "fixture-session", new string('a',64), new string('b',64), "UnityWndClass", 34);
        var request = new DiscoveryHostRequest(Guid.NewGuid(),12,context.Session,context.BridgeHash,context.GameHash,
            "UnityWndClass",0,"0/6",now,now.AddSeconds(30));
        var gate = new DiscoverySessionGate(context);
        foreach (var bad in new[] { request with { Pid = 13 }, request with { Session = "other" },
            request with { GameHash = new string('c',64) }, request with { BridgeHash = new string('c',64) },
            request with { FocusPath = "0/7" }, request with { PanelIndex = 1 }, request with { WindowClass = "Other" },
            request with { RequestedAt = now.AddSeconds(1) }, request with { ExpiresAt = now } })
            Check(gate.TryTake(bad,now) is null && !gate.Taken,"invalid/replaced request cannot reach native admission");
        var policy = gate.TryTake(request,now)!;
        Check(policy is not null && gate.Taken && policy.Approval.Context.EntryThread == 34 &&
            policy.Approval.PanelIndex == 0 && policy.Approval.FocusPath == "0/6", "exact immutable session/entry-thread/scope binding");
        request = request with { FocusPath = "0/7", Nonce = Guid.NewGuid() };
        Check(policy.Approval.FocusPath == "0/6", "request replacement after admission cannot alter active grant");
        policy.Stop();
        Check(gate.TryTake(request with { FocusPath = "0/6" },now) is null,
            "native failure does not free host's one session attempt even for another nonce");
        var race = new DiscoverySessionGate(context);
        var admitted = 0;
        Parallel.For(0,32,_ => { if (race.TryTake(request with { FocusPath = "0/6", Nonce = Guid.NewGuid() },now) is not null) Interlocked.Increment(ref admitted); });
        Check(admitted == 1 && race.Taken,"concurrent request replacements admit exactly one attempt");
        // Wrong entry/callback ownership is rejected by the real policy, never repaired by current-TID rebinding.
        var ownerGate = new DiscoverySessionGate(context);
        var ownerPolicy = ownerGate.TryTake(request with { FocusPath = "0/6" },now)!;
        var token = new DiscoveryRequest(3,ownerPolicy.Approval.Nonce,ownerPolicy.ApprovalSha256);
        var wrongThread = new WindowsThreadIdentity(0,12,0,35,0,34,false)
        { WindowScanStatus="complete", WindowScanCount=1, WindowCandidates=new[]
            { new WindowsWindowDiagnostic(56,12,35,true,"UnityWndClass",true,0,true,true,10,10,0) } };
        Check(ownerPolicy.TryBegin(token,wrongThread,now) is null && ownerPolicy.Terminal && ownerGate.Taken,
            "callback cannot replace the original entry thread to obtain a grant");
        Console.WriteLine("PASS discovery host session gate (synthetic, no host startup/native calls).");
    }
}
