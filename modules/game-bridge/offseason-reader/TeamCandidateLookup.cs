using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace FootballAssistant.OffseasonReader;

// Fixed-build, bounded type classification of a candidate team's container.
// Results are incomplete candidates, not a roster or an active-manager claim.
public static class TeamCandidateLookup
{
    private const string ExpectedHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
    public static TeamCandidateResult Read(int pid, uint clubUid)
    {
        if (pid <= 0 || clubUid is 0 or uint.MaxValue) return new("invalid_input");
        try
        {
            using var process = Process.GetProcessById(pid);
            if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("wrong_process");
            var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
            if (module is null || string.IsNullOrEmpty(module.FileName)) return new("module_unavailable");
            using (var file = File.OpenRead(module.FileName))
            using (var sha = SHA256.Create())
                if (Convert.ToHexString(sha.ComputeHash(file)) != ExpectedHash) return new("unsupported_binary");
            using var memory = Native.OpenProcess(0x1010, false, pid);
            if (memory.IsInvalid) return new("process_unavailable");
            var reader = new Reader(memory, module.BaseAddress.ToInt64(), clubUid);
            var timer = Stopwatch.StartNew();
            var root = reader.FindTeam();
            var header = reader.Header(root.Team);
            int total = checked((int)((header.End - header.Begin) / 8));
            int inspected = Math.Min(total, 64), exact = 0;
            var entries = new long[inspected];
            var classes = new int[inspected];
            var ids = new uint[inspected];
            var snapshots = new PlayerSnapshot?[inspected];
            var seen = new HashSet<uint>();
            for (int i = 0; i < inspected; i++)
            {
                entries[i] = reader.I64(checked(header.Begin + 8L * i));
                classes[i] = reader.Classify(entries[i], out ids[i]);
                if (classes[i] == 1) { if (!seen.Add(ids[i])) return new("unavailable"); exact++; snapshots[i] = reader.Player(entries[i], ids[i]); }
                if (timer.ElapsedMilliseconds >= 2000) return new("unavailable");
            }
            if (reader.FindTeam() != root || reader.Header(root.Team) != header) return new("changed_during_read");
            for (int i = 0; i < inspected; i++)
            {
                if (reader.I64(checked(header.Begin + 8L * i)) != entries[i] || reader.Classify(entries[i], out uint id) != classes[i] || id != ids[i]) return new("changed_during_read");
                if (classes[i] == 1 && reader.Player(entries[i], id) != snapshots[i]) return new("changed_during_read");
            }
            if (reader.FindTeam() != root || reader.Header(root.Team) != header || timer.ElapsedMilliseconds >= 2000) return new("changed_during_read");
            var players = snapshots.Where(p => p is not null).Select(p => new TeamPlayerCandidate(p!.Uid, p.Name, p.LinkStatus, p.TeamUid, p.ClubUid)).ToArray();
            return new("experimental_candidates_incomplete", total, inspected, exact, inspected - exact, total > inspected, DateTimeOffset.UtcNow, players);
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException)
        { return new("unavailable"); }
    }
    private readonly record struct Root(long Manager, long Person, long Contract, long Team, long Club);
    private readonly record struct Vector(long Begin, long End, long Capacity);
    // Addresses stay internal and participate in the second-read comparison.
    private sealed record PlayerSnapshot(uint Uid, string? Name, string LinkStatus, long Team, long Club, uint? TeamUid, uint? ClubUid);
    private sealed class Reader
    {
        private readonly SafeProcessHandle process;
        private readonly long image;
        private readonly uint clubUid;
        public Reader(SafeProcessHandle process, long image, uint clubUid) { this.process = process; this.image = image; this.clubUid = clubUid; }
        private byte[] Bytes(long address, int count)
        {
            if (address < 65536 || count <= 0) throw new InvalidOperationException();
            byte[] buffer = new byte[count];
            if (!Native.ReadProcessMemory(process, (IntPtr)address, buffer, (nuint)count, out nuint read) || read != (nuint)count) throw new InvalidOperationException();
            return buffer;
        }
        public long I64(long p) => BitConverter.ToInt64(Bytes(p, 8), 0);
        private int I32(long p) => BitConverter.ToInt32(Bytes(p, 4), 0);
        private uint U32(long p) => BitConverter.ToUInt32(Bytes(p, 4), 0);
        private bool V(long p, long rva) => I64(p) == checked(image + rva);
        public Root FindTeam()
        {
            long manager = I64(checked(image + 0x056F3008));
            if (!V(manager, 0x04E2D678) || !V(manager + 8, 0x04E2D688)) throw new InvalidOperationException();
            long begin = I64(manager + 0x18), end = I64(manager + 0x20);
            if (begin < 65536 || end < begin || (end - begin) % 8 != 0 || (end - begin) / 8 > 16) throw new InvalidOperationException();
            Root? found = null;
            for (long p = begin; p < end; p += 8)
            {
                long item = I64(p);
                if (item < 65536) throw new InvalidOperationException();
                long person = checked(item + 0x440);
                if (!V(person, 0x04CC08D8) || I32(person - 4) != 0 || I64(item) != image + 0x04CC086C) continue;
                long contract = I64(person + 0xA8);
                if (contract < 65536 || !V(contract, 0x04B00AE8) || I64(contract + 8) != person) continue;
                long team = I64(contract + 0x10);
                if (team < 65536 || !V(team, 0x04CE1108)) continue;
                long club = I64(team + 0x30);
                if (club < 65536 || !V(club, 0x04CDA1F8) || U32(club + 0x0C) != clubUid) continue;
                if (found.HasValue) throw new InvalidOperationException();
                found = new Root(manager, person, contract, team, club);
            }
            if (I64(manager + 0x18) != begin || I64(manager + 0x20) != end) throw new InvalidOperationException();
            return found ?? throw new InvalidOperationException();
        }
        public Vector Header(long team)
        {
            long b = I64(team + 0x38), e = I64(team + 0x40), c = I64(team + 0x48);
            if (b == 0 && e == 0 && c == 0) return new Vector(0, 0, 0);
            if (b < 65536 || (b & 7) != 0 || e < b || c < e || (e - b) % 8 != 0 || (c - b) % 8 != 0 || (c - b) / 8 > 8192) throw new InvalidOperationException();
            return new Vector(b, e, c);
        }
        public int Classify(long entry, out uint uid)
        {
            uid = 0;
            if (entry < 65536 || (entry & 7) != 0) return 0;
            if (!V(entry, 0x04D27228)) return 0;
            if (!V(entry + 8, 0x04D2720C) || !V(entry + 0x288, 0x04D27758) || I32(entry + 0x284) != 0) throw new InvalidOperationException();
            uid = U32(entry + 0x294);
            if (uid == 0 || uid > int.MaxValue) throw new InvalidOperationException();
            return 1;
        }
        private string NamePart(long person, long offset)
        {
            long obj = I64(checked(person + offset));
            if (obj == 0) return "";
            long buffer = I64(obj);
            byte[] bytes = Bytes(checked(buffer + 4), 64);
            int end = Array.IndexOf(bytes, (byte)0);
            if (end < 0) throw new InvalidOperationException();
            return new UTF8Encoding(false, true).GetString(bytes, 0, end).Trim();
        }
        public PlayerSnapshot Player(long entry, uint uid)
        {
            long person = checked(entry + 0x288);
            string first = NamePart(person, 0x50), last = NamePart(person, 0x58), common = NamePart(person, 0x60);
            string display = string.IsNullOrWhiteSpace(common) ? $"{first} {last}".Trim() : common;
            string? name = string.IsNullOrWhiteSpace(display) ? null : display;
            long team = I64(checked(entry + 0x130));
            if (team == 0) return new(uid, name, "no_team", 0, 0, null, null);
            if (team < 65536 || !V(team, 0x04CE1108)) return new(uid, name, "unsupported_team", team, 0, null, null);
            uint teamUid = U32(team + 0x0C);
            if (teamUid is 0 or uint.MaxValue) throw new InvalidOperationException();
            long club = I64(team + 0x30);
            if (club == 0) return new(uid, name, "no_club", team, 0, teamUid, null);
            if (club < 65536 || !V(club, 0x04CDA1F8)) return new(uid, name, "unsupported_club", team, club, teamUid, null);
            uint clubUid = U32(club + 0x0C);
            if (clubUid is 0 or uint.MaxValue) throw new InvalidOperationException();
            return new(uid, name, "exact_types", team, club, teamUid, clubUid);
        }
    }
    private static class Native
    {
        [DllImport("kernel32.dll", SetLastError = true)] public static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool ReadProcessMemory(SafeProcessHandle process, IntPtr address, byte[] buffer, nuint size, out nuint read);
    }
}
public sealed record TeamCandidateResult(string Status, int? EntriesTotal = null, int? Inspected = null, int? ExactPlayerType = null, int? OtherOrUnresolved = null, bool? Truncated = null, DateTimeOffset? ObservedAt = null, IReadOnlyList<TeamPlayerCandidate>? Players = null);
public sealed record TeamPlayerCandidate(uint Uid, string? Name, string LinkStatus, uint? TeamUid, uint? ClubUid);
