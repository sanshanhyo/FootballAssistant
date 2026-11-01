using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace FootballAssistant.OffseasonReader;

// Experimental candidate: phase and player association are unknown. Position and role
// labels follow FMMatchLens TacticalFormationDecoder; its MIT license is retained in
// ../match-reader/vendor/LICENSE. No game functions are called.
public static class TacticCandidateLookup
{
private const string expectedHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
public static TacticCandidateResult Read(int pid, uint targetClubUid)
{
if (pid <= 0 || targetClubUid == 0 || targetClubUid == uint.MaxValue) return new("invalid_input");
try
{
    using var process = Process.GetProcessById(pid);
    if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("wrong_process");
    var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
    if (module is null || string.IsNullOrEmpty(module.FileName)) { return new("module_unavailable"); }
    using (var file = File.OpenRead(module.FileName))
    using (var sha = SHA256.Create())
        if (Convert.ToHexString(sha.ComputeHash(file)) != expectedHash) return new("unsupported_binary");
    using var memory = new SafeProcessHandle(OpenProcess(0x1010, false, pid));
    if (memory.IsInvalid) { return new("process_unavailable"); }
    var clock = Stopwatch.StartNew();
    long image = module.BaseAddress.ToInt64();
    var header = ReadHeader(memory, image);
    if (header is null) { return new("manager_range_unavailable"); }
    int count = checked((int)((header.Value.End - header.Value.Begin) / 8));
    var candidates = new List<Candidate>();
    var inspected = new List<(long Slot, long Object, CandidateRead Result)>();
    for (int i = 0; i < count; i++)
    {
        if (clock.ElapsedMilliseconds >= 2000 || !Read64(memory, header.Value.Begin + i * 8, out long obj))
        { return new("unavailable"); }
        if (obj == 0) { inspected.Add((header.Value.Begin + i * 8L, 0, new("empty", null))); continue; }
        var result = ReadCandidate(memory, image, obj, targetClubUid, candidates.Count < 4);
        if (result.Status is "unavailable" or "unsupported_type" or "unsupported_contract" or "unsupported_team" or "unsupported_club") return new("unavailable");
        if (result.Status == "too_many_matches") { return new("unavailable"); }
        inspected.Add((header.Value.Begin + i * 8L, obj, result));
        if (result.Candidate is not null) candidates.Add(result.Candidate);
        if (candidates.Count > 4) { return new("unavailable"); }
    }
    if (ReadHeader(memory, image) != header || clock.ElapsedMilliseconds >= 2000)
    { return new("changed_during_read"); }
    foreach (var entry in inspected)
    {
        if (!Read64(memory, entry.Slot, out long current) || current != entry.Object) return new("changed_during_read");
        if (current != 0 && ReadCandidate(memory, image, current, targetClubUid, true) != entry.Result) return new("changed_during_read");
    }
    if (ReadHeader(memory, image) != header || clock.ElapsedMilliseconds >= 2000)
    { return new("changed_during_read"); }
    if (candidates.Count != 1) return new("candidate_not_unique");
    var selected = candidates[0];
    if (selected.Relation != "backref_matches_team") return new("unavailable");
    var players = TacticPlayerAssociations.Read(memory, image, selected.Team, selected.Slot);
    var treeRoles = TacticOutRoleReader.Read(memory, image, selected.Team, pid, process.StartTime.ToUniversalTime().Ticks);
    if (ReadCandidate(memory, image, selected.Object, targetClubUid).Candidate != selected ||
        ReadHeader(memory, image) != header || clock.ElapsedMilliseconds >= 2000)
        return new("changed_during_read");
    foreach (var entry in inspected)
        if (!Read64(memory, entry.Slot, out long current) || current != entry.Object) return new("changed_during_read");
    if (ReadHeader(memory, image) != header || clock.ElapsedMilliseconds >= 2000) return new("changed_during_read");
    return new("experimental", "unknown", selected.PositionMasks.Split(','), selected.RolesDuties.Split(','), DateTimeOffset.UtcNow, players, treeRoles?.SecondRoles, "unknown", "RolesDuties comes from a template candidate and may not track edits. FirstTargetRoles is a separate experimental tree candidate; active selection and unsaved edits remain unverified. observedAt is read time only. Generation is valid only within this reader process and may not detect address reuse.", treeRoles?.FirstRoles, treeRoles?.Generation, treeRoles?.MentalityId);
}
catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException)
{ return new("unavailable"); }
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
    if (!Read64(p, team + 0xA0, out long container) || container <= 0 || !Read64(p, container + 0xD0, out long candidate)) return new("unavailable", null);
    long back = 0;
    if (candidate != 0 && !Read64(p, candidate + 0xA0, out back)) return new("unavailable", null);
    string relation = candidate == 0 ? "null" : back == team ? "backref_matches_team" : "other_or_unknown";
    if (candidate == 0 || back != team) return new("candidate", new(obj, contract, team, club, container, candidate, back, relation, "", "", ""));
    if (!ReadBytes(p, candidate, 22, out byte[] values)) return new("unavailable", null);
    var decoded = Decode(values)!;
    return new("candidate", new(obj, contract, team, club, container, candidate, back, relation, string.Join(",", decoded.Positions), string.Join(",", decoded.RolesDuties), Convert.ToHexString(values)));
}
// Pure decoding; no game process access. Invalid lengths cannot produce a candidate.
public static TacticDecoded? Decode(byte[]? values)
{
    if (values is null || values.Length != 22) return null;
    uint[] table = { 0x1, 0, 0x4, 0x200010, 0x10, 0x100010, 0x8, 0x20, 0x200080, 0x80, 0x100080, 0x40, 0x100, 0x200400, 0x400, 0x100400, 0x200, 0x800, 0x202000, 0x2000, 0x102000, 0x1000, 0x800, 0x204000, 0x4000, 0x104000, 0x1000 };
    string[] roleTable = { "Goalkeeper / Defend", "Central Defender / Defend", "Full-Back / Support", "Wing-Back / Support", "Defensive Midfielder / Defend", "Central Midfielder / Support", "Wide Midfielder / Support", "Winger / Support", "Attacking Midfielder / Attack", "Deep-Lying Forward / Attack", "Centre-Forward / Attack", "Ball-Playing Goalkeeper / Support", "unknown / Defend", "Libero / Defend", "Deep-Lying Playmaker / Support", "Box-to-Box Midfielder / Support", "Advanced Playmaker / Attack", "Target Man / Attack", "Poacher / Attack", "Complete Forward / Attack", "Ball-Playing Defender / Defend", "Inside Forward / Attack", "Ball-Winning Midfielder / Defend", "No-Nonsense Centre-Back / Defend", "Defensive Winger / Support", "Channel Forward / Attack", "Trequartista / Attack", "Anchor / Defend", "Half-Back / Defend", "No-Nonsense Full-Back / Defend", "Enganche / Attack", "Advanced Wing-Back / Attack", "Regista / Support", "False Nine / Attack", "Shadow Striker / Attack", "Wide Target Forward / Attack", "Wide Playmaker / Support", "Inverted Wing-Back / Defend", "Wide Forward / Attack", "Box-to-Box Playmaker / Support", "Mezzala / Attack", "Inverted Winger / Support", "Wide Central Midfielder / Support", "Segundo Volante / Support", "Wide Centre-Back / Defend", "Inverted Full-Back / Defend", "No-Nonsense Goalkeeper / Defend", "Overlapping Centre-Back / Attack", "Playmaking Wing-Back / Support", "Channel Midfielder / Attack", "Midfield Playmaker / Support" };
    var masks = new string[11];
    var roles = new string[11];
    for (int i = 0; i < masks.Length; i++) {
        int raw = BitConverter.ToUInt16(values, i * 2) & 0x3f;
        int signed = raw >= 32 ? raw - 64 : raw;
        int index = signed + 15;
        masks[i] = index < 0 || index >= table.Length || table[index] == 0 ? "unknown" : $"0x{table[index]:X}";
        int roleRaw = (BitConverter.ToUInt16(values, i * 2) >> 6) & 0x7f;
        int roleSigned = roleRaw >= 64 ? roleRaw - 128 : roleRaw;
        int roleIndex = roleSigned + 31;
        roles[i] = roleIndex < 0 || roleIndex >= roleTable.Length ? "unknown" : roleTable[roleIndex];
    }
    return new TacticDecoded(masks, roles);
}
static bool Read32(SafeProcessHandle p, long a, out int v) { v = 0; if (!ReadBytes(p, a, 4, out var b)) return false; v = BitConverter.ToInt32(b); return true; }
static bool ReadU32(SafeProcessHandle p, long a, out uint v) { v = 0; if (!ReadBytes(p, a, 4, out var b)) return false; v = BitConverter.ToUInt32(b); return true; }
static bool Read64(SafeProcessHandle p, long a, out long v) { v = 0; if (!ReadBytes(p, a, 8, out var b)) return false; v = BitConverter.ToInt64(b); return true; }
static bool ReadBytes(SafeProcessHandle p, long a, int n, out byte[] b) { b = new byte[n]; return a > 0 && ReadProcessMemory(p, (nint)a, b, n, out var read) && read == (nuint)n; }
[DllImport("kernel32.dll", SetLastError = true)] static extern nint OpenProcess(uint access, bool inherit, int pid);
[DllImport("kernel32.dll", SetLastError = true)] static extern bool ReadProcessMemory(SafeProcessHandle p, nint address, byte[] buffer, int size, out nuint read);
readonly record struct Header(long Manager, long Begin, long End);
sealed record Candidate(long Object, long Contract, long Team, long Club, long Container, long Slot, long Backref, string Relation, string PositionMasks, string RolesDuties, string RawCheck);
readonly record struct CandidateRead(string Status, Candidate? Candidate);
private sealed class SafeProcessHandle : Microsoft.Win32.SafeHandles.SafeHandleZeroOrMinusOneIsInvalid
{
    public SafeProcessHandle(nint handle) : base(true) { SetHandle(handle); }
    protected override bool ReleaseHandle() => CloseHandle(handle);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(nint handle);
}







}
public sealed record TacticCandidateResult(string Status, string? Phase = null, IReadOnlyList<string>? PositionMasks = null, IReadOnlyList<string>? RolesDuties = null, DateTimeOffset? ObservedAt = null, IReadOnlyList<TacticPlayerCandidate>? Players = null, IReadOnlyList<string>? SecondPhaseRoles = null, string? ContentFreshness = null, string? Limitation = null, IReadOnlyList<string>? FirstTargetRoles = null, string? Generation = null, byte? TargetMentalityId = null);



public sealed record TacticDecoded(IReadOnlyList<string> Positions, IReadOnlyList<string> RolesDuties);










