namespace FootballAssistant.GameBridge;

// Structural display evidence only. Neither this title nor a user page-epoch assertion
// proves the player identity or that two chunks observed an unchanged page.
internal static class GroupedDiscoveryValidation
{
    internal static bool TryValidate(DiscoveryResult? result, string profile, out string[] labels)
    {
        labels = Array.Empty<string>();
        if (!AttributeRowSelection.TryGet(profile, out var selected) || result is null ||
            result.Status != "raw_diagnostics" || result.Reason != "approved_group_targets_complete" ||
            result.SelectionProfile != profile || result.PageIdentityVerified || result.TraversalBounded ||
            result.PanelIndex != 0 || result.FocusPath != selected.FocusRoot ||
            result.NativeOperations is < 0 or > 2048 || result.Nodes is < 1 or > 96 ||
            result.TotalRoots is < 0 or > 512 || result.PeakRoots is < 0 or > 64 ||
            !double.IsFinite(result.ElapsedMilliseconds) || result.ElapsedMilliseconds is < 0 or > 1000 ||
            result.Observations is null || result.Observations.Length != 1 + 2 * selected.RowCount) return false;
        var paths = TargetedDiscoveryCollector.GetTargetPaths(profile);
        var values = new string[paths.Length];
        for (var i = 0; i < paths.Length; i++)
        {
            var observation = result.Observations[i];
            if (observation is null || observation.Path != paths[i] || observation.Text is null ||
                observation.Text.Length is < 1 or > 128) return false;
            // No trimming, Unicode compatibility folding, markup stripping or value repair.
            values[i] = observation.Text.Replace("\u200b", "", StringComparison.Ordinal);
        }
        if (values[0] != selected.Title) return false;
        var observed = new HashSet<string>(StringComparer.Ordinal);
        for (var row = 0; row < selected.RowCount; row++)
            if (!selected.AllowsLabel(values[1 + row * 2]) || !observed.Add(values[1 + row * 2]) ||
                !Rating(values[2 + row * 2])) return false;
        labels = Enumerable.Range(0, selected.RowCount).Select(row => values[1 + row * 2]).ToArray();
        return true;
    }

    private static bool Rating(string value) => value.Length is 1 or 2 &&
        value.All(c => c is >= '0' and <= '9') && value[0] != '0' &&
        int.TryParse(value, System.Globalization.NumberStyles.None,
            System.Globalization.CultureInfo.InvariantCulture, out var parsed) && parsed is >= 1 and <= 20;
}
