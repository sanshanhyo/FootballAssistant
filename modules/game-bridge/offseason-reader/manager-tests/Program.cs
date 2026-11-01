using ManagerCandidates;
using System.Text;

const long img = 0x10000000, m = 0x20000000, array = 0x20001000, obj = 0x20002000, person = obj + 0x440, contract = 0x20003000, team = 0x20004000, club = 0x20005000;
var mem = new Fake();
mem.Q(img + 0x056F3008, m); mem.Q(m, img + 0x04E2D678); mem.Q(m + 8, img + 0x04E2D688); mem.Q(m + 0x18, array); mem.Q(m + 0x20, array + 8); mem.Q(array, obj);
mem.Q(obj, img + 0x04CC086C); mem.Q(person, img + 0x04CC08D8); mem.D(person - 4, 0); mem.D(person + 0x0C, 123);
mem.Q(person + 0xA8, contract); mem.Q(contract, img + 0x04B00AE8); mem.Q(contract + 8, person); mem.Q(contract + 0x10, team);
mem.Q(team, img + 0x04CE1108); mem.Q(team + 0x30, club); mem.Q(club, img + 0x04CDA1F8); mem.D(club + 0x0C, 406);
mem.Q(person + 0x50, 0); mem.Q(person + 0x58, 0); mem.Q(person + 0x60, 0x20006000); mem.Q(0x20006000, 0x20007000); mem.S(0x20007004, "Test Manager");
mem.Q(club + 0xC8, 0x20008000); mem.S(0x20008004, "Test Club");
var reader = new ManagerCandidateReader(mem, img);
var hit = reader.Read(406); if (hit.Candidates.Count != 1 || hit.Candidates[0].Uid != 123 || hit.Candidates[0].Name != "Test Manager") throw new Exception("candidate");
if (reader.Read(407).Candidates.Count != 0) throw new Exception("explicit selection");
mem.MutateOnSecondArrayRead = true; if (reader.Read(406).Status != "unavailable") throw new Exception("changed array");
Console.WriteLine("3 synthetic checks passed");
sealed class Fake : IReadOnlyMemory
{
    readonly Dictionary<long, byte> data = new(); int arrayReads; public bool MutateOnSecondArrayRead;
    public void Q(long a, long v) => Put(a, BitConverter.GetBytes(v)); public void D(long a, int v) => Put(a, BitConverter.GetBytes(v));
    public void S(long a, string s) { var b = new byte[64]; Encoding.UTF8.GetBytes(s).CopyTo(b, 0); Put(a, b); }
    void Put(long a, byte[] b) { for (int i = 0; i < b.Length; i++) data[a + i] = b[i]; }
    public byte[] Read(long a, int n)
    {
        if (MutateOnSecondArrayRead && a == 0x20001000 && ++arrayReads == 2) return BitConverter.GetBytes(0L);
        var b = new byte[n]; for (int i = 0; i < n; i++) if (!data.TryGetValue(a + i, out b[i])) throw new InvalidOperationException(); return b;
    }
}
