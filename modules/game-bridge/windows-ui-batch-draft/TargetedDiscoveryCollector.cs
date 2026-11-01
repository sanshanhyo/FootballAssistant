namespace FootballAssistant.GameBridge;

// Exactly one source-defined goalkeeper category/row0, not a generic FM query API.
// Mac selectors provide the hypothesis; Windows paths and row0 label remain unverified.
internal static class TargetedDiscoveryCollector
{
    internal const int MaximumDepth = 48;
    internal const string FocusRoot = DiscoveryCandidateConfiguration.GoalkeeperRow0FocusPath;
    internal const string TitlePath = FocusRoot + "/0";
    internal const string RowRoot = FocusRoot + "/2/0/0/0/0";
    internal const string LabelPath = RowRoot + "/0/0/0/0/0/0/0/0/0";
    internal const string ValuePath = RowRoot + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0";

    internal static DiscoveryResult? Run(DiscoveryPolicy policy, DiscoveryRequest request,
        Func<BatchNativeBackend> createBackend, Func<WindowsThreadIdentity> freshIdentity,
        Func<DateTimeOffset> now, CancellationToken cancellation = default, Func<double>? elapsedForTest = null)
        => DiscoveryCollector.RunCore(policy, request, createBackend, freshIdentity, now,
            cancellation, elapsedForTest, targetedRow: true);

    // Fresh bounded arrays, never retained across requests or supplied from the request.
    internal static int[][] CreateTargets(string profile = "single")
    {
        var paths = GetTargetPaths(profile);
        if (paths.Any(path => !IsAllowedTargetPath(path))) throw new InvalidOperationException("Invalid fixed target depth.");
        return paths.Select(path => path[(FocusRoot.Length + 1)..].Split('/')
            .Select(int.Parse).ToArray()).ToArray();
    }
    internal static bool ValidSelection(string profile, int panel, string focus) =>
        profile == "single" || (profile is "goalkeeper_rows0_1" or "goalkeeper_rows2_3") &&
        panel == 0 && focus == FocusRoot;

    internal static string[] GetTargetPaths(string profile)
    {
        if (profile == "single") return new[] { TitlePath, LabelPath, ValuePath };
        var first = profile switch { "goalkeeper_rows0_1" => 0, "goalkeeper_rows2_3" => 2,
            _ => throw new ArgumentException("Unknown fixed selection.") };
        var paths = new List<string>(5) { TitlePath };
        for (var row = first; row < first + 2; row++)
        {
            var root = FocusRoot + "/2/0/0/0/" + row.ToString(System.Globalization.CultureInfo.InvariantCulture);
            paths.Add(root + "/0/0/0/0/0/0/0/0/0");
            paths.Add(root + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0");
        }
        return paths.ToArray();
    }
    // Pure validation hook: it cannot activate a custom target or perform native calls.
    internal static bool IsAllowedTargetPath(string? path)
    {
        if (path is null || path.Length > 191 || !path.StartsWith(FocusRoot + "/", StringComparison.Ordinal)) return false;
        var edges = path.Split('/');
        return edges.Length <= MaximumDepth && edges.All(part => part.Length is > 0 and <= 3 &&
            (part.Length == 1 || part[0] != '0') && part.All(c => c is >= '0' and <= '9') &&
            int.TryParse(part, out var value) && value <= 511);
    }
}
