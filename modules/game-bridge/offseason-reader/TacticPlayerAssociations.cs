using System.Runtime.InteropServices;
using System.Text;
using System.Diagnostics;

namespace FootballAssistant.OffseasonReader;

// Internal IDs are used only for matching and never appear in public results.
public sealed record TacticPlayerCandidate(string Status, uint? Uid = null, string? Name = null, byte? Number = null);
internal sealed record TacticIdentity(uint InternalId, uint Uid, string? Name, string First, string Last, string Common);
internal static class TacticPlayerAssociations
{
    // Call only after the fixed game binary hash, TEAM type and TEAM->slot backref
    // have been verified. Caller must recheck its complete root after this returns.
    internal static IReadOnlyList<TacticPlayerCandidate>? Read(SafeHandle process, long image, long team, long slot)
    {
        try
        {
            var clock = Stopwatch.StartNew();
            long b = I64(process, team + 0x38), e = I64(process, team + 0x40), c = I64(process, team + 0x48);
            if (b < 65536 || (b & 7) != 0 || e < b || c < e || (e-b)%8 != 0 || (c-b)%8 != 0 || (e-b)/8 > 64 || (c-b)/8 > 8192) return null;
            int count = checked((int)((e-b)/8)); var entries = new long[count]; var values = new TacticIdentity?[count]; bool unsupported = false;
            byte[] ids = Bytes(process, slot + 0x30, 44), numbers = Bytes(process, slot + 0xC0, 11);
            for (int i=0; i<count; i++) { entries[i]=I64(process,b+i*8L); values[i]=ReadIdentity(process,image,entries[i]); if(values[i] is null) unsupported=true; }
            if (I64(process,team+0x38)!=b || I64(process,team+0x40)!=e || I64(process,team+0x48)!=c) return null;
            for (int i=0; i<count; i++) if (I64(process,b+i*8L)!=entries[i] || ReadIdentity(process,image,entries[i])!=values[i]) return null;
            if (I64(process,team+0x38)!=b || I64(process,team+0x40)!=e || I64(process,team+0x48)!=c ||
                !ids.SequenceEqual(Bytes(process,slot+0x30,44)) || !numbers.SequenceEqual(Bytes(process,slot+0xC0,11)) || clock.ElapsedMilliseconds>=2000) return null;
            return Match(ids,numbers,values,unsupported);
        }
        catch (Exception ex) when (ex is InvalidOperationException or ArgumentException or OverflowException or System.IO.IOException) { return null; }
    }
    internal static IReadOnlyList<TacticPlayerCandidate> Match(byte[] ids, byte[] numbers, IReadOnlyList<TacticIdentity?> identities, bool unsupported)
    {
        if(ids.Length!=44 || numbers.Length!=11) throw new ArgumentException();
        var valid=identities.Where(x=>x is not null).Select(x=>x!).ToArray(); var result=new TacticPlayerCandidate[11];
        for(int i=0;i<11;i++)
        {
            uint key=BitConverter.ToUInt32(ids,i*4); var found=valid.Where(x=>x.InternalId==key && key!=uint.MaxValue).ToArray();
            int occurrences=Enumerable.Range(0,11).Count(j=>BitConverter.ToUInt32(ids,j*4)==key);
            result[i] = unsupported || found.Length!=1 || occurrences!=1 || found[0].Name is null || valid.Count(x=>x.Uid==found[0].Uid)!=1
                ? new("unknown") : new("experimental_candidate",found[0].Uid,found[0].Name,numbers[i]==byte.MaxValue ? null : numbers[i]);
        }
        return result;
    }
    private static TacticIdentity? ReadIdentity(SafeHandle p,long image,long entry)
    {
        if(entry<65536 || (entry&7)!=0 || I64(p,entry)!=image+0x04D27228) return null;
        long person=checked(entry+0x288);
        if(I64(p,entry+8)!=image+0x04D2720C || I64(p,person)!=image+0x04D27758 || I32(p,person-4)!=0) throw new InvalidOperationException();
        uint uid=U32(p,person+0x0C); if(uid is 0 or > int.MaxValue) throw new InvalidOperationException();
        string first=Part(p,person+0x50), last=Part(p,person+0x58), common=Part(p,person+0x60);
        string display=string.IsNullOrWhiteSpace(common)?$"{first} {last}".Trim():common;
        return new(U32(p,person+8),uid,string.IsNullOrWhiteSpace(display)?null:display,first,last,common);
    }
    private static string Part(SafeHandle p,long a)
    {
        long obj=I64(p,a); if(obj==0) return ""; long buffer=I64(p,obj); var bytes=Bytes(p,checked(buffer+4),64);
        int end=Array.IndexOf(bytes,(byte)0); if(end<0) throw new InvalidOperationException();
        return new UTF8Encoding(false,true).GetString(bytes,0,end).Trim();
    }
    private static byte[] Bytes(SafeHandle p,long a,int n) { if(a<65536 || n<=0 || n>64) throw new InvalidOperationException(); var b=new byte[n]; if(!ReadProcessMemory(p,(IntPtr)a,b,(nuint)n,out nuint read)||read!=(nuint)n) throw new InvalidOperationException(); return b; }
    private static long I64(SafeHandle p,long a)=>BitConverter.ToInt64(Bytes(p,a,8),0);
    private static int I32(SafeHandle p,long a)=>BitConverter.ToInt32(Bytes(p,a,4),0);
    private static uint U32(SafeHandle p,long a)=>BitConverter.ToUInt32(Bytes(p,a,4),0);
    [DllImport("kernel32.dll",SetLastError=true)] [return:MarshalAs(UnmanagedType.Bool)] private static extern bool ReadProcessMemory(SafeHandle process,IntPtr address,byte[] buffer,nuint length,out nuint read);
}
