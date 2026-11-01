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
Console.WriteLine("Decoder checks passed");
