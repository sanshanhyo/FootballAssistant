using System.Diagnostics;
using System.Text.Json;
using System.Globalization;
using FootballAssistant.OffseasonReader;

// A one-shot producer: stdout only, no on-disk snapshot. Numeric UIDs are explicit
// selectors, not evidence of the active manager or a complete roster.
if ((args.Length != 2 && args.Length != 4) || !uint.TryParse(args[0], out var clubUid) ||
    !int.TryParse(args[1], out var personUid) || personUid < 0 || clubUid == uint.MaxValue)
    return 2;
DateTime start = default, finish = default;
if (args.Length == 4 && (clubUid == 0 ||
    !DateTime.TryParseExact(args[2], "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out start) ||
    !DateTime.TryParseExact(args[3], "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out finish) ||
    !FixtureCalendarLookup.IsValidRange(start, finish))) return 2;
try
{
    var processes = Process.GetProcessesByName("fm");
    try
    {
        if (processes.Length != 1)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { schema = "fa-offseason/0.1", status = "unavailable", reason = "fm_process_not_unique", capturedAt = DateTimeOffset.UtcNow }));
            return 0;
        }
        int pid = processes[0].Id;
        var date = WorldDateLookup.Read(pid);
        PersonResult? person = null;
        DateTimeOffset? personObservedAt = null;
        if (personUid > 0)
        {
            person = PersonLookup.Read(pid, personUid);
            if (person.Status == "experimental") personObservedAt = DateTimeOffset.UtcNow;
        }
        var team = clubUid > 0 ? TeamCandidateLookup.Read(pid, clubUid) : null;
        var schedule = clubUid > 0 ? ScheduleCandidateLookup.Read(pid, clubUid) : null;
        var managerCandidates = clubUid > 0 ? ManagerCandidateLookup.Read(pid, clubUid) : ManagerCandidateLookup.ReadAll(pid);
        var tactic = clubUid > 0 ? TacticCandidateLookup.Read(pid, clubUid) : null;
        var calendar = args.Length == 4 ? FixtureCalendarLookup.Read(pid, clubUid, start, finish) : null;
        if (date.Status != "experimental" && person?.Status != "experimental" &&
            team?.Status != "experimental_candidates_incomplete" && schedule?.Status != "experimental_records_unverified" && managerCandidates?.Status != "experimental_candidates_incomplete" &&
            tactic?.Status != "experimental" && calendar?.Status != "partial" && calendar?.Status != "experimental_loaded_buckets_only")
        {
            Console.WriteLine(JsonSerializer.Serialize(new { schema = "fa-offseason/0.1", status = "unavailable", reason = "no_current_data", capturedAt = DateTimeOffset.UtcNow }));
            return 0;
        }
        Console.WriteLine(JsonSerializer.Serialize(new {
            schema = "fa-offseason/0.1", status = "partial", capturedAt = DateTimeOffset.UtcNow,
            date, player = person is null ? null : new { observedAt = personObservedAt, value = person }, manager = new { status = "unknown", reason = "active_manager_not_identified" },
            managerCandidates, team, schedule, tactic, calendar
        }, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase }));
        return 0;
    }
    finally { foreach (var process in processes) process.Dispose(); }
}
catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
{
    Console.WriteLine(JsonSerializer.Serialize(new { schema = "fa-offseason/0.1", status = "unavailable", reason = "process_unavailable", capturedAt = DateTimeOffset.UtcNow }));
    return 0;
}
