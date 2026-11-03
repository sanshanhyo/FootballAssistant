namespace FootballAssistant.OffseasonReader;

public sealed record PositionFamiliarity(string Code, string NativeName, uint MaskBit, byte Value, bool Natural);
public sealed record NativePlayerPositions(string Status, string? Reason = null,
    IReadOnlyList<PositionFamiliarity>? Fields = null, uint? NaturalPositionMask = null,
    IReadOnlyList<string>? NaturalPositionCodes = null, byte? GoalkeeperFamiliarity = null,
    bool? IsGoalkeeper = null, byte? UnusedSlot151Raw = null,
    string Source = "native_position_familiarity", string? Proof = null,
    int NaturalThreshold = 18, int GoalkeeperThreshold = 15);

// Original reconstruction from FMAPI research 99aba1d2. This is familiarity,
// not a current match/tactic assignment. Player +0x151 is deliberately skipped.
public static class PositionFields
{
    private static readonly (int Index, string Code, string Name, uint Bit)[] Mapping = {
        (0, "GK", "Goalkeeper", 0x1), (2, "DL", "DefenderLeft", 0x8),
        (3, "DC", "DefenderCentre", 0x10), (4, "DR", "DefenderRight", 0x4),
        (5, "DM", "DefensiveMidfielderCentre", 0x80), (6, "ML", "MidfielderLeft", 0x200),
        (7, "MC", "MidfielderCentre", 0x400), (8, "MR", "MidfielderRight", 0x100),
        (9, "AML", "AttackingMidfielderLeft", 0x1000), (10, "AMC", "AttackingMidfielderCentre", 0x2000),
        (11, "AMR", "AttackingMidfielderRight", 0x800), (12, "ST", "AttackerCentre", 0x4000),
        (13, "WBL", "WingBackLeft", 0x40), (14, "WBR", "WingBackRight", 0x20)
    };
    // Caller supplies the exact, UID-bound, double-read block under a matched profile.
    internal static NativePlayerPositions Decode(byte[]? block)
    {
        if (block is null || block.Length != 15 || block.Any(value => value > 20))
            return new("unavailable", "invalid_position_block");
        var fields = Mapping.Select(item => new PositionFamiliarity(item.Code, item.Name, item.Bit, block[item.Index], block[item.Index] >= 18)).ToArray();
        uint mask = 0;
        foreach (var field in fields) if (field.Natural) mask |= field.MaskBit;
        return new("available", Fields: fields, NaturalPositionMask: mask,
            NaturalPositionCodes: fields.Where(field => field.Natural).Select(field => field.Code).ToArray(),
            GoalkeeperFamiliarity: block[0], IsGoalkeeper: block[0] >= 15, UnusedSlot151Raw: block[1],
            Proof: "exact_player_type_uid_double_read");
    }
}
