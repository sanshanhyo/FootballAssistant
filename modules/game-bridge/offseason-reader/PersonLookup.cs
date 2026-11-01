using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace FootballAssistant.OffseasonReader;

// A single bounded lookup in the experimentally located PERSON table. It is
// not a roster API and does not prove team membership or capture freshness.
public static class PersonLookup
{
    private const string ExpectedHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
    public static PersonResult Read(int pid, int uid)
    {
        if (pid <= 0 || uid <= 0) return new("invalid_input", null, null);
        try
        {
            using var process = Process.GetProcessById(pid);
            if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("wrong_process", null, null);
            var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
            if (module is null || string.IsNullOrEmpty(module.FileName)) return new("module_unavailable", null, null);
            using (var stream = File.OpenRead(module.FileName))
            using (var sha = SHA256.Create())
                if (Convert.ToHexString(sha.ComputeHash(stream)) != ExpectedHash) return new("unsupported_binary", null, null);
            using var memory = new SafeProcessHandle(OpenProcess(0x1010, false, pid));
            if (memory.IsInvalid) return new("process_unavailable", null, null);
            var clock = Stopwatch.StartNew();
            long image = module.BaseAddress.ToInt64();
            var header = ReadHeader(memory, image);
            if (header is null) return new("table_unavailable", null, null);
            long low = 0, high = (header.Value.End - header.Value.Begin) / 8 - 1, item = 0, index = -1;
            int probes = 0;
            while (low <= high && probes < 20 && clock.ElapsedMilliseconds < 2000)
            {
                long mid = low + (high - low) / 2;
                if (!Read64(memory, header.Value.Begin + mid * 8, out long candidate) || candidate <= 0 ||
                    !Read32(memory, candidate + 0x0C, out int current) || current <= 0) return new("unavailable", null, null);
                probes++;
                if (current == uid) { item = candidate; index = mid; break; }
                if (current < uid) low = mid + 1; else high = mid - 1;
            }
            // No result is evidence of absence: ordering and concurrent mutation
            // have not been independently established for every session.
            if (item == 0) return new("not_confirmed", null, null);
            if (!ReadName(memory, item, 0x50, out string first) || !ReadName(memory, item, 0x58, out string last) ||
                !ReadName(memory, item, 0x60, out string common) || clock.ElapsedMilliseconds >= 2000)
                return new("unavailable", null, null);
            // Only the exact validated ACTUAL_PLAYER PERSON virtual-base vtable
            // permits the upstream -0x288 adjustment for this build.
            if (!Read64(memory, item, out long personVtable)) return new("unavailable", null, null);
            PlayerDetails? details = null;
            CandidateAffiliation? affiliation = null;
            ContractSnapshot? contract = null;
            if (personVtable == image + 0x04D27758 && item >= 0x288)
            {
                details = ReadDetails(memory, item, item - 0x288);
                affiliation = ReadAffiliation(memory, image, item, item - 0x288);
                contract = ReadContract(memory, image, item, item - 0x288);
            }
            var after = ReadHeader(memory, image);
            if (after != header || !Read64(memory, header.Value.Begin + index * 8, out long same) || same != item ||
                !Read32(memory, item + 0x0C, out int sameUid) || sameUid != uid ||
                !Read64(memory, item, out long sameVtable) || sameVtable != personVtable ||
                (details is not null && ReadDetails(memory, item, item - 0x288) != details) ||
                (affiliation is not null && ReadAffiliation(memory, image, item, item - 0x288) != affiliation) ||
                (contract is not null && ReadContract(memory, image, item, item - 0x288) != contract) ||
                clock.ElapsedMilliseconds >= 2000)
                return new("changed_during_read", null, null);
            var display = string.IsNullOrWhiteSpace(common) ? $"{first} {last}".Trim() : common;
            return string.IsNullOrWhiteSpace(display) ? new("unavailable", null, null) : new("experimental", uid, display, details, affiliation, contract?.Value);
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException)
        { return new("unavailable", null, null); }
    }

    private static Header? ReadHeader(SafeProcessHandle p, long image)
    {
        if (!Read64(p, image + 0x057036D0 + 0x68, out var table) || table <= 0 ||
            !Read64(p, table, out var vtable) || vtable != image + 0x04CA5278 ||
            !ReadBytes(p, table + 0x5C, 1, out var flags) || (flags[0] & 1) == 0 ||
            !ReadBytes(p, table + 0xA0, 1, out var dirty) || dirty[0] != 0 ||
            !Read64(p, table + 0x80, out var vector) || vector <= 0 ||
            !Read64(p, vector, out var baseBegin) || !Read64(p, vector + 8, out var baseEnd) ||
            baseBegin <= 0 || baseEnd <= baseBegin || (baseEnd - baseBegin) % 8 != 0 || (baseEnd - baseBegin) / 8 > 1_048_575 ||
            !Read64(p, table + 0x88, out var begin) || !Read64(p, table + 0x90, out var end) ||
            begin <= 0 || end < begin || (end - begin) % 8 != 0 || (end - begin) / 8 > 1_048_575) return null;
        return new(table, vector, baseBegin, baseEnd, begin, end);
    }
    private static bool ReadName(SafeProcessHandle p, long person, int offset, out string value)
    {
        value = "";
        if (!Read64(p, person + offset, out long obj)) return false;
        if (obj == 0) return true;
        if (!Read64(p, obj, out long buffer) || buffer <= 0 || !ReadBytes(p, buffer + 4, 64, out var bytes)) return false;
        int end = Array.IndexOf(bytes, (byte)0);
        if (end < 0) return false;
        try { value = new UTF8Encoding(false, true).GetString(bytes, 0, end).Trim(); return true; }
        catch (DecoderFallbackException) { return false; }
    }
    private static PlayerDetails ReadDetails(SafeProcessHandle p, long person, long player)
    {
        static byte? Attribute(SafeProcessHandle memory, long address)
        {
            return ReadBytes(memory, address, 1, out var raw) ? PlayerValueDecoder.Attribute(raw[0]) : null;
        }
        int? height = null;
        if (ReadBytes(p, player + 0x22E, 2, out var h))
        {
            var cm = BitConverter.ToInt16(h, 0);
            height = PlayerValueDecoder.Height(cm);
        }
        string? birthday = null;
        if (ReadBytes(p, person + 0x88, 4, out var rawDate))
        {
            birthday = PlayerValueDecoder.Date(BitConverter.ToUInt32(rawDate, 0));
        }
        return new(Attribute(p, player + 0x174), Attribute(p, player + 0x16A),
            Attribute(p, player + 0x170), Attribute(p, player + 0x186), height, birthday);
    }
    private static CandidateAffiliation? ReadAffiliation(SafeProcessHandle p, long image, long person, long player)
    {
        // One validated sample supports an affiliation, not managed-team or
        // loan semantics. Exact types fail closed for other valid subclasses.
        if (!Read32(p, person - 4, out int displacement) || displacement != 0 ||
            !Read64(p, player + 0x130, out long team) || team <= 0 ||
            !Read64(p, team, out long teamType) || teamType != image + 0x04CE1108 ||
            !Read64(p, team + 0x30, out long club) || club <= 0 ||
            !Read64(p, club, out long clubType) || clubType != image + 0x04CDA1F8 ||
            !ReadBytes(p, team + 0x0C, 4, out var teamId) || !ReadBytes(p, club + 0x0C, 4, out var clubId) ||
            !Read64(p, club + 0xC8, out long nameObject) || nameObject <= 0 ||
            !ReadBytes(p, nameObject + 4, 64, out var nameBytes)) return null;
        uint teamUid = BitConverter.ToUInt32(teamId, 0), clubUid = BitConverter.ToUInt32(clubId, 0);
        return PlayerValueDecoder.Affiliation(teamUid, clubUid, nameBytes);
    }
    private static ContractSnapshot? ReadContract(SafeProcessHandle p, long image, long person, long player)
    {
        if (!Read32(p, person - 4, out int displacement) || displacement != 0 ||
            !Read64(p, player, out long playerType) || playerType != image + 0x04D27228 ||
            !Read64(p, player + 8, out long vbtable) || vbtable != image + 0x04D2720C ||
            !Read64(p, person + 0xA8, out long contract) || contract <= 0 ||
            !Read64(p, contract, out long type) || type != image + 0x04B00AE8 ||
            !Read64(p, contract + 8, out long owner) || owner != person ||
            !Read32(p, contract + 0x20, out int wage) || !Read32(p, contract + 0x44, out int start) ||
            !Read32(p, contract + 0x48, out int end)) return null;
        return new(contract, wage, start, end, PlayerValueDecoder.Contract(wage, unchecked((uint)start), unchecked((uint)end)));
    }
    private sealed record ContractSnapshot(long Address, int Wage, int Start, int End, PlayerContractCandidate Value);
    private static bool Read32(SafeProcessHandle p, long address, out int value)
    { value = 0; if (!ReadBytes(p, address, 4, out var b)) return false; value = BitConverter.ToInt32(b, 0); return true; }
    private static bool Read64(SafeProcessHandle p, long address, out long value)
    { value = 0; if (!ReadBytes(p, address, 8, out var b)) return false; value = BitConverter.ToInt64(b, 0); return true; }
    private static bool ReadBytes(SafeProcessHandle p, long address, int length, out byte[] bytes)
    { bytes = new byte[length]; return address > 0 && ReadProcessMemory(p, (nint)address, bytes, length, out var read) && read == (nuint)length; }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern nint OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool ReadProcessMemory(SafeProcessHandle process, nint address, byte[] buffer, int size, out nuint read);
    private readonly record struct Header(long Table, long Vector, long BaseBegin, long BaseEnd, long Begin, long End);
    private sealed class SafeProcessHandle : Microsoft.Win32.SafeHandles.SafeHandleZeroOrMinusOneIsInvalid
    {
        public SafeProcessHandle(nint handle) : base(true) { SetHandle(handle); }
        protected override bool ReleaseHandle() => CloseHandle(handle);
        [DllImport("kernel32.dll")] private static extern bool CloseHandle(nint h);
    }
}

public sealed record PersonResult(string Status, int? Uid, string? DisplayName, PlayerDetails? Details = null,
    CandidateAffiliation? Affiliation = null, PlayerContractCandidate? Contract = null);
public sealed record PlayerDetails(byte? ReflexesRaw, byte? HandlingRaw, byte? AnticipationRaw,
    byte? JumpingRaw, int? HeightCm, string? DateOfBirth);
public sealed record CandidateAffiliation(uint TeamUid, uint ClubUid, string ClubShortName);
public sealed record PlayerContractCandidate(string Status, string? StartDate, string? EndDate, int? WageRaw);
