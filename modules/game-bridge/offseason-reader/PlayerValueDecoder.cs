namespace FootballAssistant.OffseasonReader;

// Decode only the fields supported by the checked match-reader evidence.
public static class PlayerValueDecoder
{
    public static byte? Attribute(byte value) => value is 0 or > 100 ? null : value;
    public static int? Height(int value) => value is >= 100 and <= 250 ? value : null;
    public static string? Date(uint value)
    {
        int year = (int)(value >> 16), day = (int)(value & 0x1FF);
        if (year is < 1900 or > 2100 || day < 1 || day > (DateTime.IsLeapYear(year) ? 366 : 365)) return null;
        return new DateTime(year, 1, 1).AddDays(day - 1).ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
    }
}
