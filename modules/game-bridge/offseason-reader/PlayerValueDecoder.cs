namespace FootballAssistant.OffseasonReader;

// Decode only the fields supported by the checked match-reader evidence.
public static class PlayerValueDecoder
{
    public static byte? Attribute(byte value) => value is 0 or > 100 ? null : value;
    public static int? Height(int value) => value is >= 100 and <= 250 ? value : null;
    public static PlayerContractCandidate Contract(int rawWage, uint rawStart, uint rawEnd) =>
        new("experimental", Date(rawStart), Date(rawEnd), rawWage > 0 ? rawWage : null);
    public static CandidateAffiliation? Affiliation(uint teamUid, uint clubUid, byte[] nameBytes)
    {
        int length = Array.IndexOf(nameBytes, (byte)0);
        if (teamUid is 0 or uint.MaxValue || clubUid is 0 or uint.MaxValue || length <= 0 || nameBytes.Length > 64) return null;
        try
        {
            string name = new System.Text.UTF8Encoding(false, true).GetString(nameBytes, 0, length).Trim();
            return string.IsNullOrWhiteSpace(name) ? null : new(teamUid, clubUid, name);
        }
        catch (System.Text.DecoderFallbackException) { return null; }
    }
    public static string? Date(uint value)
    {
        int year = (int)(value >> 16), day = (int)(value & 0x1FF);
        if (year is < 1900 or > 2100 || day < 1 || day > (DateTime.IsLeapYear(year) ? 366 : 365)) return null;
        return new DateTime(year, 1, 1).AddDays(day - 1).ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
    }
}
