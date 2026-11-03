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
    if (!synthetic) ReaderDiagnostics.Stage(ReaderStage.Complete);
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
ReaderDiagnostics.Stage(ReaderStage.Process);
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
        ReaderDiagnostics.Stage(ReaderStage.ModuleHash);
        var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
        // A running executable without its game module is not yet a readable session.
        if (module is null || string.IsNullOrEmpty(module.FileName)) return Emit("no_session");
        using var readContext = NativeReadContext.Open(process, module);
        string binaryHash = readContext.Sha256.ToLowerInvariant();
        bool matched = binaryHash == ExpectedHash;
        binaryIdentity = new { module = "game_plugin.dll", sha256 = binaryHash, matched };
        // Never call any memory lookup for an unknown game binary.
        if (!matched) return Emit("unsupported_binary");
        using var access = Native.OpenProcess(0x1010, false, pid); // QUERY_LIMITED_INFORMATION | VM_READ
        if (access.IsInvalid) return Emit(Marshal.GetLastWin32Error() == 5 ? "process_access_denied" : "read_failed");
        ReaderDiagnostics.Stage(ReaderStage.NativeProfile);
        var nativeProfile = NativeReadProfile.Read(pid, readContext);
        ReaderDiagnostics.Stage(ReaderStage.Manager);
        var manager = NativeManagerLookup.Read(pid, nativeProfile, readContext);
        ReaderDiagnostics.Stage(ReaderStage.Date);
        var date = WorldDateLookup.Read(pid, readContext);
        PersonResult? person = null;
        DateTimeOffset? personObservedAt = null;
        if (personUid > 0)
        {
            ReaderDiagnostics.Stage(ReaderStage.Person);
            person = PersonLookup.Read(pid, personUid, nativeProfile, readContext);
            if (person.Status == "experimental") personObservedAt = DateTimeOffset.UtcNow;
        }
        TeamCandidateResult? team = null;
        if (clubUid > 0)
        {
            ReaderDiagnostics.Stage(ReaderStage.Team);
            team = TeamCandidateLookup.Read(pid, clubUid, nativeProfile, readContext);
        }
        ScheduleCandidateResult? schedule = null;
        if (clubUid > 0)
        {
            ReaderDiagnostics.Stage(ReaderStage.Schedule);
            schedule = ScheduleCandidateLookup.Read(pid, clubUid, readContext);
        }
        ReaderDiagnostics.Stage(ReaderStage.ManagerCandidates);
        var managerCandidates = clubUid > 0 ? ManagerCandidateLookup.Read(pid, clubUid, readContext) : ManagerCandidateLookup.ReadAll(pid, readContext);
        TacticCandidateResult? tactic = null;
        if (clubUid > 0)
        {
            ReaderDiagnostics.Stage(ReaderStage.Tactic);
            tactic = TacticCandidateLookup.Read(pid, clubUid, readContext);
        }
        FixtureCalendarResult? calendar = null;
        if (args.Length == 4)
        {
            ReaderDiagnostics.Stage(ReaderStage.Calendar);
            calendar = FixtureCalendarLookup.Read(pid, clubUid, start, finish, readContext);
        }
        ReaderDiagnostics.Stage(ReaderStage.Revalidate);
        var managerAfter = NativeManagerLookup.Read(pid, nativeProfile, readContext);
        if (!NativeManagerResult.SameBinding(manager, managerAfter))
            manager = new NativeManagerResult("unavailable", manager.Status == "available" || managerAfter.Status == "available" ? "changed_during_capture" : managerAfter.Reason ?? manager.Reason);
        if (!readContext.IsCurrent(process) || process.HasExited || new DateTimeOffset(process.StartTime.ToUniversalTime()) != started) return Emit("no_session");
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

// This side channel contains only a fixed schema and allowlisted stage names.
// No argument values, paths, identifiers, timings, or exception text are logged.
internal enum ReaderStage
{
    Process, ModuleHash, NativeProfile, Manager, Date, Person, Team, Schedule,
    ManagerCandidates, Tactic, Calendar, Revalidate, Complete
}
internal static class ReaderDiagnostics
{
    internal static void Stage(ReaderStage value)
    {
        string? stage = value switch
        {
            ReaderStage.Process => "process", ReaderStage.ModuleHash => "module_hash",
            ReaderStage.NativeProfile => "native_profile", ReaderStage.Manager => "manager",
            ReaderStage.Date => "date", ReaderStage.Person => "person", ReaderStage.Team => "team",
            ReaderStage.Schedule => "schedule", ReaderStage.ManagerCandidates => "manager_candidates",
            ReaderStage.Tactic => "tactic", ReaderStage.Calendar => "calendar",
            ReaderStage.Revalidate => "revalidate", ReaderStage.Complete => "complete", _ => null
        };
        if (stage is null) return;
        try
        {
            Console.Error.WriteLine(JsonSerializer.Serialize(new { schema = "fa-reader-stage/1", stage }));
            Console.Error.Flush();
        }
        // A closed diagnostics pipe must not change the stdout producer protocol.
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }
}

internal static class Native
{
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);
}
