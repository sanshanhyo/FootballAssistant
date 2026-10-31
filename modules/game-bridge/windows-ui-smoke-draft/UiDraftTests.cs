using FootballAssistant.GameBridge;
static void Check(bool value, string message) { if (!value) throw new Exception(message); }
UiSmokeResult Read(FakeBackend backend, Action? guard = null, Func<double>? elapsed = null) =>
    WindowsSmokeReader.ReadOne(backend, guard ?? (() => { }), elapsed ?? (() => 0));
var backend = new FakeBackend();
var one = Read(backend);
Check(one.Text == "fixture text" && one.Nodes == 2 && backend.ChildReads == 1, "lazy first eligible text, no eager sibling reads");
backend = new FakeBackend { RootVisible = false };
Check(Read(backend).Text is null && backend.ChildReads == 0, "hidden ancestor prunes subtree");
backend = new FakeBackend { RootBoundsPositive = false };
Check(Read(backend).Text == "fixture text", "invalid parent bounds do not hide valid descendant");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 101).StopReason == "time_budget" && backend.Calls == 0, "initial resolution inside time budget");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 25.5497).Text == "fixture text", "observed first-capture elapsed no longer prematurely stops fixture");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 100).Text == "fixture text", "100ms boundary retains soft-budget semantics");
backend = new FakeBackend { ResolutionCalls = 400 };
Check(Read(backend).StopReason == "native_call_budget" && backend.Calls == 384, "resolution cannot escape native call budget");
backend = new FakeBackend();
var guardCalls = 0;
var stopped = Read(backend, () => { if (++guardCalls > 4) throw new UiSmokeStopped("window_changed"); });
Check(stopped.StopReason == "window_changed" && stopped.Text is null, "fresh identity failure stops before next native action");
backend = new FakeBackend { ExcessiveText = true };
var rejected = Read(backend);
Check(rejected.Text is null && rejected.StopReason == "backend_failure" && rejected.ErrorType == nameof(InvalidOperationException),
    "unbounded adapter text is rejected not silently accepted");
backend = new FakeBackend { NoText = true, Children = 100 };
var bounded = Read(backend);
Check(bounded.StopReason == "bounded_no_text" && backend.ChildReads == 8, "children cap is explicit incompleteness");
backend = new FakeBackend { EmptyText = true };
var empty = Read(backend);
Check(empty.Text is null && empty.TextGetterSucceeded && empty.RootResolved && empty.StopReason == "no_eligible_text",
    "successful empty getter is not a fabricated field or a native failure");
var now = DateTimeOffset.UtcNow;
var context = new SmokeContext(12, "ui-fixture", new string('a', 64), new string('b', 64), "FixtureWindow", 34);
var identity = new WindowsThreadIdentity(0, 12, 0, 34, 0, 34, false) { WindowScanStatus = "complete", WindowScanCount = 1,
    WindowCandidates = new[] { new WindowsWindowDiagnostic(56, 12, 34, true, "FixtureWindow", true, 0, true, true, 10, 10, 0) } };
SmokeRequest Request(SmokeStage stage) => new(Guid.NewGuid(), 12, context.Session, context.BridgeHash, context.GameHash,
    context.ConfirmedWindowClass, stage, now, now.AddSeconds(30));
var policy = new WindowsSmokePolicy(context);
var ambiguous = identity with { WindowScanCount = 2, WindowCandidates = new[] {
    identity.WindowCandidates![0], identity.WindowCandidates![0] with { Hwnd = 57, OwnerTid = 99 } } };
Check(policy.SelectWindow(ambiguous) is null, "second visible same-class positive window is ambiguous even on another thread");
backend = new FakeBackend();
Check(WindowsSmokeReader.TryReadAuthorized(policy, Request(SmokeStage.UiText), backend, () => identity, () => now) is null &&
    backend.Calls == 0, "UI cannot run before metadata succeeds");
var metadata = policy.TryConsume(Request(SmokeStage.Metadata), identity, now)!;
Check(policy.TryBeginCall(metadata, identity, now), "fixture metadata starts");
policy.CompleteMetadata(metadata, true);
Check(WindowsSmokeReader.TryReadAuthorized(policy, Request(SmokeStage.UiText), backend, () => identity, () => now) is null,
    "UI also requires separately authorized resolve success");
var resolve = policy.TryConsume(Request(SmokeStage.UiResolve), identity, now)!;
Check(policy.TryBeginCall(resolve, identity, now), "fixture resolve starts");
policy.CompleteResolve(resolve, true);
var authorized = WindowsSmokeReader.TryReadAuthorized(policy, Request(SmokeStage.UiText), backend, () => identity, () => now,
    elapsedForTest: () => 0);
Check(authorized?.Text == "fixture text", "separate UI grant permits only fake first-text fixture");
var previousCalls = backend.Calls;
Check(WindowsSmokeReader.TryReadAuthorized(policy, Request(SmokeStage.UiText), backend, () => identity, () => now) is null &&
    backend.Calls == previousCalls, "even another nonce cannot retry UI stage");
foreach (var invalidation in new[] { "failed", "expired", "window" })
{
    var p = new WindowsSmokePolicy(context);
    Check(p.TryConsume(Request(SmokeStage.UiResolve), identity, now) is null, "resolve cannot precede metadata");
    var m = p.TryConsume(Request(SmokeStage.Metadata), identity, now)!;
    Check(p.TryBeginCall(m, identity, now), "isolated metadata starts"); p.CompleteMetadata(m, true);
    var r = p.TryConsume(Request(SmokeStage.UiResolve), identity, now)!;
    if (invalidation == "failed") Check(p.TryBeginCall(r, identity, now), "isolated resolve starts");
    else Check(!p.TryBeginCall(r, invalidation == "window" ? identity with { WindowScanStatus = "incomplete" } : identity,
        invalidation == "expired" ? now.AddSeconds(31) : now), "consumed resolve cannot survive expiry/window loss");
    p.CompleteResolve(r, false);
    Check(p.TryConsume(Request(SmokeStage.UiResolve), identity, now) is null &&
        p.TryConsume(Request(SmokeStage.UiText), identity, now) is null, "failed resolve permits neither retry nor capture");
}
using (var nativeFixture = new NativeUiAdapterFixture())
{
    using var nativeBackend = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), nativeFixture.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(nativeBackend, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    Check(nativeFixture.Invocations.Count == 0 && nativeFixture.RootCreates == 0, "resolve-only warm-up calls no UI getter and creates no object roots");
    var actualPath = WindowsSmokeReader.ReadOne(nativeBackend, () => { }, () => 0);
    Check(actualPath.Text == "fixture-native-path" && actualPath.NativeOperations < 128 && actualPath.Nodes == 2,
        "actual thin adapter follows original getter path through fake exports and own memory");
    Check(nativeFixture.Invocations.Count(n => n == "get_text") == 1 &&
        nativeFixture.Invocations.All(n => new[] { "GetSortedPlayerPanels", "get_Count", "get_Item", "get_visualTree", "get_visible", "get_worldBound", "get_childCount", "get_text" }.Contains(n)),
        "only allowlisted getters and exactly one text getter invoked");
    Check(nativeFixture.LiveRoots > 0 && nativeFixture.RootCreates == nativeFixture.RootTargets,
        "each non-null runtime return rooted and exact target checked before later work");
    nativeBackend.Dispose();
    Check(nativeFixture.LiveRoots == 0 && nativeFixture.RootFrees == nativeFixture.RootCreates,
        "all temporary roots freed while fixture module remains alive");
}
using (var chain = new NativeUiAdapterFixture { TextDepth = 8 })
{
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), chain.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var deep = WindowsSmokeReader.ReadOne(b, () => { }, () => 0);
    Check(deep.Text == "fixture-native-path" && deep.Nodes == 9 && deep.NativeOperations > 128 && deep.NativeOperations <= 384,
        "one text at depth8 is reachable within384 reserved units, beyond old128 cap");
    Check(chain.RootCreates <= 64 && chain.Invocations.Count(n => n == "get_text") == 1,
        "depth8 still fits unchanged root cap and one text getter");
    b.Dispose();
    Check(chain.LiveRoots == 0 && chain.RootFrees == chain.RootCreates, "depth8 cleanup frees every temporary root");
    Console.WriteLine($"Depth8 fixture: reserved={deep.NativeOperations}, nodes={deep.Nodes}, roots={chain.RootCreates}; no game calls.");
}
foreach (var wrongBox in new[] { true, false })
{
    using var f = new NativeUiAdapterFixture { WrongBoxType = wrongBox, GetterThrows = !wrongBox };
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), f.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var outcome = WindowsSmokeReader.ReadOne(b, () => { }, () => 0);
    Check(outcome.Text is null && outcome.StopReason == "backend_failure" && !f.Invocations.Contains("get_text"),
        "wrong primitive box or getter exception stops before text access");
    b.Dispose();
    Check(f.LiveRoots == 0 && f.RootFrees == f.RootCreates, "exception path releases all created roots");
}
using (var f = new NativeUiAdapterFixture())
{
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), f.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var checkNumber = 0;
    var stoppedWithRoots = WindowsSmokeReader.ReadOne(b, () =>
    {
        if (f.RootCreates > 2 && ++checkNumber > 2) throw new UiSmokeStopped("time_budget");
    }, () => 0);
    Check(stoppedWithRoots.StopReason == "time_budget" && f.LiveRoots > 0, "budget can stop with temporary roots held");
    b.Dispose();
    Check(f.LiveRoots == 0 && f.RootFrees == f.RootCreates, "cleanup ignores exhausted sampling budget");
}
// Strict stage request parsing, without launching a host or using a game module.
var parserRoot = Path.Combine(Path.GetTempPath(), "football-ui-request-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(parserRoot);
try
{
    var path = Path.Combine(parserRoot, UiCandidateConfiguration.RequestName);
    foreach (var (name, stage) in new[] { ("metadata", SmokeStage.Metadata), ("ui_resolve", SmokeStage.UiResolve), ("ui_text", SmokeStage.UiText) })
    {
        var fixture = new { schema_version = 1, stage = name, nonce = Guid.NewGuid(), pid = 10,
            session_id = "fixture", bridge_sha256 = new string('a',64), game_sha256 = new string('b',64),
            window_class = "UnityWndClass", checkpoint = "stable_current_session_page", requested_at = now, expires_at = now.AddSeconds(30) };
        var json = System.Text.Json.JsonSerializer.Serialize(fixture);
        File.WriteAllText(path, json);
        Check(UiCandidateConfiguration.ReadRequest(path).Stage == stage, "only explicit supported stage parses");
        File.WriteAllText(path, json.Replace("stable_current_session_page", "past_main_menu"));
        var parserRejected = false;
        try { UiCandidateConfiguration.ReadRequest(path); } catch (InvalidOperationException) { parserRejected = true; }
        Check(parserRejected, "old page checkpoint parserRejected");
        File.WriteAllText(path, json[..^1] + ",\"stage\":\"ui_text\"}");
        parserRejected = false;
        try { UiCandidateConfiguration.ReadRequest(path); } catch (InvalidOperationException) { parserRejected = true; }
        Check(parserRejected, "duplicate stage parserRejected");
    }
}
finally { Directory.Delete(parserRoot, true); }
Console.WriteLine("PASS UI traversal fake fixtures only. Actual adapter exercised with fake exports/own fixture memory only; no real IL2CPP calls or host activation.");

sealed class FakeBackend : IWindowsUiSmokeBackend
{
    public string VerifiedModuleHash => new('b', 64);
    public void Dispose() { }
    public bool RootVisible = true, RootBoundsPositive = true, ExcessiveText, NoText, EmptyText;
    public int ResolutionCalls = 1, Calls, ChildReads, Children = 8;
    private void Touch(UiSmokeBudget budget) { budget.BeforeNative(); Calls++; }
    public nint ResolveFirstPanelRoot(UiSmokeBudget budget)
    { for (var i = 0; i < ResolutionCalls; i++) Touch(budget); return 1; }
    public bool Visible(nint element, UiSmokeBudget budget) { Touch(budget); return element != 1 || RootVisible; }
    public UiSmokeBounds Bounds(nint element, UiSmokeBudget budget)
    { Touch(budget); return new(0, 0, element != 1 || RootBoundsPositive ? 10 : 0, 10); }
    public bool IsTextElement(nint element, UiSmokeBudget budget) { Touch(budget); return element != 1 && !NoText; }
    public string ReadText(nint element, int maximumCodeUnits, UiSmokeBudget budget)
    { Touch(budget); return EmptyText ? "" : ExcessiveText ? new string('x', 129) : "fixture text"; }
    public int ChildCount(nint element, UiSmokeBudget budget) { Touch(budget); return element == 1 ? Children : 0; }
    public nint Child(nint element, int index, UiSmokeBudget budget) { Touch(budget); ChildReads++; return index + 2; }
}
