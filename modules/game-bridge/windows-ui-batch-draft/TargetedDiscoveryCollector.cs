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

    // Fresh fixed-plan arrays. No caller-supplied paths or row indices.
    internal static string TargetFocus(string profile) => profile == "single" ? FocusRoot :
        AttributeRowSelection.TryGet(profile, out var selected) ? selected.FocusRoot :
        throw new ArgumentException("Unknown fixed selection.");
    internal static int[][] CreateTargets(string profile = "single")
    {
        var root = TargetFocus(profile);
        var paths = GetTargetPaths(profile);
        if (paths.Any(path => !ValidTarget(path, root))) throw new InvalidOperationException("Invalid fixed target depth.");
        return paths.Select(path => path[(root.Length + 1)..].Split('/')
            .Select(int.Parse).ToArray()).ToArray();
    }
    internal static bool ValidSelection(string profile, int panel, string focus) =>
        profile == "single" || AttributeRowSelection.TryGet(profile, out var selected) &&
        panel == 0 && focus == selected.FocusRoot;
    internal static string[] GetTargetPaths(string profile) => profile == "single" ?
        new[] { TitlePath, LabelPath, ValuePath } :
        AttributeRowSelection.TryGet(profile, out var selected) ? selected.GetPaths() :
        throw new ArgumentException("Unknown fixed selection.");
    // Pure validation hook: it cannot activate a custom target or perform native calls.
    internal static bool IsAllowedTargetPath(string? path) => ValidTarget(path, FocusRoot);
    private static bool ValidTarget(string? path, string root)
    {
        if (path is null || path.Length > 191 || !path.StartsWith(root + "/", StringComparison.Ordinal)) return false;
        var edges = path.Split('/');
        return edges.Length <= MaximumDepth && edges.All(part => part.Length is > 0 and <= 3 &&
            (part.Length == 1 || part[0] != '0') && part.All(c => c is >= '0' and <= '9') &&
            int.TryParse(part, out var value) && value <= 511);
    }
}
