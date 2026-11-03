using System.Diagnostics;
using System.Text.Json;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using FootballAssistant.OffseasonReader;

// One-shot, read-only producer. Process-session identity is NOT a game-save ID.
const string Protocol = "fa-offseason/0.1";
const string ExpectedHash = "bc940e472418fc5c214208d7cf30fecf600f689b6f9d71c11ba19a2df0fe057f";
var producer = new { id = "footballassistant.offseason-reader", version = "0.1.0", protocol = Protocol };
var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
object? processIdentity = null;
object? binaryIdentity = null;
int Emit(string state, Dictionary<string, object?>? values = null, bool synthetic = false)
{
    var output = values ?? new Dictionary<string, object?>();
    output["schema"] = Protocol;
    output["producer"] = producer;
    output["synthetic"] = synthetic;
    output["status"] = state == "fresh_partial" ? "partial" : state == "offline_self_test" ? state : "unavailable";
    output["state"] = state;
    output["reason"] = state;
    output["capturedAt"] = DateTimeOffset.UtcNow;
    output["process"] = processIdentity;
    output["binary"] = binaryIdentity;
    Console.WriteLine(JsonSerializer.Serialize(output, options));
    return 0;
}
// Offline CI paths are handled before platform checks or any process enumeration.
if (args.Length == 1 && args[0] == "--version")
{
    Console.WriteLine(JsonSerializer.Serialize(new { schema = "fa-offseason-producer/1", status = "version", producer, synthetic = true }, options));
    return 0;
}
if (args.Length == 1 && args[0] == "--self-test") return Emit("offline_self_test", synthetic: true);
if ((args.Length != 2 && args.Length != 4) || !uint.TryParse(args[0], out var clubUid) ||
    !int.TryParse(args[1], out var personUid) || personUid < 0 || clubUid == uint.MaxValue)
    return 2;
DateTime start = default, finish = default;
if (args.Length == 4 && (clubUid == 0 ||
    !DateTime.TryParseExact(args[2], "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out start) ||
    !DateTime.TryParseExact(args[3], "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out finish) ||
    !FixtureCalendarLookup.IsValidRange(start, finish))) return 2;
if (!OperatingSystem.IsWindows() || !Environment.Is64BitProcess) return Emit("read_failed");
try
{
    var processes = Process.GetProcessesByName("fm");
    try
    {
        if (processes.Length == 0) return Emit("fm_not_running");
        if (processes.Length != 1) return Emit("multiple_process");
        var process = processes[0];
        int pid = process.Id;
        var started = new DateTimeOffset(process.StartTime.ToUniversalTime());
        var startedAt = started.ToString("O", CultureInfo.InvariantCulture);
        var sessionId = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"{pid}:{startedAt}"))).ToLowerInvariant();
        processIdentity = new { pid, startedAt, sessionId, identityKind = "process_start", saveIdentity = "unknown" };
        var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
        // A running executable without its game module is not yet a readable session.
        if (module is null || string.IsNullOrEmpty(module.FileName)) return Emit("no_session");
        string binaryHash;
        using (var file = File.OpenRead(module.FileName))
            binaryHash = Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant();
        bool matched = binaryHash == ExpectedHash;
        binaryIdentity = new { module = "game_plugin.dll", sha256 = binaryHash, matched };
        // Never call any memory lookup for an unknown game binary.
        if (!matched) return Emit("unsupported_binary");
        using var access = Native.OpenProcess(0x1010, false, pid); // QUERY_LIMITED_INFORMATION | VM_READ
        if (access.IsInvalid) return Emit(Marshal.GetLastWin32Error() == 5 ? "process_access_denied" : "read_failed");
        var nativeProfile = NativeReadProfile.Read(pid);
        var manager = NativeManagerLookup.Read(pid, nativeProfile);
        var date = WorldDateLookup.Read(pid);
        PersonResult? person = null;
        DateTimeOffset? personObservedAt = null;
        if (personUid > 0)
        {
            person = PersonLookup.Read(pid, personUid, nativeProfile);
            if (person.Status == "experimental") personObservedAt = DateTimeOffset.UtcNow;
        }
        var team = clubUid > 0 ? TeamCandidateLookup.Read(pid, clubUid, nativeProfile) : null;
        var schedule = clubUid > 0 ? ScheduleCandidateLookup.Read(pid, clubUid) : null;
        var managerCandidates = clubUid > 0 ? ManagerCandidateLookup.Read(pid, clubUid) : ManagerCandidateLookup.ReadAll(pid);
        var tactic = clubUid > 0 ? TacticCandidateLookup.Read(pid, clubUid) : null;
        var calendar = args.Length == 4 ? FixtureCalendarLookup.Read(pid, clubUid, start, finish) : null;
        var managerAfter = NativeManagerLookup.Read(pid, nativeProfile);
        if (!NativeManagerResult.SameBinding(manager, managerAfter))
            manager = new NativeManagerResult("unavailable", manager.Status == "available" || managerAfter.Status == "available" ? "changed_during_capture" : managerAfter.Reason ?? manager.Reason);
        if (process.HasExited || new DateTimeOffset(process.StartTime.ToUniversalTime()) != started) return Emit("no_session");
        if (manager.Status != "available" && date.Status != "experimental" && person?.Status != "experimental" &&
            team?.Status != "experimental_candidates_incomplete" && schedule?.Status != "experimental_records_unverified" && managerCandidates?.Status != "experimental_candidates_incomplete" &&
            tactic?.Status != "experimental" && calendar?.Status != "partial" && calendar?.Status != "experimental_loaded_buckets_only")
            return Emit("no_data", new Dictionary<string, object?> { ["manager"] = manager, ["nativeProfile"] = nativeProfile });
        return Emit("fresh_partial", new Dictionary<string, object?> {
            ["date"] = date,
            ["player"] = person is null ? null : new { observedAt = personObservedAt, value = person },
            ["manager"] = manager, ["nativeProfile"] = nativeProfile,
            ["managerCandidates"] = managerCandidates, ["team"] = team, ["schedule"] = schedule,
            ["tactic"] = tactic, ["calendar"] = calendar,
        });
    }
    finally { foreach (var process in processes) process.Dispose(); }
}
catch (UnauthorizedAccessException) { return Emit("process_access_denied"); }
catch (System.Security.SecurityException) { return Emit("process_access_denied"); }
catch (System.ComponentModel.Win32Exception ex) { return Emit(ex.NativeErrorCode == 5 ? "process_access_denied" : "read_failed"); }
catch (InvalidOperationException) { return Emit("no_session"); }
catch (Exception ex) when (ex is IOException or ArgumentException or NotSupportedException or OverflowException or CryptographicException)
{ return Emit("read_failed"); }

internal static class Native
{
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);
}
