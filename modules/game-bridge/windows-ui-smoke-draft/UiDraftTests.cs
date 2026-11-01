using FootballAssistant.GameBridge;
static void Check(bool value, string message) { if (!value) throw new Exception(message); }
UiSmokeResult Read(FakeBackend backend, Action? guard = null, Func<double>? elapsed = null) =>
    WindowsSmokeReader.ReadOne(backend, guard ?? (() => { }), elapsed ?? (() => 0));
// Deterministic diagnostic accounting; no native calls, real wall-clock assertions or data capture.
var diagnosticClock = 0.0;
var failGuard = false;
var diagnosticBudget = new UiSmokeBudget(() => diagnosticClock, () =>
{
    diagnosticClock += failGuard ? 4 : 2;
    if (failGuard) throw new UiSmokeStopped("fixture_guard_failure");
});
diagnosticBudget.Check(); // setup [0, 2], completed guard 2ms
diagnosticClock = 5;
diagnosticBudget.Stage = "first_panel_root";
diagnosticBudget.BeforeNative(); // first-panel [5, 7], completed guard 2ms
diagnosticClock = 10;
diagnosticBudget.Stage = "visible";
failGuard = true;
try { diagnosticBudget.BeforeNative(); } catch (UiSmokeStopped) { }
var diagnostic = diagnosticBudget.Snapshot();
var setupTiming = diagnostic.Stages.Single(x => x.Stage == "before_resolution");
var panelTiming = diagnostic.Stages.Single(x => x.Stage == "first_panel_root");
var visibleTiming = diagnostic.Stages.Single(x => x.Stage == "visible");
Check(diagnostic.SchemaVersion == 1 && diagnostic.Stages.Length == 12 && diagnostic.ElapsedMs == 14 &&
    diagnostic.Stages.Sum(x => x.TotalMs) == 14, "fixed stage totals cover elapsed resolution and traversal without gaps");
Check(setupTiming.TotalMs == 5 && panelTiming.TotalMs == 5 && visibleTiming.TotalMs == 4 && visibleTiming.MaxMs == 4,
    "contiguous stage timing includes work between prechecks");
Check(diagnostic.Stages.Sum(x => x.GuardTotalMs) == 8 && visibleTiming.GuardMaxMs == 4 &&
    visibleTiming.GuardCalls == 1 && visibleTiming.GuardFailures == 1 && visibleTiming.PrechecksFailed == 1 &&
    diagnostic.Stages.Sum(x => x.PrechecksCompleted) == 2 && diagnosticBudget.Operations == 1,
    "failed guard duration counted but failed reservation not charged as completed");
Check(diagnosticBudget.Snapshot().Stages.Sum(x => x.TotalMs) == 14, "snapshots never double-count final interval");
diagnosticClock = 251;
try { diagnosticBudget.BeforeNative(); } catch (UiSmokeStopped diagnosticStopped) { Check(diagnosticStopped.Message == "time_budget", "original stop reason retained"); }
var deadlineTiming = diagnosticBudget.Snapshot().Stages.Single(x => x.Stage == "visible");
Check(deadlineTiming.PrechecksFailed == 2 && deadlineTiming.GuardCalls == 1 && diagnosticBudget.Operations == 1,
    "failed deadline precheck is distinct from a guard call and reserves nothing");
diagnosticClock = 252;
diagnosticBudget.Stage = "fixture-secret-text-or-path";
var boundedJson = System.Text.Json.JsonSerializer.Serialize(diagnosticBudget.Snapshot());
Check(!boundedJson.Contains("fixture-secret-text-or-path") && boundedJson.Length < 6000 &&
    diagnosticBudget.Stage == "unknown", "diagnostics contain only fixed labels and bounded numeric aggregates");
var clockReads = 0;
var overheadBudget = new UiSmokeBudget(() => ++clockReads, () => { }, 3);
overheadBudget.BeforeNative();
try { overheadBudget.BeforeNative(); } catch (UiSmokeStopped diagnosticStopped) { Check(diagnosticStopped.Message == "time_budget", "instrumentation does not subtract elapsed cost"); }
Check(overheadBudget.Operations == 1, "diagnostic timestamp reads consume the same elapsed budget");
var deniedGuardCalls = 0;
var callLimitBudget = new UiSmokeBudget(() => 0, () => deniedGuardCalls++, maximumOperations: 0);
try { callLimitBudget.BeforeNative(); } catch (UiSmokeStopped diagnosticStopped) { Check(diagnosticStopped.Message == "native_call_budget", "call-budget stop unchanged"); }
var callLimitTiming = callLimitBudget.Snapshot().Stages[0];
Check(callLimitTiming.PrechecksFailed == 1 && callLimitTiming.GuardCalls == 0 && deniedGuardCalls == 0 &&
    callLimitBudget.Operations == 0, "call-limit precheck failure invokes neither guard nor native work");
var repeatedClock = 0.0;
var repeatedBudget = new UiSmokeBudget(() => repeatedClock, () => { });
repeatedBudget.Stage = "visible"; repeatedClock = 3; repeatedBudget.Stage = "text_type";
repeatedClock = 5; repeatedBudget.Stage = "visible"; repeatedClock = 9;
var repeated = repeatedBudget.Snapshot().Stages.Single(x => x.Stage == "visible");
Check(repeated.Intervals == 2 && repeated.TotalMs == 7 && repeated.MaxMs == 4,
    "repeated stage total and longest contiguous interval are distinct");
var backend = new FakeBackend();
var one = Read(backend);
Check(one.Diagnostics is { Stages.Length: 12 } && one.Diagnostics.ElapsedMs == one.ElapsedMs, "capture result carries bounded diagnostics at the same endpoint");
Check(one.Text == "fixture text" && one.Nodes == 2 && backend.ChildReads == 1, "lazy first eligible text, no eager sibling reads");
Check(backend.BoundsReads == 1, "non-text root skips bounds; eligible text still checks bounds");
backend = new FakeBackend { TextBoundsPositive = false };
Check(Read(backend).Text is null && backend.TextReads == 0 && backend.BoundsReads == 8,
    "text nodes with invalid bounds never invoke text getter");
backend = new FakeBackend { RootVisible = false };
Check(Read(backend).Text is null && backend.ChildReads == 0, "hidden ancestor prunes subtree");
Check(backend.BoundsReads == 0 && backend.TypeReads == 0, "hidden ancestor is pruned before type and bounds");
backend = new FakeBackend { RootBoundsPositive = false, RootIsText = true };
Check(Read(backend).Text == "fixture text", "invalid parent bounds do not hide valid descendant");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 250.001).StopReason == "time_budget" && backend.Calls == 0, "initial resolution rejects elapsed above the 250ms soft budget");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 25.5497).Text == "fixture text", "observed first-capture elapsed no longer prematurely stops fixture");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 250).Text == "fixture text", "250ms boundary retains soft-budget semantics");
backend = new FakeBackend();
Check(Read(backend, elapsed: () => 100.4476).Text == "fixture text", "previous observed elapsed is within the authorized 250ms experiment");
backend = new FakeBackend { ResolutionCalls = 400 };
Check(Read(backend, elapsed: () => 200).StopReason == "native_call_budget" && backend.Calls == 384,
    "unchanged 384-unit cap stops work even while within the new time budget");
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
// Scan-only policy input intentionally omits legacy MainWindowHandle diagnostics.
// The shared native collector is unchanged; these fixtures prove policy decisions use
// only fresh scan/PID/TID evidence, never the omitted diagnostic fields.
WindowsThreadIdentity ScanOnly(WindowsThreadIdentity source) => source with
    { Window = 0, OwnerProcessId = 0, OwnerThreadId = 0, ExplicitWindow = false };
var explicitIdentity = identity with { Window = 56, OwnerProcessId = 12, OwnerThreadId = 34, ExplicitWindow = true };
Check(explicitIdentity.Matches() && !ScanOnly(explicitIdentity).Matches(),
    "scan-only identity cannot authorize the legacy explicit-window path");
var candidate = identity.WindowCandidates![0];
WindowsThreadIdentity Row(WindowsWindowDiagnostic row) => explicitIdentity with { WindowCandidates = new[] { row } };
var scanCases = new[]
{
    explicitIdentity,
    explicitIdentity with { ProcessId = 99 },
    explicitIdentity with { CurrentThreadId = 99 },
    explicitIdentity with { InstallerThreadId = 99 },
    explicitIdentity with { CurrentThreadId = 0, InstallerThreadId = 0 },
    explicitIdentity with { WindowScanStatus = "failed" },
    explicitIdentity with { WindowScanStatus = "bounded" },
    explicitIdentity with { WindowScanStatus = "callback_failed" },
    explicitIdentity with { WindowCandidates = null },
    explicitIdentity with { WindowCandidates = Array.Empty<WindowsWindowDiagnostic>(), WindowScanCount = 0 },
    explicitIdentity with { WindowScanCount = 2 },
    explicitIdentity with { WindowCandidates = Enumerable.Repeat(candidate, 33).ToArray(), WindowScanCount = 33 },
    explicitIdentity with { WindowCandidates = new[] { candidate, candidate }, WindowScanCount = 2 },
    explicitIdentity with { WindowCandidates = new[] { candidate, candidate with { Hwnd = 57, OwnerTid = 99 } }, WindowScanCount = 2 },
    Row(candidate with { Hwnd = 0 }),
    Row(candidate with { OwnerPid = 99 }),
    Row(candidate with { OwnerTid = 99 }),
    Row(candidate with { OwnerStable = false }),
    Row(candidate with { ClassName = "OtherWindow" }),
    Row(candidate with { ClassName = null, ClassNameComplete = false }),
    Row(candidate with { ClassNameComplete = false }),
    Row(candidate with { VisibleStyle = false }),
    Row(candidate with { ClientRectAvailable = false }),
    Row(candidate with { ClientWidth = 0 }),
    Row(candidate with { ClientHeight = -1 }),
    Row(candidate with { ClientWidth = null }),
    explicitIdentity with { WindowCandidates = new[] { candidate, candidate with { Hwnd = 57, ClassName = "OtherWindow", ClassNameComplete = false } }, WindowScanCount = 2 }
};
var scanPolicy = new WindowsSmokePolicy(context);
for (var scanIndex = 0; scanIndex < scanCases.Length; scanIndex++)
{
    var diagnosticDecision = scanPolicy.SelectWindow(scanCases[scanIndex]);
    Check(diagnosticDecision == scanPolicy.SelectWindow(ScanOnly(scanCases[scanIndex])),
        "diagnostic and scan-only policy decisions remain identical: " + scanIndex);
    Check(scanIndex == 0 ? diagnosticDecision == 56 : diagnosticDecision is null,
        "all incomplete, ambiguous, stale-owner, shape and thread failures remain denied: " + scanIndex);
}
(UiSmokeResult? Result, int IdentityReads) CaptureIdentityVariant(bool scanOnly)
{
    var p = new WindowsSmokePolicy(context);
    var m = p.TryConsume(Request(SmokeStage.Metadata), explicitIdentity, now)!;
    Check(p.TryBeginCall(m, explicitIdentity, now), "identity variant metadata starts"); p.CompleteMetadata(m, true);
    var r = p.TryConsume(Request(SmokeStage.UiResolve), explicitIdentity, now)!;
    Check(p.TryBeginCall(r, explicitIdentity, now), "identity variant resolve starts"); p.CompleteResolve(r, true);
    var identityReads = 0;
    var result = WindowsSmokeReader.TryReadAuthorized(p, Request(SmokeStage.UiText), new FakeBackend(),
        () => { identityReads++; return scanOnly ? ScanOnly(explicitIdentity) : explicitIdentity; }, () => now, elapsedForTest: () => 0);
    return (result, identityReads);
}
var diagnosticCapture = CaptureIdentityVariant(false);
var scanCapture = CaptureIdentityVariant(true);
Check(diagnosticCapture.Result is not null && scanCapture.Result is not null &&
    diagnosticCapture.Result.Text == scanCapture.Result.Text && diagnosticCapture.Result.StopReason == scanCapture.Result.StopReason &&
    diagnosticCapture.Result.Nodes == scanCapture.Result.Nodes && diagnosticCapture.Result.NativeOperations == scanCapture.Result.NativeOperations &&
    diagnosticCapture.IdentityReads == scanCapture.IdentityReads && scanCapture.IdentityReads > scanCapture.Result.NativeOperations,
    "scan-only identity preserves capture outcome and every fresh guard/consume/begin check");
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
    Check(nativeFixture.Invocations.Count(n => n == "get_worldBound") == 1,
        "actual adapter skips non-text container bounds and still validates text bounds");
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
// Coverage is observational: exactly the pre-existing 9 reservations / 13 fresh
// guard checks for this two-node fixture, including the successful text getter.
var coverageGuardChecks = 0;
var coveragePair = Read(new FakeBackend(), () => coverageGuardChecks++);
Check(coveragePair.NativeOperations == 9 && coverageGuardChecks == 13 &&
    coveragePair.Coverage is { NodesRecorded: 2, Nodes.Length: 32, PanelCount: -1, SelectedPanelIndex: -1 },
    "coverage adds no native reservations or fresh guard calls; fake backend leaves unread panel count unknown");
var coverageJson = System.Text.Json.JsonSerializer.Serialize(coveragePair.Coverage);
Check(!coverageJson.Contains("fixture text") && coverageJson.Length < 6000,
    "coverage output is bounded and contains no captured text");
var beforeRoot = Read(new FakeBackend(), elapsed: () => 251);
Check(beforeRoot.Coverage is { PanelCount: -1, SelectedPanelIndex: -1, NodesRecorded: 0 } &&
    beforeRoot.Coverage.Nodes.All(n => n.Depth == -1 && n.Visibility == 0 && n.TextType == 0),
    "pre-resolution stop uses unknown sentinels, never fabricated empty panels or completed checks");
var partialChecks = 0;
var partialVisible = Read(new FakeBackend(), () =>
{
    if (++partialChecks == 4) throw new UiSmokeStopped("fixture_stop");
});
Check(partialVisible.StoppedStage == "visible" && partialVisible.Coverage is { NodesRecorded: 1 } &&
    partialVisible.Coverage.Nodes[0] is { Depth: 0, Visibility: 1, TextType: 0, ChildCountState: 0, ChildCountBucket: -1 },
    "partial visible check is incomplete, not false; downstream checks remain not started");
var partialTypeChecks = 0;
var partialType = Read(new FakeBackend(), () =>
{
    if (++partialTypeChecks == 5) throw new UiSmokeStopped("fixture_stop");
});
Check(partialType.Coverage!.Nodes[0] is { Visibility: 3, TextType: 1, ChildCountBucket: -1 },
    "partial type classification is incomplete, not non-text");
using (var derived = new NativeUiAdapterFixture { DerivedText = true })
{
    Check(derived.il2cpp_class_is_assignable_from(22, 34) && !derived.il2cpp_class_is_assignable_from(34, 22),
        "derived-label fixture relation is asymmetric");
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), derived.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var outcome = WindowsSmokeReader.ReadOne(b, () => { }, () => 0);
    Check(outcome.Text == "fixture-native-path" && outcome.Nodes == 2 && outcome.Coverage!.Nodes[1].TextType == 3,
        "base-first IsAssignableFrom accepts derived label (reversing arguments must fail this assertion)");
}
using (var secondPanel = new NativeUiAdapterFixture { PanelCount = 2, TextOnlyInSecondPanel = true })
{
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), secondPanel.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var outcome = WindowsSmokeReader.ReadOne(b, () => { }, () => 0);
    Check(outcome.Text is null && outcome.StopReason == "no_eligible_text" && outcome.Nodes == 1 &&
        outcome.Coverage is { PanelCount: 2, SelectedPanelIndex: 0 } &&
        secondPanel.PanelIndices.SequenceEqual(new[] { 0 }) && !secondPanel.Invocations.Contains("get_text"),
        "existing first-panel policy cannot reach text only in panel 1; diagnostics never expand selection");
}
using (var stoppedPanel = new NativeUiAdapterFixture { PanelCount = 2 })
{
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), stoppedPanel.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var checksAfterUnbox = 0;
    var outcome = WindowsSmokeReader.ReadOne(b, () =>
    {
        // First check reads the count payload; the second would inspect the list for Item(0).
        if (stoppedPanel.PanelCountUnboxes > 0 && ++checksAfterUnbox == 2) throw new UiSmokeStopped("fixture_stop");
    }, () => 0);
    Check(outcome.Coverage is { PanelCount: 2, SelectedPanelIndex: 0, NodesRecorded: 0 } &&
        !outcome.RootResolved && stoppedPanel.PanelIndices.Count == 0,
        "validated count records planned panel0 even when item/root access never completes");
}
foreach (var panelCount in new[] { -1, 0, 1025 })
{
    using var fixture = new NativeUiAdapterFixture { PanelCount = panelCount };
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), fixture.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var outcome = WindowsSmokeReader.ReadOne(b, () => { }, () => 0);
    Check(outcome.Coverage!.PanelCount == (panelCount == 0 ? 0 : -1) && outcome.Coverage.SelectedPanelIndex == -1 &&
        fixture.PanelIndices.Count == 0, "only validated panel counts are recorded; zero differs from unknown/invalid");
}
using (var tooDeep = new NativeUiAdapterFixture { TextDepth = 9 })
{
    using var b = WindowsLoadedModuleLease.CreateUiTestBackend(new string('b', 64), tooDeep.Bind);
    WindowsLoadedModuleLease.PrepareUiTestBackend(b, new UiSmokeBudget(() => 0, () => { }, 250, 2048));
    var outcome = WindowsSmokeReader.ReadOne(b, () => { }, () => 0);
    Check(outcome.Text is null && outcome.StopReason == "bounded_no_text" && outcome.Nodes == 9 &&
        outcome.Coverage!.Nodes[8] is { Depth: 8, TextType: 2, ChildCountBucket: 1, DepthPruned: 1 } &&
        !tooDeep.Invocations.Contains("get_text"), "depth9 text stays unreachable with unchanged depth8 limit");
}
var ninthChild = new FakeBackend { Children = 9, OnlyTextChildIndex = 8 };
var tooWide = Read(ninthChild);
Check(tooWide.Text is null && tooWide.StopReason == "bounded_no_text" && ninthChild.ChildReads == 8 &&
    ninthChild.TextReads == 0 && tooWide.Coverage!.Nodes[0] is { ChildCountBucket: 9, ChildrenTruncated: 1 },
    "text at child index8 stays unreachable with unchanged first8-child limit");
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
    public bool RootVisible = true, RootBoundsPositive = true, TextBoundsPositive = true, RootIsText, ExcessiveText, NoText, EmptyText;
    public int OnlyTextChildIndex = -1;
    public int ResolutionCalls = 1, Calls, ChildReads, BoundsReads, TypeReads, TextReads, Children = 8;
    private void Touch(UiSmokeBudget budget) { budget.BeforeNative(); Calls++; }
    public nint ResolveFirstPanelRoot(UiSmokeBudget budget)
    { for (var i = 0; i < ResolutionCalls; i++) Touch(budget); return 1; }
    public bool Visible(nint element, UiSmokeBudget budget) { Touch(budget); return element != 1 || RootVisible; }
    public UiSmokeBounds Bounds(nint element, UiSmokeBudget budget)
    { Touch(budget); BoundsReads++; return new(0, 0, (element == 1 ? RootBoundsPositive : TextBoundsPositive) ? 10 : 0, 10); }
    public bool IsTextElement(nint element, UiSmokeBudget budget) { Touch(budget); TypeReads++; return ((element != 1 && (OnlyTextChildIndex < 0 || element == OnlyTextChildIndex + 2)) || (element == 1 && RootIsText)) && !NoText; }
    public string ReadText(nint element, int maximumCodeUnits, UiSmokeBudget budget)
    { Touch(budget); TextReads++; return EmptyText ? "" : ExcessiveText ? new string('x', 129) : "fixture text"; }
    public int ChildCount(nint element, UiSmokeBudget budget) { Touch(budget); return element == 1 ? Children : 0; }
    public nint Child(nint element, int index, UiSmokeBudget budget) { Touch(budget); ChildReads++; return index + 2; }
}
