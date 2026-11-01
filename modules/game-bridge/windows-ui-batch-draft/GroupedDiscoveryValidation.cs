namespace FootballAssistant.GameBridge;

// Structural display evidence only. Neither this title nor a user page-epoch assertion
// proves the player identity or that two chunks observed an unchanged page.
internal static class GroupedDiscoveryValidation
{
    // Matches the Mac goalkeeper category's observed-label allowlist, not row ordering.
    private static readonly HashSet<string> Labels = new(StringComparer.Ordinal)
    {
        "出击(倾向)", "传球", "大脚开球", "反应", "拦截传中", "拳击球(倾向)",
        "手控球", "手抛球", "停球", "一对一", "意外性", "指挥防守", "制空范围"
    };

    internal static bool TryValidate(DiscoveryResult? result, string profile, out string[] labels)
    {
        labels = Array.Empty<string>();
        if (profile is not ("goalkeeper_rows0_1" or "goalkeeper_rows2_3") || result is null ||
            result.Status != "raw_diagnostics" || result.Reason != "approved_group_targets_complete" ||
            result.SelectionProfile != profile || result.PageIdentityVerified || result.TraversalBounded ||
            result.PanelIndex != 0 || result.FocusPath != TargetedDiscoveryCollector.FocusRoot ||
            result.NativeOperations is < 0 or > 2048 || result.Nodes is < 1 or > 96 ||
            result.TotalRoots is < 0 or > 512 || result.PeakRoots is < 0 or > 64 ||
            !double.IsFinite(result.ElapsedMilliseconds) || result.ElapsedMilliseconds is < 0 or > 1000 ||
            result.Observations is null || result.Observations.Length != 5) return false;
        var paths = TargetedDiscoveryCollector.GetTargetPaths(profile);
        var values = new string[5];
        for (var i = 0; i < paths.Length; i++)
        {
            var observation = result.Observations[i];
            if (observation is null || observation.Path != paths[i] || observation.Text is null ||
                observation.Text.Length is < 1 or > 128) return false;
            // No trimming, Unicode compatibility folding, markup stripping or value repair.
            values[i] = observation.Text.Replace("\u200b", "", StringComparison.Ordinal);
        }
        if (values[0] != "守门" || !Labels.Contains(values[1]) || !Labels.Contains(values[3]) ||
            values[1] == values[3] || !Rating(values[2]) || !Rating(values[4])) return false;
        labels = new[] { values[1], values[3] };
        return true;
    }

    private static bool Rating(string value) => value.Length is 1 or 2 &&
        value.All(c => c is >= '0' and <= '9') && value[0] != '0' &&
        int.TryParse(value, System.Globalization.NumberStyles.None,
            System.Globalization.CultureInfo.InvariantCulture, out var parsed) && parsed is >= 1 and <= 20;
}
