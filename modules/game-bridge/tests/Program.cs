using System.Net;
using System.Text.Json;
using System.Text;
using System.Runtime.InteropServices;
using System.Net.Sockets;
using FootballAssistant.GameBridge;

NativePacketClient.ValidateManagedLayouts();
var completePacket = new NativePacketManifest { Version = 1, StructSize = 112, State = 4, Flags = 7,
    OriginalKeysCount = 2, OriginalPayloadCount = 64, CopiedKeysBytes = 16, CopiedPayloadBytes = 64 };
Assert(NativePacketClient.IsComplete(completePacket), "packet requires exact complete bounded byte copies");
var shortPacket = completePacket; shortPacket.CopiedPayloadBytes--;
Assert(!NativePacketClient.IsComplete(shortPacket), "short copied payload never becomes complete");
var unknownPacket = completePacket; unknownPacket.Flags = 3;
Assert(!NativePacketClient.IsComplete(unknownPacket), "packet original result remains explicitly unknown");
var oversizedPacket = completePacket; oversizedPacket.OriginalKeysCount = ulong.MaxValue;
Assert(!NativePacketClient.IsComplete(oversizedPacket), "packet count overflow rejected before multiplication");
var requestWindow = new Dictionary<Guid, DateTimeOffset>();
var requestNow = DateTimeOffset.UtcNow;
var requestA = Guid.NewGuid(); var requestB = Guid.NewGuid();
Assert(NativePacketClient.TryConsumeRequest(requestWindow, requestA, requestNow, requestNow), "first packet control nonce accepted");
Assert(NativePacketClient.TryConsumeRequest(requestWindow, requestB, requestNow, requestNow), "different packet control nonce accepted");
Assert(!NativePacketClient.TryConsumeRequest(requestWindow, Guid.Parse(requestA.ToString("B").ToUpperInvariant()), requestNow, requestNow.AddSeconds(1)), "A-B-A replay and alternate UUID spelling rejected");
Assert(!NativePacketClient.TryConsumeRequest(requestWindow, Guid.NewGuid(), requestNow.AddSeconds(-31), requestNow), "expired packet control rejected");
Assert(!NativePacketClient.TryConsumeRequest(requestWindow, Guid.NewGuid(), requestNow.AddSeconds(1), requestNow), "future packet control rejected");
using (var unknownPacketStatus = JsonDocument.Parse(JsonSerializer.Serialize(NativePacketClient.Describe(new NativePacketManifest { Version = 1, StructSize = 112, State = 1 }))))
{
    foreach (var field in new[] { "call_sequence", "monotonic_ns", "native_thread_id", "original_keys_count", "original_payload_count", "copied_keys_bytes", "copied_payload_bytes" })
        Assert(unknownPacketStatus.RootElement.GetProperty(field).ValueKind == JsonValueKind.Null, "pending packet " + field + " remains unknown");
    Assert(unknownPacketStatus.RootElement.GetProperty("checked_packets").GetString() == "0", "known zero checked counter retained");
    Assert(unknownPacketStatus.RootElement.GetProperty("skipped_packets").GetString() == "0", "known zero skipped counter retained");
}
var immutableTemp = Path.Combine(Path.GetTempPath(), "footballassistant-evidence-test-" + Guid.NewGuid());
Directory.CreateDirectory(immutableTemp);
try
{
    var evidencePath = Path.Combine(immutableTemp, "packet.bin");
    NativePacketClient.WriteImmutableBytes(evidencePath, new byte[] { 1, 2, 3 });
    NativePacketClient.WriteImmutableBytes(evidencePath, new byte[] { 1, 2, 3 });
    try { NativePacketClient.WriteImmutableBytes(evidencePath, new byte[] { 4, 5, 6 }); throw new Exception("Changed packet evidence was accepted"); }
    catch (IOException) { }
    Assert(File.ReadAllBytes(evidencePath).SequenceEqual(new byte[] { 1, 2, 3 }), "packet evidence never overwritten by another copy");
}
finally { Directory.Delete(immutableTemp, true); }
if (args.Length == 3 && args[0] == "--native-packet-abi-smoke")
{
    var packetTemp = Path.Combine(Path.GetTempPath(), "footballassistant-packet-abi-" + Guid.NewGuid());
    Directory.CreateDirectory(Path.Combine(packetTemp, "native-observer"));
    Directory.CreateDirectory(Path.Combine(packetTemp, "diagnostics"));
    File.Copy(args[1], Path.Combine(packetTemp, "native-observer", "libfootballassistant_native_observer.dylib"));
    var packet = new NativePacketClient(packetTemp, args[2], _ => { });
    packet.Tick(Guid.NewGuid().ToString(), new string('a', 64), false);
    using var packetStatus = JsonDocument.Parse(File.ReadAllText(Path.Combine(packetTemp, "diagnostics", "native-packet-status.json")));
    Assert(packetStatus.RootElement.GetProperty("manifest_result").GetInt32() == 0, "actual packet ABI allows querying its idle slot");
    Assert(packetStatus.RootElement.GetProperty("active_capture_id").GetString() == "0", "ABI smoke neither arms nor installs a hook");
    Assert(packetStatus.RootElement.GetProperty("native").GetProperty("state").GetUInt32() == 0, "unarmed packet slot remains idle");
    Assert(packetStatus.RootElement.GetProperty("native").GetProperty("capture_id").GetString() == "0", "unarmed native capture ID remains zero");
    Console.WriteLine("PASS: actual packet ABI1 request48/manifest112, no capture, no hook, no game call.");
    return;
}

NativeObserverClient.ValidateManagedLayouts();
if (args.Length == 2 && args[0] == "--native-abi-smoke")
{
    var nativeTemp = Path.Combine(Path.GetTempPath(), "footballassistant-native-abi-" + Guid.NewGuid());
    Directory.CreateDirectory(Path.Combine(nativeTemp, "native-observer"));
    File.Copy(args[1], Path.Combine(nativeTemp, "native-observer", "libfootballassistant_native_observer.dylib"));
    var native = new NativeObserverClient(nativeTemp, _ => { });
    using var snapshot = JsonDocument.Parse(JsonSerializer.Serialize(native.DrainSnapshot()));
    Assert(snapshot.RootElement.GetProperty("abi_version").GetUInt32() == 1, "actual reviewed native ABI loads");
    Assert(snapshot.RootElement.GetProperty("install_state").GetUInt32() == 0, "ABI smoke never installs a hook");
    Assert(!snapshot.RootElement.GetProperty("capture_enabled").GetBoolean(), "ABI smoke capture remains off");
    Assert(snapshot.RootElement.GetProperty("invocation_count").GetUInt64() == 0, "ABI smoke has no game calls");
    Console.WriteLine("PASS: actual reviewed native library C# ABI/stats smoke; no install, Dobby or game call.");
}
Assert(NativeObserverClient.DescribeHeader(new NativeObserverRecord(), 0).keys_count is null, "unknown native header count is not zero");
Assert(NativeObserverClient.DescribeHeader(new NativeObserverRecord { Flags = 3 }, 0).keys_count == 0, "known native header zero retained");
Assert(NativeObserverClient.DescribeHeader(new NativeObserverRecord { MonotonicNs = 2 }, 1).age_seconds is null, "incompatible/backwards monotonic time is not fabricated");
if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
{
    Assert(MainThreadGuard.IsCurrent(), "OS main-thread gate");
    Assert(!Task.Run(MainThreadGuard.IsCurrent).GetAwaiter().GetResult(), "worker thread rejected before UI access");
    var mainLoopTicks = 0;
    using (var scheduler = new MacMainThreadTimer(() => { Assert(MainThreadGuard.IsCurrent(), "CF callback is on OS main thread"); mainLoopTicks++; }, 0.01))
        MacMainThreadTimer.RunLoopForTest(0.1);
    Assert(mainLoopTicks > 0, "CoreFoundation main-runloop callbacks fire without Unity wrappers");
    var stoppedAt = mainLoopTicks;
    MacMainThreadTimer.RunLoopForTest(0.03);
    Assert(mainLoopTicks == stoppedAt, "disposed CF timer has no subsequent callbacks");
}
var countOnly = InspectionPublisher.CountsOnlyProbe(new RegistryDiagnostic("PropertyIdentifierSet", "available", "Offline shape fixture only", id_count: 123, name_hash_count: 123), "offline-epoch", "offline-session");
using (var probe = JsonDocument.Parse(JsonSerializer.Serialize(countOnly)))
{
    Assert(probe.RootElement.GetProperty("enumeration").GetProperty("observed_unique_entries").GetInt32() == 0, "dictionary count is not per-entry coverage");
    Assert(!probe.RootElement.GetProperty("enumeration").GetProperty("complete").GetBoolean(), "count-only diagnostics never claim enumeration complete");
    Assert(probe.RootElement.GetProperty("entries").GetArrayLength() == 0, "no fabricated business entries");
}
var chinese = ObservationFactory.Create(Enumerable.Range(0, 240).Select(i => new UiText($"panel0/{i}", new string('球', 1000))).ToArray(), "27.0.0.2486716", "byte-budget-test");
Assert(Encoding.UTF8.GetByteCount(chinese) <= ObservationFactory.MaximumPayloadBytes, "maximum Chinese page fits backend body cap");
using (var page = JsonDocument.Parse(chinese))
    Assert(page.RootElement.GetProperty("payload").GetProperty("facts").GetArrayLength() is > 0 and < 240, "page reduced to byte budget");

// TEST-only generic paths, never a hardcoded game/page selection.
foreach (var invalidFocus in new[] { "", " ", "panel", "panel00", "Panel0", "panel32", "panel-1", "panel0/", "panel0//1", "panel0/00", "panel0/512", "panel0/-1", "panel0/1x", "panel0/1\n", "panel0/" + new string('1', 123) })
    Assert(!UiFocusPath.TryParse(invalidFocus, out _), "invalid focus grammar fails closed");
Assert(UiFocusPath.TryParse("panel31/511", out _), "bounded panel/child endpoints accepted");
Assert(UiFocusPath.TryParse("panel0/0/1", out var focusTest), "literal focus path parsed");
var focusVisits = 0;
var focusCalls = 0;
Assert(focusTest!.TryResolve(1, () => null, _ => true, _ => 2,
    (node, index) => { focusCalls++; return node * 10 + index + 1; }, () => focusVisits++,
    out var focusRoot, out var focusReason) && focusRoot == 112, "focus resolves only selected child path");
Assert(focusVisits == 2 && focusCalls == 2 && focusReason == "complete", "descent ancestors charged to shared node budget");
Assert(UiFocusPath.TryParse("panel0/0/0/0", out var longFocusTest), "bounded descent fixture");
focusVisits = focusCalls = 0;
Assert(!longFocusTest!.TryResolve(1, () => focusVisits >= 2 ? "node_limit" : null, _ => true, _ => 1,
    (node, index) => { focusCalls++; return node + 1; }, () => focusVisits++,
    out focusRoot, out focusReason) && focusReason == "node_limit" && focusRoot == 0, "descent node budget never falls back to original root");
Assert(focusVisits == 2 && focusCalls == 1, "no child getter after node budget exhausted");
var focusTimeExpired = false;
focusCalls = 0;
Assert(!focusTest.TryResolve(1, () => focusTimeExpired ? "time_budget" : null, _ => true,
    _ => { focusTimeExpired = true; return 2; }, (node, index) => { focusCalls++; return 2; }, () => { },
    out focusRoot, out focusReason) && focusReason == "time_budget" && focusCalls == 0 && focusRoot == 0, "descent time limit checked between getters");
Assert(!focusTest.TryResolve(1, () => null, _ => true, _ => 0, (_, _) => throw new Exception("Out-of-range child getter called"), () => { },
    out focusRoot, out focusReason) && focusReason == "focus_child_unavailable" && focusRoot == 0, "missing child fails closed");
Assert(!focusTest.TryResolve(1, () => null, _ => false, _ => throw new Exception("Ineligible ancestor traversed"), (_, _) => 0, () => { },
    out focusRoot, out focusReason) && focusReason == "focus_ancestor_ineligible", "existing ancestor visibility filter retained");
Assert(!focusTest.TryResolve(1, () => null, _ => true, _ => 2, (_, _) => 0, () => { },
    out focusRoot, out focusReason) && focusReason == "focus_root_unavailable" && focusRoot == 0, "null descendant never falls back");
Assert(UiFocusPath.TryParse("panel0", out var panelFocusTest) && panelFocusTest!.TryResolve(1, () => null,
    _ => throw new Exception("Root-only focus unexpectedly descends"), _ => 0, (_, _) => 0, () => { }, out focusRoot, out focusReason)
    && focusRoot == 1, "explicit panel-root focus is supported without implicit default");
var focusedCapture = new UiCapture { FocusRequested = true, FocusResolved = true, FocusRootPath = "panel0/0/1", FocusDescentNodes = 2 };
focusedCapture.Add(new UiText("focus/0", "TEST focused text"));
using (var focusedPage = JsonDocument.Parse(ObservationFactory.Create(focusedCapture, null, "offline-focus-test")))
{
    var focusedFacts = focusedPage.RootElement.GetProperty("payload").GetProperty("facts");
    using var focusMetrics = JsonDocument.Parse(focusedFacts[0].GetProperty("value").GetString()!);
    Assert(focusMetrics.RootElement.GetProperty("focus_requested").GetBoolean() && focusMetrics.RootElement.GetProperty("focus_resolved").GetBoolean(), "focus state explicit in diagnostics");
    Assert(focusMetrics.RootElement.GetProperty("focus_root_path").GetString() == "panel0/0/1", "focus is a literal path, not a page identity");
    Assert(focusMetrics.RootElement.GetProperty("depth_scope").GetString() == "relative_to_requested_focus_root", "focused depth scope explicit");
    Assert(focusedFacts[1].GetProperty("entity_id").GetString() == "focus/0", "focused paths are capture-local and relative");
    Assert(focusMetrics.RootElement.GetProperty("path_scope").GetString() == "focus_relative", "relative scope explicit");
    Assert(focusMetrics.RootElement.GetProperty("identity_scope").GetString() == "capture_local_ui_path", "never claims stable entity IDs");
}

Assert(UiTraversalBounds.CaptureRootPath(3, null) == "panel3", "normal absolute root paths unchanged");
Assert(UiTraversalBounds.CaptureRootPath(0, focusTest) == "focus", "focused traversal uses a scoped relative root");
var relativeDiagnostics = new UiPanelDiagnostics();
var absolutePrefix = "panel0" + string.Concat(Enumerable.Repeat("/511", 30));
Assert(!UiTraversalBounds.TryChildPath(absolutePrefix, 0, 511, relativeDiagnostics, out _), "old full descendant would exceed contract limit");
Assert(UiTraversalBounds.TryChildPath(UiTraversalBounds.CaptureRootPath(0, focusTest), 0, 511, relativeDiagnostics, out var relativeChild)
    && relativeChild == "focus/511", "bounded relative path admits same child without contracting root metadata");
var relativeBoundary = "focus" + string.Concat(Enumerable.Repeat("/511", 30)) + "/10";
Assert(relativeBoundary.Length == 128 && !UiTraversalBounds.TryChildPath(relativeBoundary, 31, 0, relativeDiagnostics, out _), "relative paths retain 128-character hard cap");

// Synthetic deep single-child trees exercise the exact admission helper used by
// native traversal, without loading game objects or invoking native getters.
var deepDiagnostics = new UiPanelDiagnostics();
var deepPath = "panel0";
for (var depth = 0; depth < 48; depth++)
{
    Assert(UiTraversalBounds.TryChildPath(deepPath, depth, 0, deepDiagnostics, out var nextPath), "depth through 48 is admitted");
    Assert(nextPath == deepPath + "/0", "literal identity path remains unchanged");
    deepPath = nextPath;
}
Assert(!UiTraversalBounds.TryChildPath(deepPath, 48, 0, deepDiagnostics, out var rejectedDepthPath), "depth 49 is skipped");
Assert(rejectedDepthPath == "" && deepDiagnostics.depth_skipped == 1 && deepDiagnostics.truncated, "depth clipping is explicit");
var pathDiagnostics = new UiPanelDiagnostics();
var longPath = "panel0" + string.Concat(Enumerable.Repeat("/511", 30));
Assert(longPath.Length == 126, "synthetic long path fixture");
Assert(UiTraversalBounds.TryChildPath(longPath, 30, 0, pathDiagnostics, out var boundaryPath), "exact 128-character path is admitted");
Assert(boundaryPath.Length == 128, "path boundary retained without hashing");
Assert(!UiTraversalBounds.TryChildPath(boundaryPath, 31, 0, pathDiagnostics, out var rejectedLongPath), "overlong child is skipped before capture serialization");
Assert(rejectedLongPath == "" && pathDiagnostics.path_limit_skipped == 1 && pathDiagnostics.truncated, "path clipping is explicit");
var deepCapture = new UiCapture();
deepCapture.Panels.Add(pathDiagnostics);
deepCapture.Add(new UiText(deepPath, "TEST deep text"));
deepCapture.Add(new UiText(boundaryPath, "TEST boundary text"));
using (var deepPage = JsonDocument.Parse(ObservationFactory.Create(deepCapture, null, "offline-deep-path-test")))
{
    var deepFacts = deepPage.RootElement.GetProperty("payload").GetProperty("facts").EnumerateArray().ToArray();
    Assert(deepFacts.Count(f => f.GetProperty("entity_kind").GetString() == "ui_element") == 2, "path clipping does not discard valid capture texts");
    using var bounds = JsonDocument.Parse(deepFacts[0].GetProperty("value").GetString()!);
    Assert(bounds.RootElement.GetProperty("max_depth").GetInt32() == 48, "diagnostics expose measured depth setting");
    Assert(bounds.RootElement.GetProperty("max_path_length").GetInt32() == 128, "diagnostics expose contract path bound");
    Assert(bounds.RootElement.GetProperty("max_nodes").GetInt32() == 2500 && bounds.RootElement.GetProperty("max_texts").GetInt32() == 240 && bounds.RootElement.GetProperty("budget_ms").GetInt32() == 15, "documented traversal budgets");
}

var textCapCapture = new UiCapture();
for (var i = 0; i < 240; i++) textCapCapture.Add(new UiText($"panel0/{i}", "TEST short text"));
using (var textCapPage = JsonDocument.Parse(ObservationFactory.Create(textCapCapture, null, "offline-text-cap-test")))
    Assert(textCapPage.RootElement.GetProperty("payload").GetProperty("facts").EnumerateArray().Count(f => f.GetProperty("entity_kind").GetString() == "ui_element") == 240, "240 short texts fit unchanged payload budget");
textCapCapture.Add(new UiText("panel0/240", "TEST overflow"));
try { ObservationFactory.Create(textCapCapture, null, "offline-over-cap-test"); throw new Exception("Text hard cap was not enforced"); }
catch (ArgumentOutOfRangeException) { }

var diagnosticCapture = new UiCapture { PanelsAvailable = 33, StopReason = "panel_limit", ElapsedMs = 15.1 };
for (var i = 0; i < 32; i++)
    diagnosticCapture.Panels.Add(new UiPanelDiagnostics { panel_index = i, visited_nodes = 70,
        visible_nodes = 60, text_element_nodes = 3, other_widget_nodes = 57,
        emitted_texts = 2, stop_reason = "time_budget", pending_nodes = 10, elapsed_ms = 0.4 });
diagnosticCapture.AddRange(Enumerable.Range(0, 240).Select(i => new UiText($"panel0/{i}", new string('球', 1000))));
var diagnosticJson = ObservationFactory.Create(diagnosticCapture, null, "offline-diagnostic-test");
Assert(Encoding.UTF8.GetByteCount(diagnosticJson) <= ObservationFactory.MaximumPayloadBytes, "diagnostics plus Chinese text respect byte cap");
using (var diagnosticPage = JsonDocument.Parse(diagnosticJson))
{
    var facts = diagnosticPage.RootElement.GetProperty("payload").GetProperty("facts").EnumerateArray().ToArray();
    Assert(facts.Count(f => f.GetProperty("entity_kind").GetString() == "ui_capture_diagnostic") == 34, "all bounded panel diagnostics retained");
    using var metrics = JsonDocument.Parse(facts[0].GetProperty("value").GetString()!);
    Assert(metrics.RootElement.GetProperty("truncated").GetBoolean(), "panel cap reported");
    Assert(metrics.RootElement.GetProperty("visited_nodes").GetInt32() == 2240, "visited count aggregated");
    using var transport = JsonDocument.Parse(facts[^1].GetProperty("value").GetString()!);
    Assert(transport.RootElement.GetProperty("omitted_texts").GetInt32() > 0, "byte truncation distinguished from traversal cap");
}
var emptyCapture = new UiCapture { StopReason = "domain_unavailable" };
using (var empty = JsonDocument.Parse(ObservationFactory.Create(emptyCapture, null, "offline-empty-test")))
    Assert(empty.RootElement.GetProperty("payload").GetProperty("facts").GetArrayLength() == 2, "zero text still publishes diagnostics, never fabricated UI text");
var skippedCapture = new UiCapture();
skippedCapture.Panels.Add(new UiPanelDiagnostics { depth_skipped = 1 });
Assert(skippedCapture.Truncated, "depth skip reports incomplete traversal without global cutoff");

var fixture = ObservationFactory.Create(new[] { new UiText("panel0/1", "Synthetic bridge contract test") }, null, "offline-contract-test");
// Never publish a contract-test fixture as a real runtime observation.
using (var parsed = JsonDocument.Parse(fixture))
{
    Assert(parsed.RootElement.GetProperty("schema_version").GetString() == "0.2.0", "contract version");
    Assert(parsed.RootElement.GetProperty("status").GetString() == "partial", "partial UI snapshot");
    Assert(parsed.RootElement.GetProperty("game").GetProperty("game_time").ValueKind == JsonValueKind.Null, "unknown game date retained");
    Assert(parsed.RootElement.GetProperty("payload").GetProperty("facts")[0].GetProperty("field").GetString() == "ui_tree_text", "raw UI tree does not promise pixel visibility");
}
if (args.Length == 1)
{
    // Explicitly mark exported offline fixtures synthetic before saving them.
    var root = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(fixture)!;
    using var marked = JsonDocument.Parse("true");
    root["synthetic"] = marked.RootElement.Clone();
    File.WriteAllText(args[0], JsonSerializer.Serialize(root));
}

var temp = Path.Combine(Path.GetTempPath(), "footballassistant-bridge-test-" + Guid.NewGuid());
Directory.CreateDirectory(temp);
try
{
    var config = Path.Combine(temp, "runtime.json");
    File.WriteAllText(config, "{\"base_url\":\"http://127.0.0.1:17827\",\"token\":\"offline-test-token\"}");
    var valid = ConnectionSettings.Read(config);
    Assert(valid.BaseUrl.IsLoopback, "loopback accepted");
    foreach (var address in new[] { "https://example.com", "http://192.168.1.1", "http://localhost:17827", "file:///tmp/anything" })
    {
        File.WriteAllText(config, JsonSerializer.Serialize(new { base_url = address, token = "offline-test-token" }));
        try { ConnectionSettings.Read(config); throw new Exception("Nonliteral/nonloopback address accepted."); }
        catch (InvalidDataException) { }
    }
    File.WriteAllText(config, "{\"base_url\":\"http://127.0.0.1:17827\",\"token\":\"offline-test-token\"}");
    var handler = new Recorder();
    using (var publisher = new SnapshotPublisher(() => ConnectionSettings.Read(config), _ => { }, handler))
    {
        Assert(publisher.Offer(fixture), "nonblocking enqueue");
        await handler.Received.Task.WaitAsync(TimeSpan.FromSeconds(3));
        Assert(handler.Path == "/v1/observations", "ingest path");
        Assert(handler.Auth == "Bearer offline-test-token", "authenticated delivery");
        Assert(handler.Body == fixture, "snapshot retained in delivery");
        Assert(!publisher.Offer(new string('x', ObservationFactory.MaximumPayloadBytes + 1)), "oversized snapshot rejected");
        File.WriteAllText(config, "{\"base_url\":\"http://127.0.0.1:17827\",\"token\":\"rotated-offline-test-token\"}");
        Assert(publisher.Offer(fixture), "next snapshot after token rotation");
        await handler.SecondReceived.Task.WaitAsync(TimeSpan.FromSeconds(3));
        Assert(handler.Auth == "Bearer rotated-offline-test-token", "runtime token reloaded");
    }
}
finally { Directory.Delete(temp, true); }

// Exercise the production handler against a local redirect server. It must not
// follow even a loopback redirect, so UI content can never leave via a 3xx hop.
var server = new TcpListener(IPAddress.Loopback, 0);
server.Start();
try
{
    var endpoint = (IPEndPoint)server.LocalEndpoint;
    var redirectSent = Task.Run(async () =>
    {
        using var client = await server.AcceptTcpClientAsync();
        using var stream = client.GetStream();
        var request = new byte[16_384];
        var count = 0;
        while (count < request.Length)
        {
            var read = await stream.ReadAsync(request.AsMemory(count));
            if (read == 0) break;
            count += read;
            if (Encoding.ASCII.GetString(request, 0, count).Contains("\r\n\r\n")) break;
        }
        var response = $"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{endpoint.Port}/redirected\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
        await stream.WriteAsync(Encoding.ASCII.GetBytes(response));
    });
    var refused = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
    using var production = new SnapshotPublisher(
        () => new ConnectionSettings(new Uri($"http://127.0.0.1:{endpoint.Port}"), "local-redirect-test"),
        message => { if (message.Contains("HTTP 302")) refused.TrySetResult(true); });
    production.Offer(fixture);
    await refused.Task.WaitAsync(TimeSpan.FromSeconds(3));
    await redirectSent.WaitAsync(TimeSpan.FromSeconds(3));
    Assert(!server.Pending(), "redirect was not followed");
}
finally { server.Stop(); }
Console.WriteLine("PASS: thread gate, Chinese byte budget, observation semantics, loopback restrictions, authenticated async delivery and token rotation. No game/loader was opened.");

static void Assert(bool condition, string label)
{
    if (!condition) throw new Exception("Failed: " + label);
}

sealed class Recorder : HttpMessageHandler
{
    public readonly TaskCompletionSource<bool> Received = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public readonly TaskCompletionSource<bool> SecondReceived = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int count;
    public string? Path, Auth, Body;
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Path = request.RequestUri!.AbsolutePath;
        Auth = request.Headers.Authorization?.ToString();
        Body = await request.Content!.ReadAsStringAsync(cancellationToken);
        Received.TrySetResult(true);
        if (Interlocked.Increment(ref count) >= 2) SecondReceived.TrySetResult(true);
        return new HttpResponseMessage(HttpStatusCode.Accepted);
    }
}
