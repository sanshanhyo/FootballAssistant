using ManagerCandidates;
using System.Diagnostics;

namespace FootballAssistant.OffseasonReader;

public sealed record NativeManagerResult(string Status, string? Reason = null,
    uint? Uid = null, uint? TeamUid = null, uint? ClubUid = null, byte? ContractKind = null,
    DateTimeOffset? ObservedAt = null, string Source = "native_gcUM_selection",
    string? Proof = null, string SelectionScope = "current_local_human_manager", bool AtomicSnapshot = false)
{
    public static bool SameBinding(NativeManagerResult first, NativeManagerResult second) =>
        first.Status == "available" && second.Status == "available" && first.Uid == second.Uid &&
        first.TeamUid == second.TeamUid && first.ClubUid == second.ClubUid && first.ContractKind == second.ContractKind;
}

// Only used after all NativeReadProfile fingerprints have matched. No game calls,
// no setters, and no inference from the number/order of human-manager candidates.
internal sealed class NativeManagerReader
{
    private readonly IReadOnlyMemory memory;
    private readonly long image;
    private readonly List<(long Address, byte[] Bytes)> reads = new();
    private readonly Stopwatch clock = new();
    private int budget;
    public NativeManagerReader(IReadOnlyMemory memory, long image) { this.memory = memory; this.image = image; }
    private byte[] Exact(long address, int count)
    {
        if (address < 65536 || address > 0x00007FFFFFFFFFFFL - count || count <= 0 || count > 128 || (budget -= count) < 0 || clock.ElapsedMilliseconds >= 2000)
            throw new InvalidOperationException();
        var bytes = memory.Read(address, count);
        if (bytes.Length != count) throw new InvalidOperationException();
        return bytes;
    }
    private byte[] Bytes(long address, int count)
    {
        var bytes = Exact(address, count);
        reads.Add((address, bytes));
        return bytes;
    }
    private long I64(long address) => BitConverter.ToInt64(Bytes(address, 8));
    private int I32(long address) => BitConverter.ToInt32(Bytes(address, 4));
    private uint Uid(long address)
    {
        uint uid = BitConverter.ToUInt32(Bytes(address, 4));
        if (uid == 0 || uid > int.MaxValue) throw new InvalidOperationException();
        return uid;
    }
    private void Type(long address, long rva)
    {
        if (I64(address) != checked(image + rva)) throw new InvalidOperationException();
    }
    public NativeManagerResult Read()
    {
        reads.Clear(); budget = 65536; clock.Restart();
        try
        {
            long selected = I64(checked(image + 0x056F32C8));
            if (selected == 0) return new("unavailable", "no_current_manager_selection");
            Type(selected, 0x04CC08D8);
            var selectedIdentity = Bytes(selected + 8, 8);
            long root = I64(checked(image + 0x056F3008));
            Type(root, 0x04E2D678); Type(root + 8, 0x04E2D688);
            long begin = I64(root + 0x18), end = I64(root + 0x20), capacity = I64(root + 0x28);
            if (begin == 0 && end == 0 && capacity == 0) return new("unavailable", "selected_manager_not_in_human_owners");
            if (begin < 65536 || (begin & 7) != 0 || end < begin || capacity < end || (end - begin) % 8 != 0 || (capacity - begin) % 8 != 0 || (capacity - begin) / 8 > 16)
                throw new InvalidOperationException();
            int matches = 0;
            for (long slot = begin; slot < end; slot += 8)
            {
                long owner = I64(slot);
                if (owner == 0) continue;
                Type(owner, 0x04CC086C);
                long person = checked(owner + 0x440);
                Type(person, 0x04CC08D8);
                if (person == selected) matches++;
            }
            if (matches != 1) return new("unavailable", matches == 0 ? "selected_manager_not_in_human_owners" : "duplicate_selected_manager_owner");
            int displacement = I32(selected - 4);
            if (displacement < 0 || displacement > 4096) throw new InvalidOperationException();
            long complete = checked(selected - displacement - 0x440);
            // The owner comparison above is the selection proof. The researched
            // virtual-base walk, not a guessed PERSON +offset, resolves the job.
            Type(complete, 0x04CC086C);
            long vbtable = I64(complete);
            int virtualOffset = I32(vbtable + 8);
            if (virtualOffset < 0 || virtualOffset > 8192) throw new InvalidOperationException();
            long contract = I64(checked(complete + virtualOffset + 0x80));
            if (contract == 0) return new("unavailable", "selected_manager_has_no_contract");
            Type(contract, 0x04B00AE8);
            if (I64(contract + 8) != selected) throw new InvalidOperationException();
            byte kind = Bytes(contract + 0x26, 1)[0];
            long team = I64(contract + 0x10);
            if (team == 0) return new("unavailable", "selected_manager_has_no_team");
            Type(team, 0x04CE1108);
            uint teamUid = Uid(team + 0x0C);
            long club = I64(team + 0x30);
            if (club == 0) return new("unavailable", "selected_manager_has_no_club");
            Type(club, 0x04CDA1F8);
            uint clubUid = Uid(club + 0x0C), uid = Uid(selected + 0x0C);
            if (BitConverter.ToUInt32(selectedIdentity, 4) != uid) throw new InvalidOperationException();
            foreach (var read in reads)
                if (!Exact(read.Address, read.Bytes.Length).SequenceEqual(read.Bytes)) return new("unavailable", "changed_during_read");
            // Recheck the selector last as well as all read relationship fields.
            if (BitConverter.ToInt64(Exact(image + 0x056F32C8, 8)) != selected) return new("unavailable", "changed_during_read");
            return new("available", Uid: uid, TeamUid: teamUid, ClubUid: clubUid, ContractKind: kind,
                ObservedAt: DateTimeOffset.UtcNow, Proof: "selected_human_owner");
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or IOException or OverflowException)
        { return new("unavailable", "read_failed"); }
    }
}
