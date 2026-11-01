using System.Text;
using System.Text.Json;
namespace FootballAssistant.GameBridge;
internal sealed record FiniteRowsConfigurationData(string PrivateRoot, ApprovedModule Module, string WindowClass, DateTimeOffset RecordedAt);
internal sealed record FiniteRowsHostManifest(Guid BatchId, Guid PageEpoch, Guid FirstNonce, Guid SecondNonce,
    int Pid, string Session, string BridgeHash, string GameHash, string WindowClass,
    DateTimeOffset RequestedAt, DateTimeOffset ExpiresAt, bool StableProfileAsserted, string Manifest = "goalkeeper_rows0_3");
internal static class FiniteRowsCandidateConfiguration
{
    internal const string ConfigName = "footballassistant.windows-finite-rows.json";
    internal const string RequestName = "finite-rows-request.json";
    internal static FiniteRowsConfigurationData Read(string assemblyPath)
    {
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(assemblyPath);
        var directory = Path.GetDirectoryName(assemblyPath)!;
        using var json = ReadBounded(Path.Combine(directory, ConfigName));
        var root = Exact(json.RootElement, "schema_version", "mode", "exe_path", "game_path", "volume_serial", "file_index", "window_class", "prelaunch_recorded_at");
        if (Integer(root, "schema_version", 4, 4) != 4 || String(root, "mode", 32) != "goalkeeper_rows0_3" ||
            String(root, "window_class", 126) != "UnityWndClass") throw new InvalidOperationException("Explicit discovery configuration required.");
        var exe = String(root, "exe_path", 2048); var game = String(root, "game_path", 2048);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(exe);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(game);
        var volume = Unsigned(root, "volume_serial"); var file = Unsigned(root, "file_index");
        if (volume > uint.MaxValue || file == 0) throw new InvalidOperationException("Invalid pre-launch file identity.");
        var module = new ApprovedModule(game, VerifiedWindowsBuild.GameAssemblySha256, (uint)volume, file, exe, VerifiedWindowsBuild.ExecutableSha256);
        var privateRoot = Path.Combine(directory, "windows-finite-rows-private");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(privateRoot);
        return new(privateRoot, module, "UnityWndClass", Date(root, "prelaunch_recorded_at"));
    }
    internal static FiniteRowsHostManifest ReadRequest(string path)
    { using var json = ReadBounded(path); return Parse(json.RootElement); }
    internal static FiniteRowsHostManifest ParseRequest(string json)
    {
        if (json is null || json.Length > 4096 || new UTF8Encoding(false, true).GetByteCount(json) is < 1 or > 4096)
            throw new InvalidOperationException("Manifest size outside 1..4096 bytes.");
        using var parsed = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = 2 });
        return Parse(parsed.RootElement);
    }
    private static Guid GuidField(JsonElement value, string name)
    {
        var text = String(value, name, 36);
        if (!Guid.TryParseExact(text, "D", out var id) || id == Guid.Empty || id.ToString("D") != text)
            throw new InvalidOperationException("Canonical nonempty UUID required.");
        return id;
    }
    private static FiniteRowsHostManifest Parse(JsonElement value)
    {
        var r = Exact(value, "schema_version", "mode", "batch_id", "page_epoch", "first_nonce", "second_nonce",
            "pid", "session_id", "bridge_sha256", "game_sha256", "window_class", "stable_profile_asserted", "requested_at", "expires_at");
        Integer(r, "schema_version", 4, 4);
        if (!FiniteRowsPolicy.ValidManifest(String(r, "mode", 32)) || String(r, "window_class", 126) != "UnityWndClass" ||
            r.GetProperty("stable_profile_asserted").ValueKind != JsonValueKind.True)
            throw new InvalidOperationException("Explicit fixed finite scope and operator assertion required.");
        var first = GuidField(r, "first_nonce"); var second = GuidField(r, "second_nonce");
        var created = Date(r, "requested_at"); var expires = Date(r, "expires_at");
        if (first == second || expires <= created || expires - created > TimeSpan.FromSeconds(120))
            throw new InvalidOperationException("Invalid finite nonce pair or lifetime.");
        return new(GuidField(r, "batch_id"), GuidField(r, "page_epoch"), first, second,
            Integer(r, "pid", 1, int.MaxValue), String(r, "session_id", 128), Hash(r, "bridge_sha256"), Hash(r, "game_sha256"),
            "UnityWndClass", created, expires, true, String(r, "mode", 32));
    }
    internal static FiniteRowsApproval? TryApproval(FiniteRowsHostManifest pending, SmokeContext current, DateTimeOffset now)
    {
        if (pending is null || current is null || pending.BatchId == Guid.Empty || pending.PageEpoch == Guid.Empty ||
            pending.FirstNonce == Guid.Empty || pending.SecondNonce == Guid.Empty || pending.FirstNonce == pending.SecondNonce ||
            !pending.StableProfileAsserted || !FiniteRowsPolicy.ValidManifest(pending.Manifest) || pending.Pid != current.Pid || pending.Session != current.Session ||
            pending.BridgeHash != current.BridgeHash || pending.GameHash != current.GameHash ||
            pending.WindowClass != "UnityWndClass" || pending.WindowClass != current.ConfirmedWindowClass ||
            pending.RequestedAt > now || pending.ExpiresAt <= now || pending.ExpiresAt <= pending.RequestedAt ||
            pending.ExpiresAt - pending.RequestedAt > TimeSpan.FromSeconds(120) || current.Pid <= 0 || current.EntryThread == 0 ||
            pending.Session is null || pending.Session.Length is < 1 or > 128 || string.IsNullOrWhiteSpace(pending.Session) ||
            !ValidHash(pending.BridgeHash) || !ValidHash(pending.GameHash)) return null;
        return new(current, pending.BatchId, pending.PageEpoch, pending.FirstNonce, pending.SecondNonce,
            pending.RequestedAt, pending.ExpiresAt, true, true, pending.Manifest);
    }
    private static bool ValidHash(string? s) => s is { Length: 64 } && s.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Hash(JsonElement r, string name)
    { var s = String(r, name, 64); if (!ValidHash(s)) throw new InvalidOperationException("Canonical SHA256 required."); return s; }
    private static string String(JsonElement r, string name, int maximum)
    {
        var e = r.GetProperty(name);
        if (e.ValueKind != JsonValueKind.String || e.GetString() is not { } s || s.Length is < 1 || s.Length > maximum || string.IsNullOrWhiteSpace(s))
            throw new InvalidOperationException("Invalid string field.");
        return s;
    }
    private static DateTimeOffset Date(JsonElement r, string name)
    {
        var s = String(r, name, 64);
        var offset = s.EndsWith('Z') || (s.Length >= 6 && (s[^6] is '+' or '-') && s[^3] == ':');
        if (!offset || !r.GetProperty(name).TryGetDateTimeOffset(out var date)) throw new InvalidOperationException("Explicit ISO timestamp offset required.");
        return date;
    }
    private static ulong Unsigned(JsonElement r, string name)
    {
        var e = r.GetProperty(name);
        if (e.ValueKind != JsonValueKind.Number || e.GetRawText().Any(c => c is < '0' or > '9') || !e.TryGetUInt64(out var number))
            throw new InvalidOperationException("Canonical unsigned integer required.");
        return number;
    }
    private static int Integer(JsonElement r, string name, int min, int max)
    { var n = Unsigned(r, name); if (n < (ulong)min || n > (ulong)max) throw new InvalidOperationException("Integer outside bounds."); return (int)n; }
    private static JsonElement Exact(JsonElement root, params string[] names)
    {
        if (root.ValueKind != JsonValueKind.Object) throw new InvalidOperationException("Object required.");
        var actual = root.EnumerateObject().Select(p => p.Name).ToArray();
        if (actual.Length != names.Length || actual.Distinct(StringComparer.Ordinal).Count() != names.Length ||
            actual.Any(n => !names.Contains(n, StringComparer.Ordinal))) throw new InvalidOperationException("Unexpected or duplicate fields.");
        return root;
    }
    private static JsonDocument ReadBounded(string path)
    {
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is <= 0 or > 4096) throw new InvalidOperationException("Configuration/request size outside 1..4096 bytes.");
        var bytes = new byte[(int)stream.Length]; stream.ReadExactly(bytes);
        if (stream.ReadByte() != -1) throw new InvalidOperationException("Configuration/request grew during read.");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        return JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 2 });
    }
}
