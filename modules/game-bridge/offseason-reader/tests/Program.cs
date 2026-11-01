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
