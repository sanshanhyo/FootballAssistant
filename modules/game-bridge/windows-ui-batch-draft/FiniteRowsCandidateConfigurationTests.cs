using System.Text.Json;
using FootballAssistant.GameBridge;
internal static class FiniteRowsCandidateConfigurationTests
{
    private static void Check(bool value, string message)
    { if (!value) throw new Exception("Finite configuration: " + message); }
    private static void Reject(Action action, string message)
    { try { action(); } catch { return; } throw new Exception("Expected rejection: " + message); }
    internal static void Run()
    {
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        var context = new SmokeContext(12, Guid.NewGuid().ToString("D"), new string('a',64), new string('b',64), "UnityWndClass",34);
        Dictionary<string,object> Input() => new()
        {
            ["schema_version"] = 4, ["mode"] = "goalkeeper_rows0_3", ["batch_id"] = Guid.NewGuid().ToString("D"),
            ["page_epoch"] = Guid.NewGuid().ToString("D"), ["first_nonce"] = Guid.NewGuid().ToString("D"),
            ["second_nonce"] = Guid.NewGuid().ToString("D"), ["pid"] = context.Pid, ["session_id"] = context.Session,
            ["bridge_sha256"] = context.BridgeHash, ["game_sha256"] = context.GameHash, ["window_class"] = "UnityWndClass",
            ["stable_profile_asserted"] = true, ["requested_at"] = at.ToString("O"), ["expires_at"] = at.AddSeconds(120).ToString("O")
        };
        FiniteRowsHostManifest Parse(Dictionary<string,object> input) => FiniteRowsCandidateConfiguration.ParseRequest(JsonSerializer.Serialize(input));
        var valid = Input(); var manifest = Parse(valid);
        Check(manifest.StableProfileAsserted && manifest.FirstNonce != manifest.SecondNonce &&
            FiniteRowsCandidateConfiguration.TryApproval(manifest, context, at) is { ModeEnabled: true },
            "one explicit manifest binds exact context, two nonce slots and operator-only page epoch");
        foreach (var (field,value) in new (string,object)[]
        {
            ("schema_version",3), ("schema_version",4.5), ("mode","ui_discovery_once"),
            ("mode","goalkeeper_rows0_4"), ("mode","schedule_rows0_10"), ("mode","schedule_row0"), ("stable_profile_asserted",false), ("stable_profile_asserted","true"),
            ("first_nonce",Guid.Empty.ToString("D")), ("page_epoch",Guid.Empty.ToString("D")),
            ("window_class","OtherWindow"), ("pid",0), ("pid",12.5), ("bridge_sha256",new string('A',64)),
            ("expires_at",at.AddSeconds(121).ToString("O")), ("requested_at","2026-01-01T00:00:00")
        })
        { var invalid = Input(); invalid[field] = value; Reject(() => Parse(invalid), "invalid " + field); }
        foreach(var scope in new[]{"profile_rows0_3","profile_all_rows","tactics_current", "tactics_alignment_candidate", "tactics_sibling_inventory","next_match_card","schedule_rows0_9"}) {
            var expanded=Input();expanded["mode"]=scope;
            var parsed=Parse(expanded);var approved=FiniteRowsCandidateConfiguration.TryApproval(parsed,context,at)!;
            Check(parsed.Manifest==scope && approved.Manifest==scope && approved.ModeEnabled,"request mode exactly binds immutable manifest");
            Reject(()=>DiscoveryCandidateConfiguration.ParseRequest(JsonSerializer.Serialize(expanded)),"old single-shot consumer rejects new manifest");
            Check(FiniteRowsCandidateConfiguration.TryApproval(parsed with{Manifest="profile_custom"},context,at) is null,
                "direct record cannot introduce arbitrary manifest");
            var sealedGate=new FiniteRowsSessionGate(context);
            Check(sealedGate.TryTake(parsed,at) is not null && sealedGate.TryTake(parsed with{Manifest="goalkeeper_rows0_3"},at) is null,
                "manifest replacement after admission rejected");
        }
        Check(manifest.Manifest=="goalkeeper_rows0_3","legacy request keeps exact old scope");
        var duplicateNonce = Input(); duplicateNonce["second_nonce"] = duplicateNonce["first_nonce"];
        Reject(() => Parse(duplicateNonce), "same nonce in both slots");
        var extra = Input(); extra["focus_path"] = "0/6"; Reject(() => Parse(extra), "no arbitrary focus/path override");
        var missing = Input(); missing.Remove("page_epoch"); Reject(() => Parse(missing), "page epoch mandatory");
        var json = JsonSerializer.Serialize(valid);
        Reject(() => FiniteRowsCandidateConfiguration.ParseRequest(json[..^1] + ",\"mode\":\"goalkeeper_rows0_3\"}"), "duplicate JSON key");
        Reject(() => FiniteRowsCandidateConfiguration.ParseRequest(new string(' ',4097)), "bounded manifest");
        Reject(() => DiscoveryCandidateConfiguration.ParseRequest(json), "old single-shot parser never accepts finite manifest");
        Check(FiniteRowsCandidateConfiguration.TryApproval(manifest with { Session = "replaced" }, context, at) is null &&
            FiniteRowsCandidateConfiguration.TryApproval(manifest with { Pid = 99 }, context, at) is null &&
            FiniteRowsCandidateConfiguration.TryApproval(manifest with { StableProfileAsserted = false }, context, at) is null &&
            FiniteRowsCandidateConfiguration.TryApproval(manifest, context, at.AddSeconds(120)) is null,
            "direct record bypass still rejects stale/replaced/expired bindings");
        var gate = new FiniteRowsSessionGate(context);
        var policy = gate.TryTake(manifest, at);
        Check(policy is not null && gate.Taken && gate.TryTake(Parse(Input()), at) is null,
            "first immutable manifest occupies the whole loaded host; second nonce/manifest cannot replace it");
        var invalidGate = new FiniteRowsSessionGate(context);
        Check(invalidGate.TryTake(manifest with { Session = "wrong" }, at) is null && invalidGate.Taken &&
            invalidGate.TryTake(manifest, at) is null, "failed binding consumes host admission; no corrected-file retry");
        var identity = new WindowsThreadIdentity(0,12,0,34,0,34,false)
        { WindowScanStatus="complete", WindowScanCount=1, WindowCandidates=new[]
            {new WindowsWindowDiagnostic(56,12,34,true,"UnityWndClass",true,0,true,true,10,10,0)} };
        var outer = policy!;
        var request = new FiniteRowsRequest(4,manifest.BatchId,manifest.PageEpoch,0,manifest.FirstNonce,outer.ApprovalSha256);
        var grant = outer.TryBegin(request,identity,at,0)!;
        var child = new DiscoveryPolicy(new(context,manifest.FirstNonce,0,TargetedDiscoveryCollector.FocusRoot,
            manifest.RequestedAt,manifest.ExpiresAt,true,grant.SelectionProfile),
            () => outer.CheckActive(grant,at,0), requiredWindow:grant.Window);
        var replacement = identity with { WindowCandidates = new[]
            {new WindowsWindowDiagnostic(57,12,34,true,"UnityWndClass",true,0,true,true,10,10,0)} };
        Check(child.TryBegin(new(3,manifest.FirstNonce,child.ApprovalSha256),replacement,at) is null,
            "fresh child admission cannot bind another HWND between outer and child scans");
        outer.Stop();
        Console.WriteLine("Finite configuration/session offline cases registered; no platform or game calls.");
    }
}
