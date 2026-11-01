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
Console.WriteLine("Decoder checks passed");
