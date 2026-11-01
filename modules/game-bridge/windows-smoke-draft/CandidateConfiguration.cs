using System.Text.Json;

namespace FootballAssistant.GameBridge;

internal sealed record MetadataCandidateConfiguration(string PrivateRoot, ApprovedModule Module, string WindowClass, DateTimeOffset RecordedAt);
internal static class CandidateConfiguration
{
    internal const string ConfigName = "footballassistant.windows-metadata.json";
    internal const string RequestName = "metadata-once-request.json";
    internal static MetadataCandidateConfiguration Read(string assemblyPath)
    {
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(assemblyPath);
        var directory = Path.GetDirectoryName(assemblyPath)!;
        using var json = ReadBounded(Path.Combine(directory, ConfigName));
        var root = RequireExactObject(json.RootElement, "schema_version", "mode", "exe_path", "game_path", "volume_serial", "file_index", "window_class", "prelaunch_recorded_at");
        if (root.GetProperty("schema_version").GetInt32() != 1 || root.GetProperty("mode").GetString() != "metadata_once" ||
            root.GetProperty("window_class").GetString() != "UnityWndClass") throw new InvalidOperationException("Explicit metadata_once configuration for the evidenced class required.");
        var exe = root.GetProperty("exe_path").GetString()!;
        var game = root.GetProperty("game_path").GetString()!;
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(exe);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(game);
        var module = new ApprovedModule(game, VerifiedWindowsBuild.GameAssemblySha256,
            root.GetProperty("volume_serial").GetUInt32(), root.GetProperty("file_index").GetUInt64(), exe, VerifiedWindowsBuild.ExecutableSha256);
        if (module.FileIndex == 0) throw new InvalidOperationException("Pre-launch file identity required.");
        var privateRoot = Path.Combine(directory, "windows-metadata-private");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(privateRoot);
        var recorded = root.GetProperty("prelaunch_recorded_at").GetDateTimeOffset();
        return new(privateRoot, module, "UnityWndClass", recorded);
    }

    internal static SmokeRequest ReadRequest(string path)
    {
        using var json = ReadBounded(path);
        var root = RequireExactObject(json.RootElement, "schema_version", "stage", "nonce", "pid", "session_id", "bridge_sha256", "game_sha256", "window_class", "checkpoint", "requested_at", "expires_at");
        if (root.GetProperty("schema_version").GetInt32() != 1 || root.GetProperty("stage").GetString() != "metadata" ||
            root.GetProperty("checkpoint").GetString() != "stable_current_session_page")
            throw new InvalidOperationException("Only explicit metadata/current-session stable-page checkpoint requests are accepted; UI is disabled.");
        return new(root.GetProperty("nonce").GetGuid(), root.GetProperty("pid").GetInt32(), root.GetProperty("session_id").GetString()!,
            root.GetProperty("bridge_sha256").GetString()!, root.GetProperty("game_sha256").GetString()!, root.GetProperty("window_class").GetString()!,
            SmokeStage.Metadata, root.GetProperty("requested_at").GetDateTimeOffset(), root.GetProperty("expires_at").GetDateTimeOffset());
    }

    private static JsonElement RequireExactObject(JsonElement root, params string[] names)
    {
        if (root.ValueKind != JsonValueKind.Object) throw new InvalidOperationException("Configuration/request must be an object.");
        var actual = root.EnumerateObject().Select(p => p.Name).ToArray();
        if (actual.Length != names.Length || actual.Distinct(StringComparer.Ordinal).Count() != names.Length ||
            actual.Any(n => !names.Contains(n, StringComparer.Ordinal))) throw new InvalidOperationException("Unexpected/duplicate configuration fields.");
        return root;
    }

    private static JsonDocument ReadBounded(string path)
    {
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is <= 0 or > 4096) throw new InvalidOperationException("Configuration/request size outside 1..4096 bytes.");
        var bytes = new byte[(int)stream.Length];
        stream.ReadExactly(bytes);
        if (stream.ReadByte() != -1) throw new InvalidOperationException("Configuration/request grew during read.");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        return JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 2 });
    }
}
