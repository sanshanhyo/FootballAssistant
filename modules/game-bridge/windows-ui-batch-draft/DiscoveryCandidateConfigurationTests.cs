using System.Text.Json;
namespace FootballAssistant.GameBridge;

internal static class DiscoveryCandidateConfigurationTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new Exception("Discovery configuration fixture: " + message); }
    internal static void Run()
    {
        var now = DateTimeOffset.Parse("2026-11-01T00:00:00Z");
        var nonce = Guid.NewGuid();
        var context = new SmokeContext(12, "test-session", new string('a', 64), new string('b', 64), "UnityWndClass", 34);
        var fields = new Dictionary<string, object> {
            ["schema_version"] = 3, ["nonce"] = nonce.ToString("D"), ["pid"] = 12, ["session_id"] = context.Session,
            ["bridge_sha256"] = context.BridgeHash, ["game_sha256"] = context.GameHash, ["window_class"] = context.ConfirmedWindowClass,
            ["checkpoint"] = DiscoveryCandidateConfiguration.Checkpoint, ["panel_index"] = 0, ["focus_path"] = "0/6",
            ["requested_at"] = now.ToString("O"), ["expires_at"] = now.AddSeconds(120).ToString("O") };
        string Json() => JsonSerializer.Serialize(fields);
        void Reject(string json)
        {
            var rejected = false;
            try { _ = DiscoveryCandidateConfiguration.ParseRequest(json); }
            catch (Exception ex) when (ex is InvalidOperationException or JsonException or ArgumentException) { rejected = true; }
            Check(rejected, "malformed/wrong scope request rejected");
        }
        var json = Json(); var parsed = DiscoveryCandidateConfiguration.ParseRequest(json);
        var approval = DiscoveryCandidateConfiguration.TryApproval(parsed, context, now)!;
        Check(approval is not null && approval.ModeEnabled && approval.FocusPath == "0/6" && approval.PanelIndex == 0 && approval.Nonce == nonce, "fixed immutable approval");
        foreach (var pair in new (string Key, object Value)[] {
            ("schema_version",1), ("schema_version","3"), ("nonce",Guid.Empty.ToString("D")), ("nonce",nonce.ToString("N")),
            ("pid",0), ("pid","12"), ("session_id",""), ("session_id",new string('s',129)),
            ("bridge_sha256",new string('A',64)), ("game_sha256",new string('x',64)), ("window_class","Other"),
            ("checkpoint","stable_current_session_page"), ("panel_index",1), ("panel_index","0"), ("focus_path","0/7"),
            ("requested_at","2026-11-01T00:00:00"), ("expires_at",now.ToString("O")), ("expires_at",now.AddSeconds(121).ToString("O")) })
        { var old = fields[pair.Key]; fields[pair.Key] = pair.Value; Reject(Json()); fields[pair.Key] = old; }
        foreach (var token in new[] { "-0", "0.0", "0e0", "null", "true" }) Reject(json.Replace("\"panel_index\":0", "\"panel_index\":" + token));
        Reject(json[..^1] + ",\"panel_index\":0}"); Reject(json[..^1] + ",\"stage\":\"ui_text\"}");
        fields.Remove("focus_path"); Reject(Json()); fields["focus_path"] = "0/6";
        Reject(new string(' ',4097)); Reject("[]"); Reject(json + " trailing");
        foreach (var modified in new[] { parsed with { Nonce = Guid.Empty }, parsed with { Pid = 13 }, parsed with { Session = "other" },
            parsed with { BridgeHash = new string('c',64) }, parsed with { GameHash = new string('c',64) }, parsed with { WindowClass = "Other" },
            parsed with { PanelIndex = 1 }, parsed with { FocusPath = "0/7" }, parsed with { RequestedAt = now.AddSeconds(1) },
            parsed with { ExpiresAt = now }, parsed with { ExpiresAt = now.AddSeconds(121) } })
            Check(DiscoveryCandidateConfiguration.TryApproval(modified, context, now) is null, "direct record mutation cannot authorize");
        Check(DiscoveryCandidateConfiguration.TryApproval(parsed, context with { EntryThread = 0 }, now) is null &&
            DiscoveryCandidateConfiguration.TryApproval(parsed, context, now.AddSeconds(120)) is null, "entry thread and expiry");
        Check(approval.Context == context && approval.FocusPath == "0/6", "caller replacement cannot mutate approval");
        // Real old/new parser incompatibility, including bounded filesystem request reader.
        var directory = Path.Combine(Path.GetTempPath(), "discovery-config-fixture-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            var path = Path.Combine(directory, "request.json"); File.WriteAllText(path, json);
            Check(DiscoveryCandidateConfiguration.ReadRequest(path) == parsed, "bounded disk parser roundtrip");
            var oldRejected = false;
            try { _ = UiCandidateConfiguration.ReadRequest(path); } catch (InvalidOperationException) { oldRejected = true; }
            Check(oldRejected, "old parser rejects discovery request");
            var oldFields = new Dictionary<string, object>(fields) { ["schema_version"] = 1, ["stage"] = "ui_text", ["checkpoint"] = "stable_current_session_page" };
            var oldJson = JsonSerializer.Serialize(oldFields); File.WriteAllText(path, oldJson);
            Check(UiCandidateConfiguration.ReadRequest(path).Stage == SmokeStage.UiText, "old fixture valid for old parser");
            Reject(oldJson);
            File.WriteAllText(path, new string(' ',4097));
            var oversized = false;
            try { _ = DiscoveryCandidateConfiguration.ReadRequest(path); } catch (InvalidOperationException) { oversized = true; }
            Check(oversized, "bounded disk read rejects oversized");
            var absent = false;
            try { _ = DiscoveryCandidateConfiguration.Read(Path.Combine(directory,"candidate.dll")); } catch (FileNotFoundException) { absent = true; }
            Check(absent, "absent config cannot implicitly enable");
            var config = new Dictionary<string, object> { ["schema_version"] = 3, ["mode"] = "ui_discovery_once",
                ["exe_path"] = Path.Combine(directory,"fm.exe"), ["game_path"] = Path.Combine(directory,"GameAssembly.dll"),
                ["volume_serial"] = 1, ["file_index"] = 2, ["window_class"] = "UnityWndClass", ["prelaunch_recorded_at"] = now.ToString("O") };
            var configPath = Path.Combine(directory,DiscoveryCandidateConfiguration.ConfigName);
            File.WriteAllText(configPath,JsonSerializer.Serialize(config));
            var configRead = DiscoveryCandidateConfiguration.Read(Path.Combine(directory,"candidate.dll"));
            Check(configRead.PrivateRoot == Path.Combine(directory,"windows-discovery-private") && configRead.Module.FileIndex == 2,
                "separate private root and prelaunch identity");
            config["schema_version"] = 1; config["mode"] = "ui_once";
            File.WriteAllText(configPath,JsonSerializer.Serialize(config));
            var wrongConfig = false;
            try { _ = DiscoveryCandidateConfiguration.Read(Path.Combine(directory,"candidate.dll")); } catch (InvalidOperationException) { wrongConfig = true; }
            Check(wrongConfig, "old configuration cannot enable discovery");
        }
        finally { Directory.Delete(directory, true); }
    }
}
