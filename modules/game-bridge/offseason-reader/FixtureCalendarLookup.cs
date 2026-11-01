using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;
namespace FootballAssistant.OffseasonReader;

// Experimental loaded-bucket view only; no complete-calendar claim.
public sealed record FixtureCalendarEntry(string Date,uint OpponentTeamUid,uint OpponentClubUid,string OpponentName,string Side,string? Venue=null,byte? RawFlags=null);
public sealed record FixtureCalendarResult(string Status,int Buckets=0,int Unloaded=0,int Unknown=0,int InspectedEntries=0,IReadOnlyList<FixtureCalendarEntry>? Fixtures=null,DateTimeOffset? ObservedAt=null);
public static class FixtureCalendarLookup
{
    private const string Hash="BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
    public static bool IsValidRange(DateTime start,DateTime finish) =>
        start.TimeOfDay==TimeSpan.Zero && finish.TimeOfDay==TimeSpan.Zero && finish>=start &&
        finish.Year==start.Year && (finish-start).Days<30 && start.Year is >=1901 and <=2100;
    internal static FixtureCalendarResult Finish(int buckets,int unloaded,int unknown,int total,IEnumerable<FixtureCalendarEntry> entries,DateTimeOffset observedAt) =>
        new(unloaded>0||unknown>0?"partial":"experimental_loaded_buckets_only",buckets,unloaded,unknown,total,entries.OrderBy(x=>x.Date,StringComparer.Ordinal).ThenBy(x=>x.OpponentClubUid).ToArray(),observedAt);
    internal static string LoadedState(byte value) => value switch { 0 => "unloaded", 1 => "loaded", _ => "unknown" };
    internal static string VenueCandidate(byte flags,uint firstTeamUid,uint targetTeamUid) =>
        (flags & 0x02)==0 || firstTeamUid is 0 or uint.MaxValue || targetTeamUid is 0 or uint.MaxValue ? "unknown" : firstTeamUid==targetTeamUid ? "home" : "away";
    internal static IEnumerable<DateTime> Days(DateTime start,DateTime finish)
    {
        if(!IsValidRange(start,finish)) throw new ArgumentException();
        for(int i=0;i<=(finish-start).Days;i++) yield return start.AddDays(i);
    }
    public static FixtureCalendarResult Read(int pid,uint clubUid,DateTime start,DateTime finish)
    {
        if(pid<=0 || clubUid is 0 or uint.MaxValue || !IsValidRange(start,finish)) return new("unknown");
        try
        {
    using var proc=Process.GetProcessById(pid);
    if(!string.Equals(proc.ProcessName,"fm",StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException();
    var module=proc.Modules.Cast<ProcessModule>().Single(m=>string.Equals(m.ModuleName,"game_plugin.dll",StringComparison.OrdinalIgnoreCase));
    if(string.IsNullOrEmpty(module.FileName)) throw new InvalidOperationException();
    using(var file=File.OpenRead(module.FileName)) using(var sha=SHA256.Create()) if(Convert.ToHexString(sha.ComputeHash(file))!=Hash) throw new InvalidOperationException();
    using var handle=Native.OpenProcess(0x1010,false,pid); if(handle.IsInvalid) throw new InvalidOperationException();
    var clock=Stopwatch.StartNew(); long image=module.BaseAddress.ToInt64();
    var mem=new Tracked((address,length)=>Native.Read(handle,address,length));
    var r=new Reader(mem,image,clubUid); var root=r.FindTeam();
    uint targetTeamUid=r.U32(root.Team+0x0C); if(targetTeamUid is 0 or uint.MaxValue) throw new InvalidOperationException();
    long rule=r.I64(image+0x05709280);
    if(rule<65536 || r.I64(rule)!=image+0x04CB86A8) throw new InvalidOperationException();
    long comp=r.I64(rule+0x138);
    if(comp<65536 || r.I64(comp)!=image+0x04DD4618) throw new InvalidOperationException();
    long finder=checked(comp+8); int year=BitConverter.ToUInt16(mem.Bytes(finder+0x40,2));
    if(year!=start.Year) throw new InvalidOperationException();
    long b=r.I64(finder+0x10),e=r.I64(finder+0x18),c=r.I64(finder+0x20);
    if(b<65536 || (b&7)!=0 || e<b || c<e || (e-b)%8!=0 || (c-b)%8!=0 || (e-b)/8>128 || (c-b)/8>128) throw new InvalidOperationException();
    int buckets=(int)((e-b)/8), unloaded=0, unknown=0,total=0, matches=0; var unique=new HashSet<long>(); var output=new List<FixtureCalendarEntry>();
    for(int i=0;i<buckets;i++)
    {
        if(clock.ElapsedMilliseconds>=15000)throw new InvalidOperationException();
        long bucket=r.I64(b+i*8L); if(bucket<65536 || (bucket&7)!=0){unknown++;continue;}
        string state=LoadedState(mem.Bytes(bucket+0xB70,1)[0]); if(state!="loaded"){if(state=="unloaded")unloaded++;else unknown++;continue;}
        foreach(var date in Days(start,finish))
        {
        if(clock.ElapsedMilliseconds>=15000)throw new InvalidOperationException();
        long day=r.I64(bucket+(date.DayOfYear-1)*8L); if(day==0)continue;
        if(day<65536 || (day&7)!=0){unknown++;continue;}
        long db=r.I64(day),de=r.I64(day+8),dc=r.I64(day+0x10);
        if(db==0 && de==0 && dc==0)continue;
        if(db<65536 || (db&7)!=0 || de<db || dc<de || (de-db)%8!=0 || (dc-db)%8!=0 || (dc-db)/8>4096)throw new InvalidOperationException();
        int n=checked((int)((de-db)/8)); if(total+n>10000)throw new InvalidOperationException();total+=n;
        for(int j=0;j<n;j++)
        {
            long fixture=r.I64(db+j*8L); if(fixture<65536 || (fixture&7)!=0){unknown++;continue;}
            if(r.I64(fixture)!=image+0x04CB69A8){unknown++;continue;}
            long a=r.I64(fixture+8), other=r.I64(fixture+0x10);
            if(a!=root.Team && other!=root.Team)continue;
            if(a==root.Team && other==root.Team){unknown++;continue;}
            long opp=a==root.Team?other:a;
            if(opp<65536 || r.I64(opp)!=image+0x04CE1108){unknown++;continue;}
            uint teamId=r.U32(opp+0x0C); long club=r.I64(opp+0x30);
            if(teamId is 0 or uint.MaxValue || club<65536 || r.I64(club)!=image+0x04CDA1F8){unknown++;continue;}
            uint clubId=r.U32(club+0x0C); long namePtr=r.I64(club+0xC8);
            if(clubId is 0 or uint.MaxValue || namePtr<65536){unknown++;continue;}
            var bytes=mem.Bytes(namePtr+4,64); int end=Array.IndexOf(bytes,(byte)0); if(end<=0){unknown++;continue;}
            string name;
            try{name=new UTF8Encoding(false,true).GetString(bytes,0,end).Trim();}catch(DecoderFallbackException){unknown++;continue;}
            uint packed=r.U32(fixture+0x4C); int y=(int)(packed>>16),d=(int)(packed&0x1FF);
            if(string.IsNullOrWhiteSpace(name) || y<1901 || y>2100 || d<1 || d>(DateTime.IsLeapYear(y)?366:365)){unknown++;continue;}
            var fd=new DateTime(y,1,1).AddDays(d-1);
            if(fd.Date!=date.Date){unknown++;continue;}
            if(!unique.Add(fixture))continue;
            byte flags=mem.Bytes(fixture+0x36,1)[0];
            uint firstTeamUid=a==root.Team?targetTeamUid:teamId;
            matches++;output.Add(new FixtureCalendarEntry(fd.ToString("yyyy-MM-dd",System.Globalization.CultureInfo.InvariantCulture),teamId,clubId,name,a==root.Team?"first":"second",VenueCandidate(flags,firstTeamUid,targetTeamUid),flags));
        }
        }
    }
    if(clock.ElapsedMilliseconds>=15000 || !mem.Stable() || clock.ElapsedMilliseconds>=15000)throw new InvalidOperationException();
    return Finish(buckets,unloaded,unknown,total,output,DateTimeOffset.UtcNow);
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException) { return new("unknown"); }
    }
readonly record struct Root(long Manager, long Person, long Contract, long Team, long Club);

sealed class Reader
{
    private readonly Tracked process; private readonly long image; private readonly uint clubUid;
    public Reader(Tracked process,long image,uint clubUid){this.process=process;this.image=image;this.clubUid=clubUid;}
    public byte[] Bytes(long address, int count) => process.Bytes(address, count);
    public long I64(long p) => BitConverter.ToInt64(Bytes(p, 8));
    int I32(long p) => BitConverter.ToInt32(Bytes(p, 4));
    public uint U32(long p) => BitConverter.ToUInt32(Bytes(p, 4));
    bool V(long p, long rva) => I64(p) == checked(image + rva);
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
            if (person < 65536 || !V(person, 0x04CC08D8) || I32(person - 4) != 0 || I64(item) != image + 0x04CC086C) continue;
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

}
internal sealed class Tracked
{
    private readonly Func<long,int,byte[]> read;
    internal Tracked(Func<long,int,byte[]> read){this.read=read;}
    readonly List<(long Address,byte[] Bytes)> reads=new();
    public byte[] Bytes(long address,int length)
    {
        if(address<65536||length<=0||length>64||reads.Count>=120000)throw new InvalidOperationException();
        var b=Read(address,length); reads.Add((address,(byte[])b.Clone())); return b;
    }
    byte[] Read(long address,int length) {var b=read(address,length);if(b is null || b.Length!=length)throw new InvalidOperationException();return b;}
    public bool Stable(){foreach(var r in reads)if(!r.Bytes.SequenceEqual(Read(r.Address,r.Bytes.Length)))return false;return true;}
}
static class Native
{
    internal static byte[] Read(SafeProcessHandle handle,long address,int length) {var b=new byte[length];if(!ReadProcessMemory(handle,(IntPtr)address,b,(nuint)length,out nuint n)||n!=(nuint)length)throw new InvalidOperationException();return b;}
    [DllImport("kernel32.dll", SetLastError = true)] public static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool ReadProcessMemory(SafeProcessHandle process, IntPtr address, byte[] buffer, nuint size, out nuint read);
}






}

