using System.Runtime.InteropServices;
namespace FootballAssistant.OffseasonReader;
// Non-polymorphic candidate: exact runtime type and current selection remain unproven.
// Caller must validate game hash and team, and recheck its complete root after reading.
internal static class TacticOutRoleReader
{
internal static IReadOnlyList<string>? Read(SafeHandle h, long image, long targetTeam)
{
    try
    {
        var t = new Tracked(h);
        long manager = t.I64(image + 0x056F5DE0);
        if (t.I64(manager) != image + 0x04EC52D8 || t.I64(manager + 8) != image + 0x04EC52E8) return null;
        long begin=t.I64(manager+0x20), end=t.I64(manager+0x28), capacity=t.I64(manager+0x30);
        if (begin < 65536 || (begin & 7) != 0 || end-begin != 8 || capacity < end || (capacity-begin)%8 != 0 || (capacity-begin)/8 > 4096) return null;
        long element=t.I64(begin); if (element < 65536 || (element&7)!=0) return null;
        long head=t.I64(element); long size=t.I64(element+8);
        if (head < 65536 || (head&7)!=0 || size < 0 || size > 32 || t.U8(head+0x19)!=1) return null;
        long treeRoot=t.I64(head+8);
        if ((size==0) != (treeRoot==head)) return null;
        long table=t.I64(image+0x05703768);
        if (table < 65536 || t.I64(table)!=image+0x04CA5518) return null;
        byte mode=t.U8(image+0x05703DE0);
        if(mode>1) return null;
        long tb,te;
        if(mode==0) { tb=t.I64(table+0x60); te=t.I64(table+0x68); }
        else { long vector=t.I64(table+0x80); if(vector<65536) return null; tb=t.I64(vector); te=t.I64(vector+8); }
        if(tb<65536 || (tb&7)!=0 || te<tb || (te-tb)%8!=0 || (te-tb)/8>1_048_575) return null;
        var stack=new Stack<(long Node,long Parent)>(); var seen=new HashSet<long>();
        if (size>0) stack.Push((treeRoot,head));
        int matches=0, targets=0; long target=0;
        while(stack.Count>0)
        {
            var (node,parent)=stack.Pop();
            if(node<65536 || (node&7)!=0 || !seen.Add(node) || seen.Count>32 || t.U8(node+0x19)!=0 || t.I64(node+8)!=parent) return null;
            long left=t.I64(node), right=t.I64(node+0x10);
            if(left!=head) stack.Push((left,node)); if(right!=head) stack.Push((right,node));
            int idx=t.I32(node+0x20);
            if(idx < -1 || idx >= (te-tb)/8) return null;
            if(idx>=0 && t.I64(tb+idx*8L)==targetTeam)
            {
                if(++matches>1) return null;
                long b=t.I64(node+0x1038), e=t.I64(node+0x1040), c=t.I64(node+0x1048);
                if(b==0 && e==0 && c==0) targets=0;
                else { if(b<65536 || (b&7)!=0 || e<b || c<e || (e-b)%8!=0 || (c-b)%8!=0 || (c-b)/8>64) return null; targets=checked((int)((e-b)/8)); if(targets!=1) return null; target=t.I64(b); if(target<65536 || (target&7)!=0) return null; }
            }
        }
        if(seen.Count!=size || matches!=1 || targets!=1 || target==0) return null;
        long schedule=t.I64(targetTeam+0xA0); if(schedule<65536) return null;
        long source=t.I64(schedule+0xD0); if(source<65536 || t.I64(source+0xA0)!=targetTeam) return null;
        uint[] positions = { 0x1, 0, 0x4, 0x200010, 0x10, 0x100010, 0x8, 0x20, 0x200080, 0x80, 0x100080, 0x40, 0x100, 0x200400, 0x400, 0x100400, 0x200, 0x800, 0x202000, 0x2000, 0x102000, 0x1000, 0x800, 0x204000, 0x4000, 0x104000, 0x1000 };
        var roles=new string[11];
        for(int i=0;i<11;i++) {
            int raw=t.U16(source+0x18+i*2L)&0x3f, signed=raw>=32?raw-64:raw, index=signed+15;
            if(index<0 || index>=positions.Length || positions[index]==0 || t.U32(target+0x438+i*0x48L)!=positions[index]) return null;
            roles[i]=TacticSecondRoleDecoder.Decode(unchecked((ulong)t.I64(target+0x478+i*0x48L)));
        }
        if(!t.Stable()) return null;
        return roles;
    }
    catch(Exception ex) when(ex is InvalidOperationException or OverflowException or ArgumentException) { return null; }
}

}
public static class TacticSecondRoleDecoder
{
// Role names follow FMMatchLens TacticalFormationDecoder (MIT, vendor/LICENSE).
public static string Decode(ulong mask)
{
    const ulong dutyMask = 0x200000UL | 0x400000UL | 0x800000UL | 0x2000000UL | 0x4000000UL | 0x400000000UL;
    string name=(mask & ~dutyMask) switch {
        0x1UL => "Goalkeeper",
        0x2UL => "Sweeper Keeper",
        0x4UL => "Line Keeper",
        0x8UL => "Centre-Back",
        0x10UL => "Stopping Centre-Back",
        0x20UL => "Covering Centre-Back",
        0x40UL => "Wide Centre-Back",
        0x80UL => "Stopping Wide Centre-Back",
        0x100UL => "Covering Wide Centre-Back",
        0x200UL => "Full-Back",
        0x400UL => "Pressing Full-Back",
        0x800UL => "Holding Full-Back",
        0x1000UL => "Wing-Back",
        0x2000UL => "Pressing Wing-Back",
        0x4000UL => "Holding Wing-Back",
        0x8000UL => "Defensive Midfielder",
        0x10000UL => "Dropping Defensive Midfielder",
        0x20000UL => "Pressing Defensive Midfielder",
        0x40000UL => "Screening Defensive Midfielder",
        0x80000UL => "Wide-Cover Defensive Midfielder",
        0x100000UL => "Central Midfielder",
        0x8000000UL => "Pressing Central Midfielder",
        0x10000000UL => "Screening Central Midfielder",
        0x20000000UL => "Wide-Cover Central Midfielder",
        0x40000000UL => "Attacking Midfielder",
        0x80000000UL => "Tracking Attacking Midfielder",
        0x100000000UL => "Central-Outlet Attacking Midfielder",
        0x200000000UL => "Splitting-Outlet Attacking Midfielder",
        0x800000000UL => "Wide Midfielder",
        0x1000000000UL => "Tracking Wide Midfielder",
        0x2000000000UL => "Wide-Outlet Wide Midfielder",
        0x4000000000UL => "Winger",
        0x8000000000UL => "Tracking Winger",
        0x10000000000UL => "Inverting-Outlet Winger",
        0x20000000000UL => "Wide-Outlet Winger",
        0x40000000000UL => "Centre-Forward",
        0x80000000000UL => "Tracking Centre-Forward",
        0x100000000000UL => "Central-Outlet Centre-Forward",
        0x200000000000UL => "Splitting-Outlet Centre-Forward",
        _ => "unknown"
    };
    string duty=(mask & dutyMask) switch { 0x200000UL => "Defend", 0x400000UL => "Support", 0x800000UL => "Attack", 0x2000000UL => "Stopper", 0x4000000UL => "Cover", 0x400000000UL => "Float", _ => "unknown" };
    return name == "unknown" ? "unknown" : $"0x{mask:X}: {name} / {duty}";
}

}
sealed class Tracked
{
    readonly SafeHandle h; readonly List<(long Address,byte[] Bytes)> reads=new();
    public Tracked(SafeHandle handle) { h=handle; }
    byte[] Bytes(long address,int size) { if(address<65536) throw new InvalidOperationException(); var b=new byte[size]; if(!NativeProbe.ReadProcessMemory(h,(nint)address,b,size,out var n)||n!=(nuint)size) throw new InvalidOperationException(); reads.Add((address,b)); return b; }
    public ushort U16(long p)=>BitConverter.ToUInt16(Bytes(p,2)); public uint U32(long p)=>BitConverter.ToUInt32(Bytes(p,4)); public long I64(long p)=>BitConverter.ToInt64(Bytes(p,8)); public int I32(long p)=>BitConverter.ToInt32(Bytes(p,4)); public byte U8(long p)=>Bytes(p,1)[0];
    public bool Stable() { foreach(var r in reads) { var b=new byte[r.Bytes.Length]; if(!NativeProbe.ReadProcessMemory(h,(nint)r.Address,b,b.Length,out var n)||n!=(nuint)b.Length||!b.SequenceEqual(r.Bytes)) return false; } return true; }
}
static class NativeProbe { [DllImport("kernel32.dll", SetLastError=true)] public static extern bool ReadProcessMemory(SafeHandle p,nint address,byte[] buffer,int size,out nuint read); }




