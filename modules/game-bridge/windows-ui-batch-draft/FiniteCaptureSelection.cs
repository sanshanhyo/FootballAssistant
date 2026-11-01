namespace FootballAssistant.GameBridge;

// Fixed visible-page hypotheses derived from the existing Mac projection selectors.
// No runtime-supplied path, category, column, row count or alternate page selection.
internal sealed class FiniteCaptureSelection
{
    private readonly string[] paths;
    private FiniteCaptureSelection(string profile, string kind, string root, int rowStart, int rowCount,
        string[] paths, AttributeRowSelection? attribute = null)
    { Profile=profile; Kind=kind; FocusRoot=root; RowStart=rowStart; RowCount=rowCount;
      this.paths=paths; Attribute=attribute; }
    internal string Profile { get; }
    internal string Kind { get; }
    internal string FocusRoot { get; }
    internal string? Category => Attribute?.Category;
    internal int RowStart { get; }
    internal int RowCount { get; }
    internal AttributeRowSelection? Attribute { get; }
    internal string[] GetPaths() => (string[])paths.Clone();
    internal const string TacticsRoot = "0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0";
    // Diagnostic hypothesis only: the observed depth14 parent had one child, not Mac's child1.
    internal const string TacticsAlignmentParent = "0/4/0/0/0/0/0/0/0/0/0/0/0/0";
    internal const string TacticsAlignmentRoot = TacticsAlignmentParent + "/0/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0";
    internal const string TacticsSibling12Root = "0/4/0/0/0/0/0/0/0/0/0/0/1";
    internal const string TacticsSibling7Root = "0/4/0/0/0/0/0/1";
    internal const string TacticsSibling4Root = "0/4/0/0/1";
    internal const string TacticsFrontier35Root = "0/4/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/1";
    internal const string TacticsEligibilityRoot = "0/4/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0";
    internal const string NextMatchRoot = "0/6/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/1/0/0/0/2";
    internal const string ScheduleRoot = "0/4/0/0/0/0/0/1/0/0/0/0/0/0/1/0/5";
    private static readonly Dictionary<string, FiniteCaptureSelection> Pages = Build();
    private static Dictionary<string, FiniteCaptureSelection> Build()
    {
        var pages=new Dictionary<string,FiniteCaptureSelection>(StringComparer.Ordinal);
        pages.Add("tactics_current",new("tactics_current","tactics",TacticsRoot,-1,0,new[] { "0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/1/0/0/1/0", "0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/0", "0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/0/2/0/0/1/0/1", "0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0/2/0/0/0/0/0" }));
        pages.Add("tactics_alignment_candidate",new("tactics_alignment_candidate","tactics_alignment",
            TacticsAlignmentRoot,-1,0,pages["tactics_current"].GetPaths()
                .Select(path=>TacticsAlignmentRoot+path[TacticsRoot.Length..]).ToArray()));
        pages.Add("tactics_sibling12",new("tactics_sibling12","tactics_sibling_probe",TacticsSibling12Root,-1,0,Array.Empty<string>()));
        pages.Add("tactics_sibling7",new("tactics_sibling7","tactics_sibling_probe",TacticsSibling7Root,-1,0,Array.Empty<string>()));
        pages.Add("tactics_sibling4",new("tactics_sibling4","tactics_sibling_probe",TacticsSibling4Root,-1,0,Array.Empty<string>()));
        pages.Add("tactics_root_census",new("tactics_root_census","tactics_frontier_probe","0",-1,0,Array.Empty<string>()));
        pages.Add("tactics_frontier35",new("tactics_frontier35","tactics_frontier_probe",TacticsFrontier35Root,-1,0,Array.Empty<string>()));
        pages.Add("tactics_leaf_eligibility7",new("tactics_leaf_eligibility7","tactics_remaining_probe",TacticsEligibilityRoot,-1,0,
            new[]{"0/0/0","0/0/1","0/0/2","1/0/0/0/0","1/0/0/0/1/0","1/0/0/0/2/0","1/0/0/0/3/0"}
                .Select(suffix=>TacticsEligibilityRoot+"/"+suffix).ToArray()));
        pages.Add("tactics_ineligible_text7",new("tactics_ineligible_text7","tactics_ineligible_probe",TacticsEligibilityRoot,-1,0,
            pages["tactics_leaf_eligibility7"].GetPaths()));
        foreach(var (profile,suffix) in new[]{("tactics_remaining45_1","1/1"),("tactics_remaining46_1","1/0/1"),
            ("tactics_remaining46_2","1/0/2"),("tactics_remaining56_1","1/0/0/0/4/1"),("tactics_remaining56_2","1/0/0/0/4/2")})
            pages.Add(profile,new(profile,"tactics_remaining_probe",TacticsEligibilityRoot+"/"+suffix,-1,0,Array.Empty<string>()));
        pages.Add("next_match_card",new("next_match_card","next_match",NextMatchRoot,-1,0,new[] { "0/6/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/1/0/0/0/2/0/0/0/0/0/0/0", "0/6/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/1/0/0/0/2/0/0/0/0/0/1/0/1/0/0", "0/6/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/1/0/0/0/2/0/0/0/0/0/1/0/1/1/0/0/0/0" }));
        for(var row=0;row<10;row++)
        {
            var profile="schedule_row"+row.ToString(System.Globalization.CultureInfo.InvariantCulture);
            var rowRoot=ScheduleRoot+"/0/0/0/0/0/0/0/0/1/1/0/1/0/0/0/2/0/0/"+row.ToString(System.Globalization.CultureInfo.InvariantCulture);
            pages.Add(profile,new(profile,"schedule",ScheduleRoot,row,1,new[] { ScheduleRoot+"/0/0/0/0/0/0/0/0/1/1/0/0/0/0/0", rowRoot+"/0/0/0/0", rowRoot+"/1/0/0/0/0/0/0/0/0/0/0/1", rowRoot+"/2/0/0/0", rowRoot+"/4/0/0/0/0/0/0/1" }));
        }
        return pages;
    }
    internal static bool TryGet(string? profile,out FiniteCaptureSelection selection)
    {
        if(AttributeRowSelection.TryGet(profile,out var attribute))
        {
            selection=new(attribute.Profile,"attributes",attribute.FocusRoot,attribute.RowStart,attribute.RowCount,
                attribute.GetPaths(),attribute); return true;
        }
        selection=null!;
        return profile is not null && Pages.TryGetValue(profile,out selection!);
    }
    internal static string[] ManifestProfiles(string manifest) => manifest switch
    {
        "tactics_current" => new[] {"tactics_current"},
        "tactics_alignment_candidate" => new[] {"tactics_alignment_candidate"},
        "tactics_sibling_inventory" => new[] {"tactics_sibling12","tactics_sibling7","tactics_sibling4"},
        "tactics_layout_diagnostic" => new[] {"tactics_root_census","tactics_frontier35"},
        "tactics_remaining_diagnostic" => new[] {"tactics_leaf_eligibility7","tactics_remaining45_1","tactics_remaining46_1",
            "tactics_remaining46_2","tactics_remaining56_1","tactics_remaining56_2"},
        "tactics_ineligible_text7" => new[] {"tactics_ineligible_text7"},
        "next_match_card" => new[] {"next_match_card"},
        "schedule_rows0_9" => Enumerable.Range(0,10).Select(row=>"schedule_row"+row.ToString(System.Globalization.CultureInfo.InvariantCulture)).ToArray(),
        _ => AttributeRowSelection.ManifestProfiles(manifest)
    };
}
