namespace FootballAssistant.GameBridge;

// Pinned Mac display selectors; Windows verifies each requested title/row at runtime.
// Label list length limits capability, NOT proof that that many native rows exist.
internal sealed class AttributeRowSelection
{
    private readonly HashSet<string> labels;
    private AttributeRowSelection(string category, string title, string focusRoot, string[] allowedLabels,
        int first, int count)
    {
        Category = category; Title = title; FocusRoot = focusRoot; RowStart = first; RowCount = count;
        Profile = category + "_rows" + first + "_" + (first + count - 1);
        labels = new(allowedLabels, StringComparer.Ordinal);
    }
    internal string Category { get; }
    internal string Title { get; }
    internal string FocusRoot { get; }
    internal string Profile { get; }
    internal int RowStart { get; }
    internal int RowCount { get; }
    internal bool AllowsLabel(string label) => labels.Contains(label);
    internal string[] GetPaths()
    {
        var paths = new List<string>(1 + 2 * RowCount) { FocusRoot + "/0" };
        for (var row = RowStart; row < RowStart + RowCount; row++)
        {
            var root = FocusRoot + "/2/0/0/0/" + row.ToString(System.Globalization.CultureInfo.InvariantCulture);
            paths.Add(root + "/0/0/0/0/0/0/0/0/0");
            paths.Add(root + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0");
        }
        return paths.ToArray();
    }
    private static readonly Dictionary<string, AttributeRowSelection> Selections = Build();
    private static Dictionary<string, AttributeRowSelection> Build()
    {
        var selections = new Dictionary<string, AttributeRowSelection>(StringComparer.Ordinal);
        void Add(string category, string title, string root, string[] labels)
        {
            for (var first = 0; first < labels.Length; first += 2)
            {
                var selection = new AttributeRowSelection(category, title, root, labels, first, Math.Min(2, labels.Length-first));
                selections.Add(selection.Profile, selection);
            }
        }
        Add("goalkeeper", "守门", "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/0/0", new[] { "出击(倾向)", "传球", "大脚开球", "反应", "拦截传中", "拳击球(倾向)", "手控球", "手抛球", "停球", "一对一", "意外性", "指挥防守", "制空范围" });
        Add("mental", "精神", "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/1/0", new[] { "才华", "防守站位", "工作投入", "集中", "决断", "领导力", "侵略性", "视野", "团队合作", "无球跑动", "意志力", "勇敢", "预判", "镇定" });
        Add("physical", "身体", "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/2/0/0", new[] { "爆发力", "弹跳", "灵活", "耐力", "平衡", "强壮", "速度", "体质" });
        return selections;
    }
    internal static bool TryGet(string? profile, out AttributeRowSelection selection)
    {
        selection = null!;
        return profile is not null && Selections.TryGetValue(profile, out selection!);
    }
    // Fresh bounded list, not a request-supplied selector array.
    internal static string[] ManifestProfiles(string manifest) => manifest switch
    {
        "goalkeeper_rows0_3" => new[] { "goalkeeper_rows0_1", "goalkeeper_rows2_3" },
        "profile_rows0_3" => new[] { "goalkeeper_rows0_1", "goalkeeper_rows2_3", "mental_rows0_1",
            "mental_rows2_3", "physical_rows0_1", "physical_rows2_3" },
        "profile_all_rows" => new[] {
            "goalkeeper_rows0_1", "goalkeeper_rows2_3", "goalkeeper_rows4_5", "goalkeeper_rows6_7",
            "goalkeeper_rows8_9", "goalkeeper_rows10_11", "goalkeeper_rows12_12",
            "mental_rows0_1", "mental_rows2_3", "mental_rows4_5", "mental_rows6_7", "mental_rows8_9",
            "mental_rows10_11", "mental_rows12_13",
            "physical_rows0_1", "physical_rows2_3", "physical_rows4_5", "physical_rows6_7" },
        _ => throw new ArgumentException("Unknown fixed attribute manifest.")
    };
}
