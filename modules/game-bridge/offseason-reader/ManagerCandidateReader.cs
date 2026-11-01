using System.Text;

namespace ManagerCandidates;

// Caller must first verify the exact game_plugin.dll SHA256:
// BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F.
// The supplied reader must be read-only and return exactly the requested bytes or throw.
public interface IReadOnlyMemory { byte[] Read(long address, int length); }
public sealed record Candidate(uint Uid, string Name, uint ClubUid, string ClubName);
public sealed record Result(string Status, int Inspected, int Unknown, IReadOnlyList<Candidate> Candidates);

public sealed class ManagerCandidateReader
{
    private readonly IReadOnlyMemory memory;
    private readonly long image;
    public ManagerCandidateReader(IReadOnlyMemory memory, long image) { this.memory = memory; this.image = image; }
    private byte[] Bytes(long a, int n) { if (a < 65536 || n <= 0) throw new InvalidOperationException(); var b = memory.Read(a, n); if (b.Length != n) throw new InvalidOperationException(); return b; }
    private long I64(long a) => BitConverter.ToInt64(Bytes(a, 8));
    private int I32(long a) => BitConverter.ToInt32(Bytes(a, 4));
    private uint U32(long a) => BitConverter.ToUInt32(Bytes(a, 4));
    private bool V(long a, long rva) => I64(a) == checked(image + rva);
    private (long Manager, long Begin, long End) Header()
    {
        var m = I64(checked(image + 0x056F3008));
        if (!V(m, 0x04E2D678) || !V(m + 8, 0x04E2D688)) throw new InvalidOperationException();
        var b = I64(m + 0x18); var e = I64(m + 0x20);
        if (b < 65536 || (b & 7) != 0 || e < b || (e - b) % 8 != 0 || (e - b) / 8 > 16) throw new InvalidOperationException();
        return (m, b, e);
    }
    private string Text(long p)
    {
        var b = Bytes(p, 64); int n = Array.IndexOf(b, (byte)0); if (n < 0) throw new InvalidOperationException();
        return new UTF8Encoding(false, true).GetString(b, 0, n).Trim();
    }
    private string Name(long person, int offset)
    {
        long p = I64(checked(person + offset)); if (p == 0) return "";
        return Text(checked(I64(p) + 4));
    }
    private (string Kind, Candidate? Candidate) Inspect(long obj, uint target)
    {
        if (obj == 0) return ("empty", null);
        long person = checked(obj + 0x440);
        if (!V(obj, 0x04CC086C) || !V(person, 0x04CC08D8) || I32(person - 4) != 0) return ("unknown_type", null);
        long contract = I64(person + 0xA8); if (contract == 0) return ("no_contract", null);
        if (!V(contract, 0x04B00AE8) || I64(contract + 8) != person) return ("unknown_contract", null);
        long team = I64(contract + 0x10); if (team == 0) return ("no_team", null);
        if (!V(team, 0x04CE1108)) return ("unknown_team", null);
        long club = I64(team + 0x30); if (club == 0) return ("no_club", null);
        if (!V(club, 0x04CDA1F8)) return ("unknown_club", null);
        uint clubUid = U32(club + 0x0C); if (clubUid != target) return ("other_club", null);
        uint uid = U32(person + 0x0C); if (uid is 0 or uint.MaxValue) throw new InvalidOperationException();
        string first = Name(person, 0x50), last = Name(person, 0x58), common = Name(person, 0x60);
        string name = string.IsNullOrWhiteSpace(common) ? $"{first} {last}".Trim() : common;
        string clubName = Text(checked(I64(club + 0xC8) + 4));
        if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(clubName)) throw new InvalidOperationException();
        return ("candidate", new(uid, name, clubUid, clubName));
    }
    // Each candidate and each non-match is read twice, plus header checks. This
    // does not guarantee an atomic snapshot and never identifies an active user.
    public Result Read(uint clubUid)
    {
        if (clubUid is 0 or uint.MaxValue) throw new ArgumentOutOfRangeException(nameof(clubUid));
        try
        {
            var clock = System.Diagnostics.Stopwatch.StartNew(); var h = Header();
            int count = checked((int)((h.End - h.Begin) / 8)); var pointers = new long[count];
            var observations = new (string Kind, Candidate? Candidate)[count]; var result = new List<Candidate>(); int unknown = 0;
            for (int i = 0; i < count; i++)
            {
                pointers[i] = I64(checked(h.Begin + i * 8L)); observations[i] = Inspect(pointers[i], clubUid);
                if (observations[i].Candidate is { } c) { result.Add(c); if (result.Count > 4) throw new InvalidOperationException(); }
                else if (observations[i].Kind.StartsWith("unknown", StringComparison.Ordinal)) unknown++;
            }
            if (Header() != h) throw new InvalidOperationException();
            for (int i = 0; i < count; i++)
                if (I64(checked(h.Begin + i * 8L)) != pointers[i] || Inspect(pointers[i], clubUid) != observations[i]) throw new InvalidOperationException();
            if (Header() != h || clock.Elapsed > TimeSpan.FromSeconds(2)) throw new InvalidOperationException();
            return new("experimental_candidates_incomplete", count, unknown, result);
        }
        catch (Exception ex) when (ex is InvalidOperationException or OverflowException or ArgumentException or System.IO.IOException)
        { return new("unavailable", 0, 0, Array.Empty<Candidate>()); }
    }
}
