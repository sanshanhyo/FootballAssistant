using System.Net;
using System.Net.Http.Headers;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;

namespace FootballAssistant.GameBridge;

public sealed record UiText(string ElementId, string Text);

// Diagnostics describe traversal only, never screen identity or football semantics.
public sealed class UiCapture : List<UiText>
{
    public UiCapture() : base(UiTraversalBounds.MaximumTexts) { }
    public List<UiPanelDiagnostics> Panels { get; } = new();
    public int PanelsAvailable { get; set; }
    public bool FocusRequested { get; set; }
    public bool FocusResolved { get; set; }
    public string? FocusRootPath { get; set; }
    public int FocusDescentNodes { get; set; }
    public UiWidgetInventory? WidgetInventory { get; set; }
    public double ElapsedMs { get; set; }
    public string StopReason { get; set; } = "complete";
    public bool Truncated => StopReason != "complete" || Panels.Any(p => p.truncated);
}

public sealed class UiPanelDiagnostics
{
    public int panel_index { get; set; }
    public int visited_nodes { get; set; }
    public int visible_nodes { get; set; }
    public int visibility_false { get; set; }
    public int invalid_or_empty_bounds { get; set; }
    public int text_element_nodes { get; set; }
    public int other_widget_nodes { get; set; }
    public int empty_text_nodes { get; set; }
    public int emitted_texts { get; set; }
    public int depth_skipped { get; set; }
    public int path_limit_skipped { get; set; }
    public int child_limit_skipped { get; set; }
    public int pending_nodes { get; set; }
    public double elapsed_ms { get; set; }
    public string stop_reason { get; set; } = "complete";
    public bool truncated => stop_reason != "complete" || depth_skipped > 0 || path_limit_skipped > 0 || child_limit_skipped > 0;
}

// Metadata-only, opt-in instrumentation of the traversal already performed.
public sealed class UiWidgetInventory
{
    public const string EnvironmentVariable = "FOOTBALL_ASSISTANT_UI_WIDGET_DIAGNOSTICS";
    public const int MaximumClasses = 16;
    public const int MaximumSamples = 32;
    private readonly Dictionary<nint, UiWidgetClass> classes = new();
    private readonly HashSet<nint> attemptedTypes = new();
    public int MetadataClassesAttempted => attemptedTypes.Count;
    public List<UiWidgetSample> Visited { get; } = new();
    public List<UiWidgetSample> Pruned { get; } = new();
    public IEnumerable<UiWidgetClass> Classes => classes.Values;
    public int ObservedNodes { get; private set; }
    public int PrunedNodes { get; private set; }
    public int UnclassifiedNodes { get; private set; }
    public int MetadataErrors { get; private set; }
    public int BudgetSkippedNodes { get; set; }

    public void Observe(nint type, string path, string phase, bool supported, bool visible,
        bool? boundsValid, int? childCount, Func<nint, (string Namespace, string Name)> identity)
    {
        ObservedNodes++;
        var pruned = !visible || boundsValid != true;
        if (pruned) PrunedNodes++;
        if (!classes.TryGetValue(type, out var summary) && attemptedTypes.Count < MaximumClasses && attemptedTypes.Add(type))
        {
            try
            {
                var (ns, name) = identity(type);
                summary = new UiWidgetClass { class_index = classes.Count, @namespace = ns[..Math.Min(ns.Length, 96)],
                    name = name[..Math.Min(name.Length, 96)], name_truncated = ns.Length > 96 || name.Length > 96 };
                classes[type] = summary;
            }
            catch (Exception) { MetadataErrors++; } // Diagnostic failure never disables capture.
        }
        if (summary is null) UnclassifiedNodes++;
        else
        {
            summary.nodes++;
            if (!visible) summary.visible_false++;
            if (boundsValid == false) summary.invalid_or_empty_bounds++;
            if (supported) summary.text_element_nodes++;
            if (childCount.HasValue) { summary.child_count_observations++; summary.child_count_total += childCount.Value; }
        }
        if (Visited.Count >= MaximumSamples && (!pruned || Pruned.Count >= MaximumSamples)) return;
        var sample = new UiWidgetSample(path, phase, summary?.class_index, supported, visible, boundsValid, childCount,
            !visible ? "visible_false" : boundsValid != true ? "invalid_or_empty_bounds" : "eligible");
        if (Visited.Count < MaximumSamples) Visited.Add(sample);
        if (pruned && Pruned.Count < MaximumSamples) Pruned.Add(sample);
    }
}

public sealed class UiWidgetClass
{
    public int class_index { get; set; }
    public string @namespace { get; set; } = "";
    public string name { get; set; } = "";
    public bool name_truncated { get; set; }
    public int nodes { get; set; }
    public int visible_false { get; set; }
    public int invalid_or_empty_bounds { get; set; }
    public int text_element_nodes { get; set; }
    public int child_count_observations { get; set; }
    public long child_count_total { get; set; }
}

public sealed record UiWidgetSample(string path, string phase, int? class_index, bool text_element_supported,
    bool visible, bool? bounds_valid, int? child_count, string eligibility);

// Literal UI hierarchy paths only: never hash/shorten them into apparent stable IDs.
internal static class UiTraversalBounds
{
    public const int MaximumTexts = 240;
    public const int MaximumDepth = 48;
    public const int MaximumPathLength = 128;

    public static string CaptureRootPath(int panelIndex, UiFocusPath? focus) => focus is null ? $"panel{panelIndex}" : "focus";

    // Reject before fetching the child object. A skipped root may have descendants;
    // counters count skipped roots, not an estimated number of missing text values.
    public static bool TryChildPath(string parentPath, int parentDepth, int childIndex,
        UiPanelDiagnostics diagnostics, out string childPath)
    {
        childPath = "";
        if (parentDepth >= MaximumDepth) { diagnostics.depth_skipped++; return false; }
        var suffix = "/" + childIndex.ToString(System.Globalization.CultureInfo.InvariantCulture);
        if (parentPath.Length + suffix.Length > MaximumPathLength)
        {
            diagnostics.path_limit_skipped++;
            return false;
        }
        childPath = parentPath + suffix;
        return true;
    }
}

// Explicit local diagnostic selection, not a page classifier or game entity path.
internal sealed record UiFocusPath(string Path, int PanelIndex, int[] ChildIndices)
{
    public const string EnvironmentVariable = "FOOTBALL_ASSISTANT_UI_FOCUS_PATH";

    public static bool TryParse(string value, out UiFocusPath? focus)
    {
        focus = null;
        if (value.Length is < 6 or > UiTraversalBounds.MaximumPathLength) return false;
        var parts = value.Split('/');
        if (!parts[0].StartsWith("panel", StringComparison.Ordinal)) return false;
        bool Index(string text, int maximum, out int index) =>
            int.TryParse(text, System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out index)
            && index >= 0 && index <= maximum && text == index.ToString(System.Globalization.CultureInfo.InvariantCulture);
        if (!Index(parts[0][5..], 31, out var panel)) return false;
        var children = new int[parts.Length - 1];
        for (var i = 1; i < parts.Length; i++)
            if (!Index(parts[i], 511, out children[i - 1])) return false;
        focus = new UiFocusPath(value, panel, children);
        return true;
    }

    // Same read-only getters as normal traversal. Each ancestor consumes the shared
    // node/time budget; check between calls, never fall back to the unfocused root.
    public bool TryResolve(nint root, Func<string?> limit, Func<nint, bool> visible,
        Func<nint, int> childCount, Func<nint, int, nint> childAt, Action visited,
        out nint resolved, out string reason)
    {
        resolved = 0;
        reason = "complete";
        foreach (var index in ChildIndices)
        {
            var stopped = limit();
            if (stopped is not null) { reason = stopped; return false; }
            if (root == 0) { reason = "focus_root_unavailable"; return false; }
            visited();
            if (!visible(root)) { reason = "focus_ancestor_ineligible"; return false; }
            stopped = limit();
            if (stopped is not null) { reason = stopped; return false; }
            var count = childCount(root);
            if (index >= Math.Clamp(count, 0, 512)) { reason = "focus_child_unavailable"; return false; }
            stopped = limit();
            if (stopped is not null) { reason = stopped; return false; }
            root = childAt(root, index);
        }
        var finalLimit = limit();
        if (finalLimit is not null) { reason = finalLimit; return false; }
        if (root == 0) { reason = "focus_root_unavailable"; return false; }
        resolved = root;
        return true;
    }
}

public static class ObservationFactory
{
    public const string AdapterVersion = "0.4.0";
    // Backend caps the whole request at 128 KiB. Leave room for envelope overhead.
    public const int MaximumPayloadBytes = 120_000;

    public static string Create(IReadOnlyList<UiText> texts, string? gameBuild, string sessionId)
    {
        if (texts.Count > UiTraversalBounds.MaximumTexts || (texts.Count == 0 && texts is not UiCapture))
            throw new ArgumentOutOfRangeException(nameof(texts));
        if (texts.Any(t => string.IsNullOrWhiteSpace(t.Text) || t.Text.Length > 4000 || t.ElementId.Length > UiTraversalBounds.MaximumPathLength))
            throw new ArgumentException("UI text must fit the observation contract.", nameof(texts));
        if (gameBuild?.Length > 128 || sessionId.Length > 128)
            throw new ArgumentException("Provenance values must be bounded.");

        var facts = new List<object>();
        var estimatedBytes = 3072;
        // Each diagnostic is a bounded JSON string scalar in the existing fact protocol.
        // Reserve its actual serialized size before fitting texts to the byte budget.
        void Diagnostic(string id, object metrics)
        {
            var value = JsonSerializer.Serialize(metrics);
            if (value.Length > 4000) throw new ArgumentException("UI diagnostics exceed scalar limit.");
            var fact = new { entity_kind = "ui_capture_diagnostic", entity_id = "diagnostic/" + id, field = "capture_metrics", value };
            estimatedBytes += JsonSerializer.SerializeToUtf8Bytes(fact).Length + 1;
            facts.Add(fact);
        }
        var capture = texts as UiCapture;
        if (capture is not null)
        {
            if (capture.Panels.Count > 32) throw new ArgumentException("UI panel diagnostics exceed limit.");
            Diagnostic("capture", new {
                panels_available = capture.PanelsAvailable, panels_visited = capture.Panels.Count,
                visited_nodes = capture.Panels.Sum(p => p.visited_nodes),
                elapsed_ms = capture.ElapsedMs, stop_reason = capture.StopReason, truncated = capture.Truncated,
                captured_texts = texts.Count, max_texts = UiTraversalBounds.MaximumTexts, max_nodes = 2500, budget_ms = 15,
                max_depth = UiTraversalBounds.MaximumDepth, max_path_length = UiTraversalBounds.MaximumPathLength,
                focus_requested = capture.FocusRequested, focus_resolved = capture.FocusResolved,
                focus_root_path = capture.FocusRootPath, focus_descent_nodes = capture.FocusDescentNodes,
                path_scope = capture.FocusRequested ? "focus_relative" : "panel_absolute",
                identity_scope = "capture_local_ui_path",
                depth_scope = capture.FocusRequested ? "relative_to_requested_focus_root" : "relative_to_panel_root",
                supported_text_type = "UnityEngine.UIElements.TextElement (including subclasses)",
                visibility_test = "get_visible_and_positive_finite_worldBound_not_pixel_visibility"
            });
            foreach (var panel in capture.Panels) Diagnostic($"panel{panel.panel_index}", panel);
            if (capture.WidgetInventory is { } inventory)
            {
                if (!capture.FocusRequested || capture.Panels.Count > 1)
                    throw new ArgumentException("Widget diagnostics require a single focused capture.");
                Diagnostic("widgets/summary", new { observed_nodes = inventory.ObservedNodes,
                    pruned_nodes = inventory.PrunedNodes, unclassified_nodes = inventory.UnclassifiedNodes,
                    metadata_errors = inventory.MetadataErrors, metadata_classes_attempted = inventory.MetadataClassesAttempted,
                    budget_skipped_nodes = inventory.BudgetSkippedNodes,
                    class_limit = UiWidgetInventory.MaximumClasses, sample_limit = UiWidgetInventory.MaximumSamples,
                    class_summary_incomplete = inventory.UnclassifiedNodes > 0, pruned_children_read = false,
                    visited_samples_truncated = inventory.ObservedNodes > inventory.Visited.Count,
                    pruned_samples_truncated = inventory.PrunedNodes > inventory.Pruned.Count,
                    descendant_visibility = "unknown_for_pruned_subtrees", values_read = "none_metadata_only" });
                // Bounded batches keep every scalar <=4000 chars and total diagnostics <=34.
                var widgetClasses = inventory.Classes.ToArray();
                for (var i = 0; i < widgetClasses.Length; i += 2)
                    Diagnostic($"widgets/classes{i / 2}", widgetClasses.Skip(i).Take(2).ToArray());
                for (var i = 0; i < inventory.Visited.Count; i += 4)
                    Diagnostic($"widgets/visited{i / 4}", inventory.Visited.Skip(i).Take(4).ToArray());
                for (var i = 0; i < inventory.Pruned.Count; i += 4)
                    Diagnostic($"widgets/pruned{i / 4}", inventory.Pruned.Skip(i).Take(4).ToArray());
            }
        }
        var diagnosticCount = facts.Count;
        foreach (var text in texts)
        {
            var fact = new { entity_kind = "ui_element", entity_id = text.ElementId, field = "ui_tree_text", value = text.Text };
            var bytes = JsonSerializer.SerializeToUtf8Bytes(fact).Length + 1;
            if (estimatedBytes + bytes > MaximumPayloadBytes) break;
            facts.Add(fact);
            estimatedBytes += bytes;
        }
        if (capture is not null)
            Diagnostic("transport", new { emitted_texts = facts.Count - diagnosticCount,
                omitted_texts = texts.Count - (facts.Count - diagnosticCount),
                truncated = texts.Count > facts.Count - diagnosticCount, stop_reason = texts.Count > facts.Count - diagnosticCount ? "payload_byte_limit" : "complete" });
        if (facts.Count == 0) throw new ArgumentException("No text fits the bounded observation.");

        var now = DateTimeOffset.UtcNow.ToString("O");
        var json = JsonSerializer.Serialize(new
        {
            schema_version = "0.2.0",
            event_id = Guid.NewGuid().ToString(),
            captured_at = now,
            observed_at = now,
            synthetic = false,
            source = new
            {
                kind = "runtime",
                adapter_id = "footballassistant.runtime-ui-tree",
                adapter_version = AdapterVersion,
                platform = Platform(),
                freshness = "live"
            },
            game = new { product = "FM27", build = gameBuild, session_id = sessionId, game_time = (string?)null },
            // This is a bounded view of the current UI, never a complete squad/database dump.
            status = "partial",
            payload = new
            {
                kind = "fact_snapshot",
                facts
            }
        });
        if (Encoding.UTF8.GetByteCount(json) > MaximumPayloadBytes)
            throw new InvalidOperationException("Observation exceeded its final byte budget.");
        return json;
    }

    private static string Platform() => (RuntimeInformation.IsOSPlatform(OSPlatform.OSX), RuntimeInformation.ProcessArchitecture) switch
    {
        (true, Architecture.Arm64) => "macos-arm64",
        (true, Architecture.X64) => "macos-x64",
        (false, Architecture.X64) when RuntimeInformation.IsOSPlatform(OSPlatform.Windows) => "windows-x64",
        _ => "unknown"
    };
}

public sealed record ConnectionSettings(Uri BaseUrl, string Token)
{
    public static ConnectionSettings Read(string path)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Length > 16_384)
            throw new InvalidDataException("Runtime connection file is missing or too large.");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = document.RootElement;
        var address = root.GetProperty("base_url").GetString();
        var token = root.GetProperty("token").GetString();
        if (!Uri.TryCreate(address, UriKind.Absolute, out var uri) || uri.Scheme != "http" ||
            !IPAddress.TryParse(uri.Host, out var host) || !IPAddress.IsLoopback(host) ||
            !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new InvalidDataException("Bridge only sends to a literal loopback HTTP address.");
        if (string.IsNullOrWhiteSpace(token) || token.Any(char.IsControl))
            throw new InvalidDataException("Runtime token is missing or malformed.");
        return new ConnectionSettings(uri, token);
    }
}

public sealed class SnapshotPublisher : IDisposable
{
    private readonly Channel<string> queue = Channel.CreateBounded<string>(new BoundedChannelOptions(2)
    {
        SingleReader = true,
        SingleWriter = true,
        FullMode = BoundedChannelFullMode.DropOldest
    });
    private readonly CancellationTokenSource stop = new();
    private readonly HttpClient http;
    private readonly Func<ConnectionSettings> connection;
    private readonly Action<string> report;
    private readonly Task worker;
    private int disposed;

    public SnapshotPublisher(Func<ConnectionSettings> connection, Action<string> report, HttpMessageHandler? handler = null)
    {
        this.connection = connection;
        this.report = report;
        http = handler is null
            ? new HttpClient(new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = false })
            : new HttpClient(handler);
        http.Timeout = TimeSpan.FromMilliseconds(1500);
        worker = Task.Run(PublishLoop);
    }

    public bool Offer(string json) => Volatile.Read(ref disposed) == 0 &&
        Encoding.UTF8.GetByteCount(json) <= ObservationFactory.MaximumPayloadBytes && queue.Writer.TryWrite(json);

    private async Task PublishLoop()
    {
        try
        {
            await foreach (var json in queue.Reader.ReadAllAsync(stop.Token))
            {
                try
                {
                    var settings = connection(); // Reload after backend restart/token rotation.
                    using var request = new HttpRequestMessage(HttpMethod.Post, new Uri(settings.BaseUrl, "/v1/observations"));
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", settings.Token);
                    request.Content = new StringContent(json, Encoding.UTF8, "application/json");
                    using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop.Token);
                    if (!response.IsSuccessStatusCode)
                        report($"Observation delivery refused (HTTP {(int)response.StatusCode}).");
                }
                catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
                catch (Exception error)
                {
                    // Never log the token, UI text, response body or local absolute paths.
                    report($"Observation delivery unavailable ({error.GetType().Name}).");
                }
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        queue.Writer.TryComplete();
        stop.Cancel();
        http.Dispose();
        // The game main thread never waits for networking or for the worker to finish.
    }
}
