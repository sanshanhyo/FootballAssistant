using FootballAssistant.GameBridge;
static void Check(bool value, string message) { if (!value) throw new Exception(message); }
var now = DateTimeOffset.UtcNow;
var context = new SmokeContext(12, "fixture-session-not-game", new string('a', 64), new string('b', 64), "FixtureOnlyClass", 34);
var candidate = new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureOnlyClass", true, 0, true, true, 200, 100, 0);
var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false)
    { WindowScanStatus = "complete", WindowScanCount = 1, WindowCandidates = new[] { candidate } };
SmokeRequest Request(SmokeStage stage) => new(Guid.NewGuid(), 12, context.Session, context.BridgeHash, context.GameHash,
    context.ConfirmedWindowClass, stage, now, now.AddSeconds(30));
var policy = new WindowsSmokePolicy(context);
Check(policy.SelectWindow(identity) == 56, "one matching fixture window");
foreach (var invalid in new[] { identity with { WindowScanStatus = "bounded" }, identity with { CurrentThreadId = 35 },
    identity with { WindowScanCount = 0 }, identity with { WindowCandidates = new[] { candidate with { OwnerStable = false } } },
    identity with { WindowCandidates = new[] { candidate with { ClassNameComplete = false } } },
    identity with { WindowCandidates = new[] { candidate with { VisibleStyle = false } } },
    identity with { WindowCandidates = new[] { candidate with { ClientWidth = 0 } } },
    identity with { WindowCandidates = new[] { candidate with { ClientRectAvailable = false } } },
    identity with { WindowScanCount = 2, WindowCandidates = new[] { candidate, candidate with { Hwnd = 57 } } } })
    Check(policy.SelectWindow(invalid) is null, "unknown/partial/multiple/wrong-thread windows rejected");
Check(policy.TryConsume(Request(SmokeStage.UiText), identity, now) is null, "no UI before metadata success");
var metadata = Request(SmokeStage.Metadata);
foreach (var invalid in new[] { metadata with { Pid = 13 }, metadata with { Session = "other" },
    metadata with { BridgeHash = context.GameHash }, metadata with { GameHash = context.BridgeHash },
    metadata with { ConfirmedWindowClass = "UnityWndClass" }, metadata with { Nonce = Guid.Empty },
    metadata with { CreatedAt = now.AddSeconds(1) }, metadata with { ExpiresAt = now },
    metadata with { ExpiresAt = now.AddSeconds(31) }, metadata with { Stage = (SmokeStage)99 } })
    Check(policy.TryConsume(invalid, identity, now) is null, "request identity/time/stage mismatch rejected");
var grant = policy.TryConsume(metadata, identity, now)!;
Check(grant is not null && policy.TryBeginCall(grant, identity, now), "metadata grant independently revalidates");
Check(!policy.TryBeginCall(grant!, identity, now), "same granted call cannot execute twice");
foreach (var expired in new[] { false, true })
{
    var p = new WindowsSmokePolicy(context);
    var g = p.TryConsume(Request(SmokeStage.Metadata), identity, now)!;
    var altered = identity with { WindowCandidates = new[] { candidate with { Hwnd = 99 } } };
    Check(!p.TryBeginCall(g, expired ? identity : altered, expired ? now.AddSeconds(30) : now), "expiry/rebuilt HWND invalidates grant");
    Check(!p.TryBeginCall(g, identity, now), "failed revalidation consumes grant permanently");
}
Check(policy.TryConsume(metadata, identity, now) is null, "nonce replay rejected");
policy.CompleteMetadata(grant!, true);
var ui = policy.TryConsume(Request(SmokeStage.UiText), identity, now);
Check(ui is not null, "distinct UI request only after metadata success");
Check(policy.TryConsume(Request(SmokeStage.UiText), identity, now) is null, "UI stage cannot retry even with a new nonce");
var failurePolicy = new WindowsSmokePolicy(context);
var failed = failurePolicy.TryConsume(Request(SmokeStage.Metadata), identity, now)!;
failurePolicy.CompleteMetadata(failed, false);
Check(failurePolicy.TryConsume(Request(SmokeStage.Metadata), identity, now) is null &&
    failurePolicy.TryConsume(Request(SmokeStage.UiText), identity, now) is null, "failed metadata consumes attempt and bars UI");
try { _ = new WindowsSmokePolicy(context with { ConfirmedWindowClass = "" }); throw new Exception("missing class accepted"); }
catch (ArgumentException) { }
var metadataPolicy = new WindowsSmokePolicy(context);
var nativeCalls = 0;
var summary = MetadataSmoke.Execute(metadataPolicy, Request(SmokeStage.Metadata), context.GameHash, () => identity, () => now,
    () => { nativeCalls++; return 123; }, _ => { nativeCalls++; return new AssemblySpan(456, 7); });
Check(summary == new MetadataSummary(true, 7) && nativeCalls == 2, "fake metadata uses only two bounded queries");
Check(MetadataSmoke.Execute(metadataPolicy, Request(SmokeStage.Metadata), context.GameHash, () => identity, () => now,
    () => throw new Exception("replayed native call"), _ => throw new Exception("replayed native call")) is null, "metadata has no repeat");
foreach (var badCount in new nuint[] { 0, 1025, nuint.MaxValue })
{
    var p = new WindowsSmokePolicy(context);
    var rejected = false;
    try { MetadataSmoke.Execute(p, Request(SmokeStage.Metadata), context.GameHash, () => identity, () => now,
        () => 123, _ => new AssemblySpan(456, badCount)); }
    catch (InvalidOperationException) { rejected = true; }
    Check(rejected && p.TryConsume(Request(SmokeStage.UiText), identity, now) is null, "invalid assembly count consumes metadata and bars UI");
}
foreach (var throws in new[] { false, true })
{
    var p = new WindowsSmokePolicy(context);
    var assemblyCalls = 0;
    var failedQuery = false;
    try
    {
        MetadataSmoke.Execute(p, Request(SmokeStage.Metadata), context.GameHash, () => identity, () => now,
            () => throws ? throw new InvalidOperationException("fixture native delegate failure") : 0,
            _ => { assemblyCalls++; return new AssemblySpan(456, 7); });
    }
    catch (InvalidOperationException) { failedQuery = true; }
    Check(failedQuery && assemblyCalls == 0 && p.TryConsume(Request(SmokeStage.Metadata), identity, now) is null,
        "null/throwing domain consumes attempt and prevents assemblies/retry");
}
var lostWindowPolicy = new WindowsSmokePolicy(context);
var identityCalls = 0;
var callsAfterDomain = 0;
try
{
    MetadataSmoke.Execute(lostWindowPolicy, Request(SmokeStage.Metadata), context.GameHash,
        () => ++identityCalls < 3 ? identity : identity with { WindowScanStatus = "failed" }, () => now,
        () => 123, _ => { callsAfterDomain++; return new AssemblySpan(456, 7); });
    throw new Exception("lost identity accepted");
}
catch (InvalidOperationException) { }
Check(callsAfterDomain == 0, "identity lost after domain prevents assemblies query");
Check(MetadataSmoke.Execute(new WindowsSmokePolicy(context), Request(SmokeStage.Metadata), context.BridgeHash,
    () => identity, () => now, () => throw new Exception("wrong hash called native"), _ => throw new Exception("wrong hash called native")) is null,
    "unapproved module hash cannot invoke native query");
using (var cancellation = new CancellationTokenSource())
{
    var p = new WindowsSmokePolicy(context);
    var assemblyCalls = 0;
    var cancelled = false;
    try
    {
        MetadataSmoke.Execute(p, Request(SmokeStage.Metadata), context.GameHash, () => identity, () => now,
            () => { cancellation.Cancel(); return 123; }, _ => { assemblyCalls++; return new AssemblySpan(456, 7); }, cancellation.Token);
    }
    catch (OperationCanceledException) { cancelled = true; }
    Check(cancelled && assemblyCalls == 0 && p.TryConsume(Request(SmokeStage.UiText), identity, now) is null,
        "stop after domain return prevents assemblies query and cannot enable UI");
}
var configRoot = Path.Combine(Path.GetTempPath(), "metadata-candidate-test-" + Guid.NewGuid());
Directory.CreateDirectory(configRoot);
try
{
    var dll = Path.Combine(configRoot, "FootballAssistant.WindowsMetadataCandidate.dll");
    var config = Path.Combine(configRoot, CandidateConfiguration.ConfigName);
    void RejectConfiguration(string json)
    {
        File.WriteAllText(config, json);
        var rejected = false;
        try { CandidateConfiguration.Read(dll); }
        catch (Exception error) when (error is InvalidOperationException or System.Text.Json.JsonException or KeyNotFoundException) { rejected = true; }
        Check(rejected, "experimental config fails closed");
    }
    RejectConfiguration("{}");
    RejectConfiguration("{\"schema_version\":1,\"schema_version\":1}");
    RejectConfiguration(new string('x', 4097));
    File.WriteAllText(config, System.Text.Json.JsonSerializer.Serialize(new
    {
        schema_version = 1, mode = "metadata_once", exe_path = Path.Combine(configRoot, "fm.exe"),
        game_path = Path.Combine(configRoot, "GameAssembly.dll"), volume_serial = 1, file_index = 2,
        window_class = "UnityWndClass", prelaunch_recorded_at = now.AddMinutes(-1)
    }));
    var parsed = CandidateConfiguration.Read(dll);
    Check(parsed.WindowClass == "UnityWndClass" && parsed.Module.FileIndex == 2 && parsed.RecordedAt < now,
        "candidate config requires explicit evidenced class and prelaunch identity");
    var requestPath = Path.Combine(configRoot, CandidateConfiguration.RequestName);
    var requestNonce = Guid.NewGuid();
    var fixture = new
    {
        schema_version = 1, stage = "metadata", nonce = requestNonce, pid = 12,
        session_id = context.Session, bridge_sha256 = context.BridgeHash, game_sha256 = context.GameHash,
        window_class = context.ConfirmedWindowClass, checkpoint = "stable_current_session_page",
        requested_at = now, expires_at = now.AddSeconds(30)
    };
    File.WriteAllText(requestPath, System.Text.Json.JsonSerializer.Serialize(fixture));
    Check(CandidateConfiguration.ReadRequest(requestPath).Nonce == requestNonce, "explicit metadata request parses");
    File.WriteAllText(requestPath, System.Text.Json.JsonSerializer.Serialize(fixture).Replace("\"stage\":\"metadata\"", "\"stage\":\"ui\""));
    var uiRejected = false;
    try { CandidateConfiguration.ReadRequest(requestPath); } catch (InvalidOperationException) { uiRejected = true; }
    Check(uiRejected, "no experimental host UI request mode exists");
}
finally { Directory.Delete(configRoot, true); }
Console.WriteLine("PASS draft policy/fake-metadata fixtures only; no real module verification, native calls, game fields or runtime wiring.");
