using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace FootballAssistant.OffseasonReader;

// Experimental two-record candidate only; not a full schedule or active-manager identification.
public static class ScheduleCandidateLookup
{
private const string expectedHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
public static ScheduleCandidateResult Read(int pid, uint targetClubUid)
{
if (pid <= 0 || targetClubUid is 0 or uint.MaxValue) return new("invalid_input");
try
{
    using var process = Process.GetProcessById(pid);
    if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("wrong_process");
    var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
    if (module is null || string.IsNullOrEmpty(module.FileName)) { return new("module_unavailable"); }
    using (var file = File.OpenRead(module.FileName))
    using (var sha = SHA256.Create())
        if (Convert.ToHexString(sha.ComputeHash(file)) != expectedHash) { return new("unsupported_binary"); }
    using var memory = new SafeProcessHandle(OpenProcess(0x1010, false, pid));
    if (memory.IsInvalid) { return new("process_read_unavailable"); }
    var clock = Stopwatch.StartNew();
    long image = module.BaseAddress.ToInt64();
    var header = ReadHeader(memory, image);
    if (header is null) { return new("manager_range_unavailable"); }
    int count = checked((int)((header.Value.End - header.Value.Begin) / 8));
    var candidates = new List<Candidate>();
    for (int i = 0; i < count; i++)
    {
        if (clock.ElapsedMilliseconds >= 2000 || !Read64(memory, header.Value.Begin + i * 8, out long obj))
        { return new("range_changed_or_unreadable"); }
        if (obj == 0) continue;
        var result = ReadCandidate(memory, image, obj, targetClubUid, candidates.Count < 4);
        if (result.Status is "unavailable" or "too_many_matches" or "unsupported_type" or "unsupported_contract" or "unsupported_team" or "unsupported_club") { return new("candidate_unavailable"); }
        if (result.Candidate is not null) candidates.Add(result.Candidate);
    }
    // A single matching manager is required; no assumption about active manager selection.
    if (candidates.Count != 1) { return new("candidate_not_unique"); }
    var candidate = candidates[0];
    if (!Read64(memory, candidate.Team + 0xA0, out long schedule) || schedule <= 0 ||
        !ReadBytes(memory, schedule, 80, out var first) || !ReadBytes(memory, schedule, 80, out var second))
    { return new("schedule_unavailable"); }
    var opponent0 = ReadOpponent(memory, image, first, 0);
    var opponent1 = ReadOpponent(memory, image, first, 40);
    if (!first.SequenceEqual(second) || ReadHeader(memory, image) != header ||
        ReadCandidate(memory, image, candidate.Object, targetClubUid).Candidate != candidate ||
        !Read64(memory, candidate.Team + 0xA0, out long afterSchedule) || schedule != afterSchedule ||
        !ReadBytes(memory, schedule, 80, out var third) || !first.SequenceEqual(third) ||
        ReadOpponent(memory, image, third, 0) != opponent0 || ReadOpponent(memory, image, third, 40) != opponent1 || clock.ElapsedMilliseconds >= 2000)
    { return new("changed_during_read"); }
    return new("experimental_records_unverified", new[] { Decode(first, 0, opponent0), Decode(first, 40, opponent1) }, DateTimeOffset.UtcNow);
}
catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException)
{ return new("unavailable"); }
}

static ScheduleCandidateRecord Decode(byte[] data, int offset, Opponent? opponent)
{
    uint raw = BitConverter.ToUInt32(data, offset + 0x18);
    int year = (int)(raw >> 16), day = (int)(raw & 0x1FF);
    string? date = null;
    if (year >= 1901 && year <= 9999 && day >= 1 && day <= (DateTime.IsLeapYear(year) ? 366 : 365))
        date = new DateTime(year, 1, 1).AddDays(day - 1).ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
    return new(date, data[offset + 0x20], data[offset + 0x21], data[offset + 0x22], opponent is null ? null : new(opponent.TeamUid, opponent.ClubUid, opponent.ClubShortName));
}
// The candidate opponent slot is accepted only after exact team/club type checks.
// An unreadable or unsupported object remains unknown and never exposes addresses.
static Opponent? ReadOpponent(SafeProcessHandle p, long image, byte[] record, int offset)
{
    long team = BitConverter.ToInt64(record, offset + 0x10);
    if (team <= 0 || !Read64(p, team, out long teamType) || teamType != image + 0x04CE1108 ||
        !ReadU32(p, team + 0x0C, out uint teamUid) || teamUid is 0 or uint.MaxValue ||
        !Read64(p, team + 0x30, out long club) || club <= 0 ||
        !Read64(p, club, out long clubType) || clubType != image + 0x04CDA1F8 ||
        !ReadU32(p, club + 0x0C, out uint clubUid) || clubUid is 0 or uint.MaxValue ||
        !ReadInlineName(p, club, 0xC8, out string name) || string.IsNullOrWhiteSpace(name)) return null;
    return new(teamUid, clubUid, name);
}
static Header? ReadHeader(SafeProcessHandle p, long image)
{
    if (!Read64(p, image + 0x056F3008, out long manager) || manager <= 0 ||
        !Read64(p, manager, out long v0) || v0 != image + 0x04E2D678 ||
        !Read64(p, manager + 8, out long v1) || v1 != image + 0x04E2D688 ||
        !Read64(p, manager + 0x18, out long begin) || !Read64(p, manager + 0x20, out long end) ||
        begin <= 0 || end < begin || (end - begin) % 8 != 0 || (end - begin) / 8 > 16) return null;
    return new(manager, begin, end);
}
static CandidateRead ReadCandidate(SafeProcessHandle p, long image, long obj, uint target, bool allowName = true)
{
    long person = obj + 0x440;
    if (!Read64(p, obj, out long vbtable) || !Read64(p, person, out long type) || !Read32(p, person - 4, out int displacement)) return new("unavailable", null);
    // Unknown subclasses remain unknown; no fixed layout is applied to them.
    if (vbtable != image + 0x04CC086C || type != image + 0x04CC08D8 || displacement != 0) return new("unsupported_type", null);
    if (!Read64(p, person + 0xA8, out long contract)) return new("unavailable", null);
    if (contract == 0) return new("no_contract", null);
    if (!Read64(p, contract, out long contractType) || !Read64(p, contract + 8, out long owner)) return new("unavailable", null);
    if (contractType != image + 0x04B00AE8 || owner != person) return new("unsupported_contract", null);
    if (!Read64(p, contract + 0x10, out long team)) return new("unavailable", null);
    if (team == 0) return new("no_team", null);
    if (!Read64(p, team, out long teamType)) return new("unavailable", null);
    if (teamType != image + 0x04CE1108) return new("unsupported_team", null);
    if (!Read64(p, team + 0x30, out long club)) return new("unavailable", null);
    if (club == 0) return new("no_club", null);
    if (!Read64(p, club, out long clubType) || !ReadU32(p, club + 0x0C, out uint clubUid)) return new("unavailable", null);
    if (clubType != image + 0x04CDA1F8) return new("unsupported_club", null);
    if (clubUid != target) return new("other_club", null);
    if (!allowName) return new("too_many_matches", null);
    if (!ReadU32(p, person + 0x0C, out uint uid) || uid is 0 or uint.MaxValue ||
        !TryName(p, person, 0x50, out var first) || !TryName(p, person, 0x58, out var last) || !TryName(p, person, 0x60, out var common) ||
        !ReadInlineName(p, club, 0xC8, out var clubName)) return new("unavailable", null);
    var name = string.IsNullOrWhiteSpace(common) ? $"{first} {last}".Trim() : common;
    if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(clubName)) return new("unavailable", null);
    return new("candidate", new(obj, contract, team, club, uid, name, clubName));
}
static bool TryName(SafeProcessHandle p, long owner, int offset, out string result)
{
    result = ""; if (!Read64(p, owner + offset, out long o)) return false;
    if (o == 0) return true;
    return Read64(p, o, out long buffer) && buffer > 0 && Text(p, buffer + 4, out result);
}
static bool ReadInlineName(SafeProcessHandle p, long owner, int offset, out string result)
{
    result = ""; return Read64(p, owner + offset, out long o) && o > 0 && Text(p, o + 4, out result);
}
static bool Text(SafeProcessHandle p, long address, out string result)
{
    result = ""; if (!ReadBytes(p, address, 64, out var bytes)) return false;
    int n = Array.IndexOf(bytes, (byte)0); if (n < 0) return false;
    try { result = new UTF8Encoding(false, true).GetString(bytes, 0, n).Trim(); return true; }
    catch (DecoderFallbackException) { return false; }
}
static bool Read32(SafeProcessHandle p, long a, out int v) { v = 0; if (!ReadBytes(p, a, 4, out var b)) return false; v = BitConverter.ToInt32(b); return true; }
static bool ReadU32(SafeProcessHandle p, long a, out uint v) { v = 0; if (!ReadBytes(p, a, 4, out var b)) return false; v = BitConverter.ToUInt32(b); return true; }
static bool Read64(SafeProcessHandle p, long a, out long v) { v = 0; if (!ReadBytes(p, a, 8, out var b)) return false; v = BitConverter.ToInt64(b); return true; }
static bool ReadBytes(SafeProcessHandle p, long a, int n, out byte[] b) { b = new byte[n]; return a > 0 && ReadProcessMemory(p, (nint)a, b, n, out var read) && read == (nuint)n; }
[DllImport("kernel32.dll", SetLastError = true)] static extern nint OpenProcess(uint access, bool inherit, int pid);
[DllImport("kernel32.dll", SetLastError = true)] static extern bool ReadProcessMemory(SafeProcessHandle p, nint address, byte[] buffer, int size, out nuint read);
readonly record struct Header(long Manager, long Begin, long End);
sealed record Candidate(long Object, long Contract, long Team, long Club, uint Uid, string Name, string ClubName);
readonly record struct CandidateRead(string Status, Candidate? Candidate);
sealed class SafeProcessHandle : Microsoft.Win32.SafeHandles.SafeHandleZeroOrMinusOneIsInvalid
{
    public SafeProcessHandle(nint handle) : base(true) { SetHandle(handle); }
    protected override bool ReleaseHandle() => CloseHandle(handle);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(nint handle);
}


sealed record Opponent(uint TeamUid, uint ClubUid, string ClubShortName);


}

public sealed record ScheduleCandidateResult(string Status, IReadOnlyList<ScheduleCandidateRecord>? Records = null, DateTimeOffset? ObservedAt = null);
public sealed record ScheduleCandidateRecord(string? Date, byte FirstScoreRaw, byte SecondScoreRaw, byte VenueRaw, ScheduleCandidateOpponent? Opponent);
public sealed record ScheduleCandidateOpponent(uint TeamUid, uint ClubUid, string ClubShortName);


