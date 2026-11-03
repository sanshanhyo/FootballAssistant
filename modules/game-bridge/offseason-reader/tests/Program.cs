#nullable enable
using FootballAssistant.OffseasonReader;

static void Check(bool value) { if (!value) throw new Exception("Decoder check failed"); }
Check(PlayerValueDecoder.Attribute(0) is null);
Check(PlayerValueDecoder.Attribute(101) is null);
Check(PlayerValueDecoder.Attribute(60) == 60);
Check(PlayerValueDecoder.Height(188) == 188);
Check(PlayerValueDecoder.Height(0) is null);
Check(PlayerValueDecoder.Date((2024u << 16) | 60u) == "2024-02-29");
Check(PlayerValueDecoder.Date((2024u << 16) | 0x1A00u | 60u) == "2024-02-29");
Check(PlayerValueDecoder.Date((2023u << 16) | 366u) is null);
Check(PlayerValueDecoder.Date(0) is null);
Check(PlayerValueDecoder.Affiliation(1, 2, new byte[] { 65, 0 }) == new CandidateAffiliation(1, 2, "A"));
Check(PlayerValueDecoder.Affiliation(0, 2, new byte[] { 65, 0 }) is null);
Check(PlayerValueDecoder.Affiliation(1, 2, new byte[] { 0xFF, 0 }) is null);
Check(PlayerValueDecoder.Affiliation(1, 2, new byte[] { 65 }) is null);
// Invalid requests must fail before touching any process.
Check(TeamCandidateLookup.Read(0, 1).Status == "invalid_input");
Check(TeamCandidateLookup.Read(1, 0).Players is null);
Check(ManagerCandidateLookup.Read(0, 1).Status == "unknown");
Check(ManagerCandidateLookup.Read(1, 0).Status == "unknown");
Check(PlayerValueDecoder.Contract(0, 0, 0).WageRaw is null);
Check(PlayerValueDecoder.Contract(-1, 0, 0).StartDate is null);
Check(PlayerValueDecoder.Contract(1234, (2023u << 16) | 365u, (2027u << 16) | 365u) == new PlayerContractCandidate("experimental", "2023-12-31", "2027-12-31", 1234));
var ids = Enumerable.Repeat(byte.MaxValue, 44).ToArray();
var numbers = Enumerable.Repeat(byte.MaxValue, 11).ToArray();
BitConverter.GetBytes(123u).CopyTo(ids, 0); numbers[0] = 7;
var identity = new TacticIdentity(123, 456, "Synthetic", "Synthetic", "", "");
Check(TacticPlayerAssociations.Match(ids, numbers, new TacticIdentity?[] { identity }, false)[0] == new TacticPlayerCandidate("experimental_candidate", 456, "Synthetic", 7));
Check(TacticPlayerAssociations.Match(ids, numbers, Array.Empty<TacticIdentity?>(), false)[0].Status == "unknown");
Check(TacticPlayerAssociations.Match(ids, numbers, new TacticIdentity?[] { identity, identity }, false)[0].Status == "unknown");
Check(TacticPlayerAssociations.Match(ids, numbers, new TacticIdentity?[] { identity }, true)[0].Status == "unknown");
BitConverter.GetBytes(123u).CopyTo(ids, 4);
Check(TacticPlayerAssociations.Match(ids, numbers, new TacticIdentity?[] { identity }, false)[0].Status == "unknown");
Console.WriteLine("Decoder checks passed");
// Synthetic packed positions and roles: no real game samples.
Check(TacticCandidateLookup.Read(0, 1).Status == "invalid_input");
Check(TacticCandidateLookup.Decode(null) is null);
Check(TacticCandidateLookup.Decode(new byte[21]) is null);
var syntheticTactic = new byte[22];
ushort packedGk = (ushort)(((108 << 6) | 49)); // signed indices: role -20, position -15
syntheticTactic[0] = (byte)packedGk;
syntheticTactic[1] = (byte)(packedGk >> 8);
ushort packedUnknown = (ushort)((64 << 6) | 32); // both outside mapped ranges
syntheticTactic[2] = (byte)packedUnknown;
syntheticTactic[3] = (byte)(packedUnknown >> 8);
var decodedTactic = TacticCandidateLookup.Decode(syntheticTactic)!;
Check(decodedTactic.Positions.Count == 11 && decodedTactic.Positions[0] == "0x1");
Check(decodedTactic.RolesDuties[0] == "Ball-Playing Goalkeeper / Support");
Check(decodedTactic.Positions[1] == "unknown" && decodedTactic.RolesDuties[1] == "unknown");
// Synthetic role mapping, independent of saved game samples.
Check(TacticSecondRoleDecoder.Decode(0x800002) == "0x800002: Sweeper Keeper / Attack");
Check(TacticSecondRoleDecoder.Decode(0x1000000000000000) == "unknown");
Check(TacticSecondRoleDecoder.Decode(0xE00002) == "0xE00002: Sweeper Keeper / unknown");
// Synthetic target first-group role masks; no game sample.
Check(TacticFirstRoleDecoder.Decode(0x401000) == "Ball-Playing Goalkeeper / Support");
Check(TacticFirstRoleDecoder.Decode(0x1000000000000000) == "unknown");
Check(TacticFirstRoleDecoder.Decode(0xE01000) == "Ball-Playing Goalkeeper / unknown");
// Synthetic process-local generation checks: no process or game data accessed.
var generationType = typeof(TacticCandidateLookup).Assembly.GetType("FootballAssistant.OffseasonReader.TacticGeneration")!;
var generationMethod = generationType.GetMethod("Create", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!;
string Generation(int pid, long start, long target) => (string)generationMethod.Invoke(null, new object[] { pid, start, 11L, 12L, 13L, 14L, 15L, 16L, target })!;
var syntheticGeneration = Generation(101, 999, 17);
Check(syntheticGeneration.StartsWith("process-local:") && syntheticGeneration == Generation(101, 999, 17));
Check(syntheticGeneration != Generation(101, 999, 18));
Check(syntheticGeneration != Generation(102, 999, 17));
Check(syntheticGeneration != Generation(101, 1000, 17));
// Synthetic native mentality IDs, no sample and no assumed UI name mapping.
Check(TacticMentalityDecoder.Candidate(0) is null);
Check(TacticMentalityDecoder.Candidate(1) == 1);
Check(TacticMentalityDecoder.Candidate(7) == 7);
Check(TacticMentalityDecoder.Candidate(8) is null);
// Synthetic bitset; source and target data are not real game samples.
Check(TeamInstructionDecoder.Decode(null, 0) is null);
Check(TeamInstructionDecoder.Decode(0, null) is null);
var emptyInstructions = TeamInstructionDecoder.Decode(0, 0)!;
Check(emptyInstructions.Status == "experimental" && emptyInstructions.Ids.Count == 0 && !emptyInstructions.PassingStyleShorter);
var syntheticInstructions = TeamInstructionDecoder.Decode((1UL << 0) | (1UL << 3) | (1UL << 63), (1UL << 0) | (1UL << 19) | (1UL << 20))!;
Check(syntheticInstructions.Ids.SequenceEqual(new[] { 3, 63, 64, 83 }) && syntheticInstructions.PassingStyleShorter);
// Synthetic bounded calendar validation; no game data.
var syntheticStart = new DateTime(2030, 2, 1);
Check(FixtureCalendarLookup.IsValidRange(syntheticStart, syntheticStart.AddDays(29)));
Check(!FixtureCalendarLookup.IsValidRange(syntheticStart, syntheticStart.AddDays(30)));
Check(!FixtureCalendarLookup.IsValidRange(syntheticStart, syntheticStart.AddDays(-1)));
Check(!FixtureCalendarLookup.IsValidRange(new DateTime(2030, 12, 31), new DateTime(2031, 1, 1)));
Check(!FixtureCalendarLookup.IsValidRange(syntheticStart.AddHours(1), syntheticStart.AddDays(1)));
Check(FixtureCalendarLookup.Read(0, 1, syntheticStart, syntheticStart).Status == "unknown");
var syntheticFixtures = new[] { new FixtureCalendarEntry("2030-02-03", 1, 9, "A", "first"), new FixtureCalendarEntry("2030-02-01", 2, 4, "B", "second") };
var syntheticPartial = FixtureCalendarLookup.Finish(3, 1, 0, 2, syntheticFixtures, DateTimeOffset.UnixEpoch);
Check(syntheticPartial.Status == "partial" && syntheticPartial.Fixtures![0].Date == "2030-02-01");
Check(FixtureCalendarLookup.Finish(3, 0, 1, 2, syntheticFixtures, DateTimeOffset.UnixEpoch).Status == "partial");
Check(FixtureCalendarLookup.Finish(3, 0, 0, 2, syntheticFixtures, DateTimeOffset.UnixEpoch).Status == "experimental_loaded_buckets_only");
Check(FixtureCalendarLookup.VenueCandidate(0x02, 11, 11) == "home");
Check(FixtureCalendarLookup.VenueCandidate(0x02, 12, 11) == "away");
Check(FixtureCalendarLookup.VenueCandidate(0x00, 11, 11) == "unknown");
Check(FixtureCalendarLookup.VenueCandidate(0x04, 11, 11) == "unknown");
var syntheticCrossing = FixtureCalendarLookup.Days(new DateTime(2030, 2, 25), new DateTime(2030, 3, 3)).ToArray();
Check(syntheticCrossing.Length == 7 && syntheticCrossing[0] == new DateTime(2030, 2, 25) && syntheticCrossing[^1] == new DateTime(2030, 3, 3));
Check(FixtureCalendarLookup.LoadedState(0) == "unloaded" && FixtureCalendarLookup.LoadedState(1) == "loaded" && FixtureCalendarLookup.LoadedState(2) == "unknown");
byte[] syntheticMemory = { 1, 2, 3, 4 };
var syntheticTracked = new FixtureCalendarLookup.Tracked((address, length) => syntheticMemory.ToArray());
Check(syntheticTracked.Bytes(65536, 4).SequenceEqual(syntheticMemory) && syntheticTracked.Stable());
syntheticMemory[1] = 9;
Check(!syntheticTracked.Stable());
var syntheticShortRead = new FixtureCalendarLookup.Tracked((address, length) => new byte[length - 1]);
try { syntheticShortRead.Bytes(65536, 4); throw new Exception("short read accepted"); } catch (InvalidOperationException) { }
try { syntheticTracked.Bytes(0, 4); throw new Exception("bad address accepted"); } catch (InvalidOperationException) { }

// Alpha8 synthetic native selection and familiarity regressions. No game process,
// private samples, SDK, UI, or installed game files are needed by these tests.
NativeIdentityChecks.Run();

static class NativeIdentityChecks
{
    const long Image = 0x10000000, Root = 0x20000000, Owners = 0x20001000,
        Owner = 0x20002000, Person = Owner + 0x440, Contract = 0x20003000,
        Team = 0x20004000, Club = 0x20005000, Players = 0x20010000, FirstPlayer = 0x30000000;
    static readonly NativeReadProfile Profile = NativeReadProfile.FromHashes(NativeReadProfile.NativeHash, NativeReadProfile.AssemblyHash, NativeReadProfile.MetadataHash);
    static void Assert(bool value, string name) { if (!value) throw new Exception("Native identity check failed: " + name); }
    static NativeManagerResult Read(FakeNative memory) => new NativeManagerReader(memory, Image).Read();
    static FakeNative Fixture(int players = 0)
    {
        var memory = new FakeNative();
        memory.Q(Image + 0x056F32C8, Person); memory.Q(Image + 0x056F3008, Root);
        memory.Q(Root, Image + 0x04E2D678); memory.Q(Root + 8, Image + 0x04E2D688);
        memory.Q(Root + 0x18, Owners); memory.Q(Root + 0x20, Owners + 8); memory.Q(Root + 0x28, Owners + 8); memory.Q(Owners, Owner);
        memory.Q(Owner, Image + 0x04CC086C); memory.D(Image + 0x04CC086C + 8, 0x468);
        memory.Q(Person, Image + 0x04CC08D8); memory.D(Person - 4, 0); memory.D(Person + 8, 19); memory.D(Person + 0x0C, 123);
        memory.Q(Person + 0xA8, Contract); memory.Q(Contract, Image + 0x04B00AE8); memory.Q(Contract + 8, Person);
        memory.Q(Contract + 0x10, Team); memory.B(Contract + 0x26, 0);
        memory.Q(Team, Image + 0x04CE1108); memory.D(Team + 0x0C, 10); memory.Q(Team + 0x30, Club);
        memory.Q(Club, Image + 0x04CDA1F8); memory.D(Club + 0x0C, 406);
        memory.Q(Team + 0x38, Players); memory.Q(Team + 0x40, Players + players * 8); memory.Q(Team + 0x48, Players + players * 8);
        for (int i = 0; i < players; i++)
        {
            long player = FirstPlayer + i * 0x1000;
            memory.Q(Players + i * 8, player); memory.Q(player, Image + 0x04D27228); memory.Q(player + 8, Image + 0x04D2720C);
            memory.Q(player + 0x288, Image + 0x04D27758); memory.D(player + 0x284, 0); memory.D(player + 0x294, 1000 + i);
            memory.Q(player + 0x288 + 0x50, 0); memory.Q(player + 0x288 + 0x58, 0); memory.Q(player + 0x288 + 0x60, 0);
            memory.Q(player + 0x130, Team);
            var block = new byte[15]; block[0] = (byte)(i == 0 ? 15 : 1); block[2] = 18; block[1] = 20;
            memory.Put(player + 0x150, block);
        }
        return memory;
    }
    public static void Run()
    {
        Assert(Profile.Matched && Profile.Status == "available", "three matching fingerprints");
        Assert(!NativeReadProfile.FromHashes("bad", NativeReadProfile.AssemblyHash, NativeReadProfile.MetadataHash).Matched, "native fingerprint");
        Assert(!NativeReadProfile.FromHashes(NativeReadProfile.NativeHash, "bad", NativeReadProfile.MetadataHash).Matched, "assembly fingerprint");
        Assert(!NativeReadProfile.FromHashes(NativeReadProfile.NativeHash, NativeReadProfile.AssemblyHash, "bad").Matched, "metadata fingerprint");
        Assert(!new NativeReadProfile("available").Matched, "status alone is not profile proof");
        Assert(NativeManagerLookup.Read(0).Status == "unavailable", "invalid pid before process access");
        Assert(NativeManagerLookup.Read(1, new("unavailable", "unsupported_native_profile")).Reason == "unsupported_native_profile", "profile gate before process access");
        var memory = Fixture(); var manager = Read(memory);
        Assert(manager.Status == "available" && manager.Uid == 123 && manager.TeamUid == 10 && manager.ClubUid == 406, "exact selected employment binding");
        Assert(manager.Proof == "selected_human_owner" && manager.Source == "native_gcUM_selection" && !manager.AtomicSnapshot, "limited source and proof");
        Assert(NativeManagerResult.SameBinding(manager, manager with { ObservedAt = DateTimeOffset.UnixEpoch }), "observation time is not binding");
        Assert(!NativeManagerResult.SameBinding(manager, manager with { Uid = 124 }), "selection change");
        Assert(!NativeManagerResult.SameBinding(manager, manager with { ClubUid = 407 }), "employment change");
        Assert(!NativeManagerResult.SameBinding(manager, manager with { Status = "unavailable" }), "unavailable is not binding");
        memory = Fixture(); memory.Q(Image + 0x056F32C8, 0);
        Assert(Read(memory).Reason == "no_current_manager_selection", "zero selection never inferred from sole candidate");
        memory = Fixture(); memory.Q(Root + 0x20, Owners);
        Assert(Read(memory).Status == "unavailable", "selected record not owned");
        memory = Fixture(); memory.Q(Root + 0x20, Owners + 16); memory.Q(Root + 0x28, Owners + 16); memory.Q(Owners + 8, Owner);
        Assert(Read(memory).Reason == "duplicate_selected_manager_owner", "duplicate selection ownership");
        memory = Fixture(); memory.Q(Person, Image + 0x04D27758);
        Assert(Read(memory).Status == "unavailable", "nonhuman selector");
        memory = Fixture(); memory.Q(Contract + 8, Person + 8);
        Assert(Read(memory).Status == "unavailable", "contract owner mismatch");
        memory = Fixture(); memory.Q(Team, 0);
        Assert(Read(memory).Status == "unavailable", "unsupported employment payload");
        memory = Fixture(); memory.Q(Club, 0);
        Assert(Read(memory).Status == "unavailable", "unsupported employment club");
        memory = Fixture(); memory.D(Club + 0x0C, 0);
        Assert(Read(memory).Status == "unavailable", "invalid linked UID");
        memory = Fixture(); memory.Q(Root + 0x28, Owners + 17 * 8);
        Assert(Read(memory).Status == "unavailable", "human vector capacity bounded");
        memory = Fixture(); memory.D(Person - 4, -1);
        Assert(Read(memory).Status == "unavailable", "negative displacement");
        memory = Fixture(); memory.D(Image + 0x04CC086C + 8, 8193);
        Assert(Read(memory).Status == "unavailable", "virtual displacement bounded");
        memory = Fixture(); memory.ShortRead = true;
        Assert(Read(memory).Status == "unavailable", "short transport read");
        memory = Fixture(); memory.Mutation = (address, count, visits) => address == Image + 0x056F32C8 && visits == 2 ? BitConverter.GetBytes(0L) : null;
        Assert(Read(memory).Reason == "changed_during_read", "selection changed on second read");
        memory = Fixture(); memory.Mutation = (address, count, visits) => address == Contract + 0x10 && visits == 2 ? BitConverter.GetBytes(Team + 8) : null;
        Assert(Read(memory).Reason == "changed_during_read", "employment changed on second read");
        var block = new byte[15]; block[0] = 20; block[1] = 20; block[2] = 18; block[3] = 17;
        var positions = PositionFields.Decode(block);
        Assert(positions.Fields!.Count == 14 && positions.NaturalPositionMask == 9 && positions.NaturalPositionCodes!.SequenceEqual(new[] { "GK", "DL" }), "named left mapping and skipped slot");
        block[0] = 15; positions = PositionFields.Decode(block);
        Assert(positions.IsGoalkeeper == true && !positions.Fields![0].Natural && positions.NaturalPositionMask == 8, "15 GK is not natural");
        block[0] = 14; Assert(PositionFields.Decode(block).IsGoalkeeper == false, "14 GK boundary");
        block[0] = 17; Assert(!PositionFields.Decode(block).Fields![0].Natural, "17 natural boundary");
        block[0] = 18; Assert(PositionFields.Decode(block).Fields![0].Natural, "18 natural boundary");
        var codes = new[] { "GK", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST", "WBL", "WBR" };
        var bits = new uint[] { 1, 8, 16, 4, 128, 512, 1024, 256, 4096, 8192, 2048, 16384, 64, 32 };
        for (int i = 0; i < 14; i++)
        {
            block = new byte[15]; block[i == 0 ? 0 : i + 1] = 18; positions = PositionFields.Decode(block);
            Assert(positions.NaturalPositionMask == bits[i] && positions.NaturalPositionCodes!.Single() == codes[i], "all 14 source offsets/bits " + codes[i]);
        }
        foreach (var invalid in new byte[]?[] { null, new byte[14], new byte[16], Enumerable.Repeat((byte)21, 15).ToArray() })
            Assert(PositionFields.Decode(invalid).Status == "unavailable", "malformed position block");
        memory = Fixture(27);
        var team = TeamCandidateLookup.ReadSnapshot(memory.Read, Image, 406, Profile);
        Assert(team.Status == "experimental_candidates_incomplete" && team.Players!.Count == 27, "bounded 27-player roster pass");
        Assert(team.Players![0].Positions!.IsGoalkeeper == true && team.Players.Skip(1).All(player => player.Positions!.IsGoalkeeper == false), "UID-linked roster positions");
        Assert(memory.BlockReads == 54 && !memory.ReadAddresses.Contains(Image + 0x05703738), "two position reads per player with no PERSON table rescans");
        Assert(memory.TotalBytes < 65536, "aggregate memory byte bound");
        memory = Fixture(1); memory.Mutation = (address, count, visits) => address == FirstPlayer + 0x150 && visits == 2 ? new byte[15] : null;
        Assert(TeamCandidateLookup.ReadSnapshot(memory.Read, Image, 406, Profile).Status == "changed_during_read", "roster position mutation");
        memory = Fixture(1); memory.B(FirstPlayer + 0x150, 21);
        team = TeamCandidateLookup.ReadSnapshot(memory.Read, Image, 406, Profile);
        Assert(team.Players![0].Positions!.Status == "unavailable", "invalid familiarity not fabricated");
        memory = Fixture(2); memory.D(FirstPlayer + 0x1000 + 0x294, 1000);
        Assert(TeamCandidateLookup.ReadSnapshot(memory.Read, Image, 406, Profile).Status == "unavailable", "duplicate roster UID");
        memory = Fixture(65); team = TeamCandidateLookup.ReadSnapshot(memory.Read, Image, 406, Profile);
        Assert(team.Truncated == true && team.Players!.Count == 64, "existing roster cap preserved");
        memory = Fixture(1); team = TeamCandidateLookup.ReadSnapshot(memory.Read, Image, 406, new("unavailable", "unsupported_native_profile"));
        Assert(team.Status == "experimental_candidates_incomplete" && team.Players![0].Positions!.Status == "unavailable" && memory.BlockReads == 0, "legacy roster survives unsupported semantic profile");
        Console.WriteLine("Native identity and position synthetic checks passed");
    }
    sealed class FakeNative : ManagerCandidates.IReadOnlyMemory
    {
        readonly Dictionary<long, byte> data = new();
        readonly Dictionary<long, int> visits = new();
        public readonly HashSet<long> ReadAddresses = new();
        public Func<long, int, int, byte[]?>? Mutation;
        public bool ShortRead;
        public int BlockReads, TotalBytes;
        public void Q(long address, long value) => Put(address, BitConverter.GetBytes(value));
        public void D(long address, int value) => Put(address, BitConverter.GetBytes(value));
        public void B(long address, byte value) => Put(address, new[] { value });
        public void Put(long address, byte[] bytes) { for (int i = 0; i < bytes.Length; i++) data[address + i] = bytes[i]; }
        public byte[] Read(long address, int length)
        {
            ReadAddresses.Add(address); TotalBytes += length; if (length == 15) BlockReads++;
            int visit = visits.TryGetValue(address, out int previous) ? previous + 1 : 1; visits[address] = visit;
            var changed = Mutation?.Invoke(address, length, visit); if (changed is not null) return changed;
            if (ShortRead) return new byte[length - 1];
            var bytes = new byte[length];
            for (int i = 0; i < length; i++) if (!data.TryGetValue(address + i, out bytes[i])) throw new InvalidOperationException("Missing synthetic address");
            return bytes;
        }
    }
}
