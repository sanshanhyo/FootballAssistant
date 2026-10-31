using System.Net;
using Microsoft.Win32.SafeHandles;
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

// Local operator control only. No UI/native getters, hooks, sockets or capture scheduling.
public sealed record UiCaptureSelection(long Sequence, string FocusPath, bool WidgetDiagnostics);

public sealed class UiCaptureControl
{
    public const int MaximumRequestBytes = 2048;
    private readonly string privateRoot;
    private readonly int pid;
    private readonly string sessionId, managedBuildSha;
    private readonly object gate = new();
    private UiCaptureSelection? pending, applied;
    private DateTimeOffset pendingExpires, appliedAt;
    private long acceptedSequence;
    private bool? focusResolved;
    private string? captureStopReason, lastError;
    private byte[]? lastRequest;

    public UiCaptureControl(string privateRoot, int pid, string sessionId, string managedBuildSha)
    {
        this.privateRoot = Path.GetFullPath(privateRoot);
        this.pid = pid;
        this.sessionId = sessionId;
        this.managedBuildSha = managedBuildSha;
    }

    private void CheckDirectory(string name)
    {
        if (new DirectoryInfo(privateRoot).LinkTarget is not null ||
            new DirectoryInfo(Path.Combine(privateRoot, name)).LinkTarget is not null)
            throw new InvalidDataException("linked_control_path");
    }

    [DllImport("libc", EntryPoint = "open", SetLastError = true)]
    private static extern int Open(string path, int flags);
    [DllImport("libc", EntryPoint = "openat", SetLastError = true)]
    private static extern int OpenAt(SafeFileHandle directory, string path, int flags);

    private FileStream OpenRequestNoFollow()
    {
        // macOS runtime; Linux is also supported for offline tests. No native game access.
        var mac = RuntimeInformation.IsOSPlatform(OSPlatform.OSX);
        if (!mac && !RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
            throw new InvalidDataException("unsupported_control_platform");
        var noFollow = mac ? 0x100 : 0x20000;
        var directory = mac ? 0x100000 : 0x10000;
        var nonBlock = mac ? 0x4 : 0x800;
        var closeOnExec = mac ? 0x1000000 : 0x80000;
        SafeFileHandle Handle(int fd)
        {
            if (fd < 0) throw new IOException("Control file could not be opened without following links.");
            return new SafeFileHandle((nint)fd, ownsHandle: true);
        }
        using var root = Handle(Open(privateRoot, directory | noFollow | closeOnExec));
        using var control = Handle(OpenAt(root, "control", directory | noFollow | closeOnExec));
        var file = Handle(OpenAt(control, "ui-capture.json", noFollow | nonBlock | closeOnExec));
        try { return new FileStream(file, FileAccess.Read); }
        catch { file.Dispose(); throw; }
    }

    public void Poll(DateTimeOffset now)
    {
        try
        {
            CheckDirectory("control");
            var path = Path.Combine(privateRoot, "control", "ui-capture.json");
            var info = new FileInfo(path);
            if (info.LinkTarget is not null) throw new InvalidDataException("linked_control_path");
            if (!info.Exists) return; // Deletion never silently broadens the capture.
            if (info.Length > MaximumRequestBytes) throw new InvalidDataException("request_too_large");
            byte[] bytes;
            using (var stream = OpenRequestNoFollow())
            {
                var buffer = new byte[MaximumRequestBytes + 1];
                var length = 0;
                while (length < buffer.Length)
                {
                    var count = stream.Read(buffer, length, buffer.Length - length);
                    if (count == 0) break;
                    length += count;
                }
                if (length > MaximumRequestBytes) throw new InvalidDataException("request_too_large");
                bytes = buffer[..length];
            }
            CheckDirectory("control");
            if (new FileInfo(path).LinkTarget is not null) throw new InvalidDataException("linked_control_path");
            lock (gate)
            {
                if (lastRequest is not null && lastRequest.AsSpan().SequenceEqual(bytes)) return;
                lastRequest = bytes;
            }
            using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 4 });
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object) throw new InvalidDataException("invalid_request");
            var fields = new HashSet<string>(StringComparer.Ordinal);
            var allowed = new HashSet<string>(new[] { "pid", "session_id", "managed_build_sha256", "sequence",
                "requested_at", "focus_path", "widget_diagnostics" }, StringComparer.Ordinal);
            foreach (var property in root.EnumerateObject())
                if (!allowed.Contains(property.Name) || !fields.Add(property.Name)) throw new InvalidDataException("invalid_request_fields");
            if (fields.Count != allowed.Count) throw new InvalidDataException("invalid_request_fields");
            if (root.GetProperty("pid").GetInt32() != pid || root.GetProperty("session_id").GetString() != sessionId ||
                root.GetProperty("managed_build_sha256").GetString() != managedBuildSha)
                throw new InvalidDataException("request_scope_mismatch");
            var sequence = root.GetProperty("sequence").GetInt64();
            var requestedText = root.GetProperty("requested_at").GetString();
            if (requestedText is null || !(requestedText.EndsWith("Z", StringComparison.Ordinal) ||
                (requestedText.Length >= 6 && requestedText[^3] == ':' && requestedText[^6] is '+' or '-')))
                throw new InvalidDataException("invalid_request_timestamp");
            var requested = root.GetProperty("requested_at").GetDateTimeOffset();
            if (requested > now || now - requested > TimeSpan.FromSeconds(30)) throw new InvalidDataException("request_expired_or_future");
            var focus = root.GetProperty("focus_path").GetString();
            if (focus is null || !UiFocusPath.TryParse(focus, out _)) throw new InvalidDataException("invalid_focus_path");
            var widgets = root.GetProperty("widget_diagnostics").GetBoolean();
            lock (gate)
            {
                if (sequence <= acceptedSequence) throw new InvalidDataException("request_sequence_replayed");
                pending = new UiCaptureSelection(sequence, focus, widgets);
                pendingExpires = requested.AddSeconds(30);
                acceptedSequence = sequence;
                lastError = null;
            }
        }
        catch (Exception error) when (error is InvalidDataException or IOException or UnauthorizedAccessException or JsonException or InvalidOperationException or FormatException or OverflowException or ArgumentException)
        {
            lock (gate) lastError = error is InvalidDataException ? error.Message : "control_read_or_parse_failed";
        }
    }

    // One immutable selection per capture; expiry limits acceptance, not duration of an applied setting.
    public UiCaptureSelection? BeginCapture(DateTimeOffset now)
    {
        lock (gate)
        {
            if (pending is not null && now > pendingExpires)
            {
                pending = null;
                lastError = "request_expired_before_capture";
            }
            return pending ?? applied;
        }
    }

    // Only the main-thread caller after Capture returns may acknowledge application.
    public void CompleteCapture(UiCaptureSelection? selection, UiCapture capture, DateTimeOffset now)
    {
        if (selection is null) return;
        lock (gate)
        {
            applied = selection;
            appliedAt = now;
            focusResolved = capture.FocusResolved;
            captureStopReason = capture.StopReason;
            if (pending?.Sequence == selection.Sequence) pending = null;
        }
    }

    // Background-only status I/O: acceptance alone never populates applied_sequence.
    public void WriteStatus()
    {
        object status;
        lock (gate) status = new {
            pid, session_id = sessionId, managed_build_sha256 = managedBuildSha,
            accepted_sequence = acceptedSequence == 0 ? (long?)null : acceptedSequence,
            applied_sequence = applied?.Sequence, focus_path = applied?.FocusPath,
            widget_diagnostics = applied?.WidgetDiagnostics, focus_resolved = focusResolved,
            capture_stop_reason = captureStopReason, applied_at = applied is null ? (DateTimeOffset?)null : appliedAt,
            last_error = lastError
        };
        CheckDirectory("diagnostics");
        var path = Path.Combine(privateRoot, "diagnostics", "ui-capture-status.json");
        if (new FileInfo(path).LinkTarget is not null) throw new InvalidDataException("linked_status_path");
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                JsonSerializer.Serialize(stream, status);
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

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
