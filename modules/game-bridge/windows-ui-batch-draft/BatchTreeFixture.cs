using System.Reflection;
using System.Runtime.InteropServices;
using FootballAssistant.GameBridge;

// Own allocated fixture buffers + managed delegates; never loads or calls GameAssembly.
sealed class BatchTreeFixture : IDisposable
{
    internal readonly Dictionary<nint, List<nint>> Children = new();
    private readonly Dictionary<nint, nint> nodeTexts = new();
    private readonly Dictionary<nint, (string Text, nint Chars)> textObjects = new();
    private int nextNode = 10000, nextText = 20000, panelOpens;
    internal int PanelOpens => panelOpens;
    internal bool ChangePostAnchor, CycleBody, FailFirstFree;
    internal string BodyPath { get; private set; } = "";
    internal const string Anchor1Path = "0/0/0/0/0/0/0/0/0/0/0/0/0/0";
    internal const string Anchor2Path = "1/0/0/0/0/0/0/0/0/0/0/0/0/0";
    private nint anchor1, changedAnchor;
    private nint TextObject(string text)
    {
        var id = nextText++; var pointer = Marshal.StringToHGlobalUni(text); allocations.Add(pointer);
        textObjects[id] = (text, pointer); return id;
    }
    private nint Chain(int depth, nint parent = 103)
    {
        for (var i = 0; i < depth; i++)
        {
            nint child = nextNode++; Children[child] = new();
            Children[parent].Add(child); parent = child;
        }
        return parent;
    }
    internal void Build(int depth, int fields = 4)
    {
        Children[103] = new();
        anchor1 = Chain(14); nodeTexts[anchor1] = TextObject("fixture-page");
        var anchor2 = Chain(14); nodeTexts[anchor2] = TextObject("fixture-subject");
        var body = Chain(depth);
        BodyPath = "2" + string.Concat(Enumerable.Repeat("/0", depth - 1));
        for (var i = 0; i < fields; i++)
        {
            nint leaf = nextNode++; Children[leaf] = new(); Children[body].Add(leaf);
            nodeTexts[leaf] = TextObject("synthetic-field-" + i);
        }
        if (CycleBody) { Children[body].Clear(); Children[body].Add(body); }
        changedAnchor = TextObject("changed-page");
    }
    internal readonly HashSet<nint> HiddenNodes = new();
    internal void BuildDiscovery(int bodyDepth, int fields = 4)
    {
        if (bodyDepth is < 2 or > 32 || fields is < 0 or > 32)
            throw new ArgumentOutOfRangeException();
        Children[103] = new();
        var container = Chain(1);
        for (var index = 0; index < 6; index++)
        {
            nint empty = nextNode++; Children[empty] = new(); Children[container].Add(empty);
        }
        var body = Chain(bodyDepth - 1, container);
        BodyPath = "0/6" + string.Concat(Enumerable.Repeat("/0", bodyDepth - 2));
        for (var index = 0; index < fields; index++)
        {
            nint leaf = nextNode++; Children[leaf] = new(); Children[body].Add(leaf);
            nodeTexts[leaf] = TextObject("synthetic-field-" + index);
        }
        if (CycleBody) { Children[body].Clear(); Children[body].Add(body); }
    }
    // Synthetic first-row topology. These labels/values are not captured game content.
    internal const string GoalkeeperCategoryPath = "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0/0/0";
    internal const string GoalkeeperRowPath = GoalkeeperCategoryPath + "/2/0/0/0/0";
    internal const string GoalkeeperTitlePath = GoalkeeperCategoryPath + "/0";
    internal const string GoalkeeperLabelPath = GoalkeeperRowPath + "/0/0/0/0/0/0/0/0/0";
    internal const string GoalkeeperValuePath = GoalkeeperRowPath + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0";
    internal readonly List<(nint Parent, int Index)> ChildEdges = new();
    internal readonly List<nint> TextReads = new();
    internal readonly HashSet<nint> ThrowingTextNodes = new();
    internal nint NodeAt(string path)
    {
        nint current = 103;
        if (path.Length != 0)
            foreach (var part in path.Split('/')) current = Children[current][int.Parse(part)];
        return current;
    }
    private nint EnsurePath(string path)
    {
        nint current = 103;
        foreach (var part in path.Split('/'))
        {
            var index = int.Parse(part);
            while (Children[current].Count <= index)
            { nint sibling = nextNode++; Children[sibling] = new(); Children[current].Add(sibling); }
            current = Children[current][index];
        }
        return current;
    }
    internal void SetNodeText(string path, string? text)
    {
        var node = NodeAt(path);
        if (text is null) nodeTexts.Remove(node); else nodeTexts[node] = TextObject(text);
    }
    internal void BuildGoalkeeperRow0()
    {
        Children[103] = new();
        EnsurePath(GoalkeeperTitlePath); EnsurePath(GoalkeeperLabelPath); EnsurePath(GoalkeeperValuePath);
        // A real-count second row exists but must never be fetched by the target plan.
        EnsurePath(GoalkeeperCategoryPath + "/2/0/0/0/1");
        SetNodeText(GoalkeeperTitlePath, "TEST-GROUP");
        SetNodeText(GoalkeeperLabelPath, "TEST-ATTRIBUTE");
        SetNodeText(GoalkeeperValuePath, "17");
    }
    internal static string GroupedRowPath(int row) => GoalkeeperCategoryPath + "/2/0/0/0/" + row;
    internal static string GroupedLabelPath(int row) => GroupedRowPath(row) + "/0/0/0/0/0/0/0/0/0";
    internal static string GroupedValuePath(int row) => GroupedRowPath(row) + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0";
    internal void BuildGoalkeeperRows(int firstRow, int count = 2)
    {
        if (firstRow is not (0 or 2) || count != 2) throw new ArgumentOutOfRangeException();
        Children[103] = new();
        EnsurePath(GoalkeeperTitlePath);
        SetNodeText(GoalkeeperTitlePath, "守门");
        // Four available rows, not merely the selected pair: exact edge assertions
        // must prove that the collector never reads the other pair.
        var labels = new[] { "出击(倾向)", "传球", "大脚开球", "反应" };
        for (var row = 0; row < 4; row++)
        {
            EnsurePath(GroupedLabelPath(row)); EnsurePath(GroupedValuePath(row));
            SetNodeText(GroupedLabelPath(row), labels[row]);
            SetNodeText(GroupedValuePath(row), (12 + row).ToString(System.Globalization.CultureInfo.InvariantCulture));
        }
    }
    internal bool InheritedContainerMethods;
    internal int ParentLookups;
    // Literal Mac selectors expanded from focus=panel0/0/6. Independent of production selections.
    internal const string AttributeCommonRoot = "0/6/0/0/0/0/0/0/0/1/0/0/0/0/0/0/0/2/0/0/0/0/0";
    internal static string CategoryFocus(string category) => AttributeCommonRoot + (category switch
    { "goalkeeper" => "/0/0", "mental" => "/1/0", "physical" => "/2/0/0", _ => throw new ArgumentException() });
    internal static string CategoryRow(string category,int row) => CategoryFocus(category) + "/2/0/0/0/" + row;
    internal static string CategoryLabel(string category,int row) => CategoryRow(category,row) + "/0/0/0/0/0/0/0/0/0";
    internal static string CategoryValue(string category,int row) => CategoryRow(category,row) + "/0/0/0/0/0/0/1/1/0/0/0/0/0/0";
    internal static string CategoryTitle(string category) => category switch
    { "goalkeeper" => "守门", "mental" => "精神", "physical" => "身体", _ => throw new ArgumentException() };
    internal static string[] CategoryLabels(string category) => category switch
    {
        "goalkeeper" => new[] { "出击(倾向)", "传球", "大脚开球", "反应", "拦截传中", "拳击球(倾向)", "手控球", "手抛球", "停球", "一对一", "意外性", "指挥防守", "制空范围" },
        "mental" => new[] { "才华", "防守站位", "工作投入", "集中", "决断", "领导力", "侵略性", "视野", "团队合作", "无球跑动", "意志力", "勇敢", "预判", "镇定" },
        "physical" => new[] { "爆发力", "弹跳", "灵活", "耐力", "平衡", "强壮", "速度", "体质" },
        _ => throw new ArgumentException()
    };
    internal void BuildAttributeCategory(string category)
    {
        Children[103]=new();
        var focus=CategoryFocus(category);var labels=CategoryLabels(category);
        EnsurePath(focus+"/0");SetNodeText(focus+"/0",CategoryTitle(category));
        for(var row=0;row<labels.Length;row++)
        {
            EnsurePath(CategoryLabel(category,row));EnsurePath(CategoryValue(category,row));
            SetNodeText(CategoryLabel(category,row),labels[row]);
            SetNodeText(CategoryValue(category,row),(row%20+1).ToString(System.Globalization.CultureInfo.InvariantCulture));
        }
        // An extra available but unapproved row exists; not fetched even at category end.
        EnsurePath(CategoryRow(category,labels.Length));
    }
    internal const string TacticsPageRoot = "0/4/0/0/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0";
    internal const string TacticsAlignmentRoot = "0/4/0/0/0/0/0/0/0/0/0/0/0/0/0/0/2/0/0/0/1/0/0/0/0/0/0/0/0/0/0/0/0/0/0";
    internal const string TacticsAlignmentParent = "0/4/0/0/0/0/0/0/0/0/0/0/0/0";
    internal readonly HashSet<(nint Parent,int Index)> NullChildEdges = new();
    internal const string NextMatchPageRoot = "0/6/0/0/0/0/0/0/0/0/0/0/1/0/0/0/0/0/1/0/0/0/2";
    internal const string SchedulePageRoot = "0/4/0/0/0/0/0/1/0/0/0/0/0/0/1/0/5";
    internal static string SiblingFocus(string profile) => profile switch {
        "tactics_sibling12" => "0/4/0/0/0/0/0/0/0/0/0/0/1",
        "tactics_sibling7" => "0/4/0/0/0/0/0/1",
        "tactics_sibling4" => "0/4/0/0/1", _ => throw new ArgumentException() };
    internal void BuildSiblingProbe(string profile, params string[] relativePaths)
    {
        Children[103] = new();
        var focus = SiblingFocus(profile); EnsurePath(focus);
        foreach (var path in relativePaths) EnsurePath(focus + "/" + path);
    }
    internal const string FrontierRoot = "0/4/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/1";
    internal readonly HashSet<nint> ZeroBoundsNodes = new();
    internal readonly Dictionary<nint,float[]> BoundsOverrides = new();
    internal void BuildFrontier(bool census, params string[] suffixes)
    {
        Children[103]=new(); var root=census?"0":FrontierRoot;
        EnsurePath(root); if(census)EnsurePath("0/19");
        foreach(var suffix in suffixes)EnsurePath(root+"/"+suffix);
    }
    internal const string EligibilityRoot = "0/4/0/0/0/0/0/0/0/0/0/0/1/0/2/0/0/0/1/0/0/0/0/0/0";
    internal static readonly string[] EligibilitySuffixes = {"0/0/0","0/0/1","0/0/2","1/0/0/0/0","1/0/0/0/1/0","1/0/0/0/2/0","1/0/0/0/3/0"};
    internal static string RemainingFocus(string profile) => EligibilityRoot + (profile switch {
        "tactics_leaf_eligibility7" or "tactics_ineligible_text7" => "", "tactics_remaining45_1" => "/1/1",
        "tactics_remaining46_1" => "/1/0/1", "tactics_remaining46_2" => "/1/0/2",
        "tactics_remaining56_1" => "/1/0/0/0/4/1", "tactics_remaining56_2" => "/1/0/0/0/4/2", _ => throw new ArgumentException() });
    internal void BuildRemaining(string profile, params string[] children)
    {
        Children[103]=new(); var focus=RemainingFocus(profile); EnsurePath(focus);
        if(profile is "tactics_leaf_eligibility7" or "tactics_ineligible_text7") {
            foreach(var suffix in EligibilitySuffixes){EnsurePath(focus+"/"+suffix);SetNodeText(focus+"/"+suffix,"TEST RAW LEAF");}
            EnsurePath(focus+"/"+EligibilitySuffixes[0]+"/0"); // Available but explicitly outside the fixed leaf plan.
        }
        else {
            var parent=focus[..focus.LastIndexOf('/')];
            EnsurePath(parent+(profile=="tactics_remaining45_1"?"/1":"/2"));
            foreach(var child in children)EnsurePath(focus+"/"+child);
        }
    }
    internal static string PageFocus(string profile) => profile switch
    { "tactics_ineligible_text7" or "tactics_leaf_eligibility7" or "tactics_remaining45_1" or "tactics_remaining46_1" or "tactics_remaining46_2" or "tactics_remaining56_1" or "tactics_remaining56_2" => RemainingFocus(profile),
      "tactics_root_census" => "0", "tactics_frontier35" => FrontierRoot,
      "tactics_sibling12" or "tactics_sibling7" or "tactics_sibling4" => SiblingFocus(profile),
      "tactics_current" => TacticsPageRoot, "tactics_alignment_candidate" => TacticsAlignmentRoot, "next_match_card" => NextMatchPageRoot,
       _ when profile.StartsWith("schedule_row",StringComparison.Ordinal) => SchedulePageRoot,
       _ => throw new ArgumentException() };
    internal static string[] PagePaths(string profile)
    {
        if(profile=="tactics_current") return new[] { TacticsPageRoot+"/0/0/0/0/1/0/0/1/0",TacticsPageRoot+"/0/0/1/0/0/0/0/0/0",
            TacticsPageRoot+"/0/0/2/0/0/1/0/1",TacticsPageRoot+"/2/0/0/0/0/0" };
        if(profile=="tactics_alignment_candidate") return new[] { TacticsAlignmentRoot+"/0/0/0/0/1/0/0/1/0",TacticsAlignmentRoot+"/0/0/1/0/0/0/0/0/0",
            TacticsAlignmentRoot+"/0/0/2/0/0/1/0/1",TacticsAlignmentRoot+"/2/0/0/0/0/0" };
        if(profile=="next_match_card") return new[] {NextMatchPageRoot+"/0/0/0/0/0/0/0",NextMatchPageRoot+"/0/0/0/0/0/1/0/1/0/0",
            NextMatchPageRoot+"/0/0/0/0/0/1/0/1/1/0/0/0/0"};
        if(!profile.StartsWith("schedule_row",StringComparison.Ordinal) || !int.TryParse(profile[12..],out var row) || row is <0 or >9)
            throw new ArgumentException();
        var prefix=SchedulePageRoot+"/0/0/0/0/0/0/0/0/1/1/0/1/0/0/0/2/0/0/"+row;
        return new[] {SchedulePageRoot+"/0/0/0/0/0/0/0/0/1/1/0/0/0/0/0",prefix+"/0/0/0/0",
            prefix+"/1/0/0/0/0/0/0/0/0/0/0/1",prefix+"/2/0/0/0",prefix+"/4/0/0/0/0/0/0/1"};
    }
    internal void BuildPageSelection(string profile)
    {
        Children[103]=new();
        if(profile.StartsWith("schedule_row",StringComparison.Ordinal))
        {
            for(var row=0;row<10;row++)
            {
                var paths=PagePaths("schedule_row"+row);
                var values=new[] {"赛程安排","30-2-28","TEST OPPONENT "+row,"主","TEST FRIENDLY"};
                for(var i=0;i<paths.Length;i++){EnsurePath(paths[i]);SetNodeText(paths[i],values[i]);}
            }
        }
        else
        {
            var paths=PagePaths(profile);
            var values=profile is "tactics_current" or "tactics_alignment_candidate" ? new[] {"均衡4-4-2 - 控球","控球","均衡","队形"} :
                new[] {"下一场比赛（2030-2-28）","TEST OPPONENT","TEST FRIENDLY"};
            for(var i=0;i<paths.Length;i++){EnsurePath(paths[i]);SetNodeText(paths[i],values[i]);}
        }
    }
    private readonly List<nint> allocations = new();
    private readonly Dictionary<nint, nint> names = new();
    private readonly Dictionary<(nint, string, int), nint> methodIds = new();
    private readonly Dictionary<nint, string> methodNames = new();
    private readonly nint assemblyArray, countPayload, panelCountPayload, zeroPayload, boolPayload, rectPayload, chars;
    public readonly List<string> Invocations = new();
    public bool WrongBoxType, GetterThrows, DerivedText, TextOnlyInSecondPanel;
    public int PanelCount = 1, PanelCountUnboxes;
    public readonly List<int> PanelIndices = new();
    public int TextDepth = 1;
    // Optional exact synthetic branch, with actual per-ancestor counts and index validation.
    // Uses only owned fixture objects; the shape does not claim Windows runtime equivalence.
    public int[]? FocusEdges;
    public int HiddenDepth = -1, MissingChildDepth = -1;
    public readonly List<int> ChildIndices = new();
    private static int ElementDepth(nint value) => value == 103 ? 0 : value >= 300 && value < 400 ? (int)value - 300 : -1;
    private readonly Dictionary<nuint, nint> roots = new();
    private nuint nextHandle = IntPtr.Size == 8 ? unchecked((nuint)0x100000001UL) : 1;
    public int RootCreates, RootTargets, RootFrees;
    internal int ObjectClassReads, UnboxReads, MethodLookups, AssignableChecks, StringLengthReads, StringCharReads;
    public int LiveRoots => roots.Count;
    public nuint il2cpp_gchandle_new(nint value, bool pinned)
    {
        if (pinned) throw new Exception("Fixture expected strong non-pinned root.");
        var handle = nextHandle++; roots.Add(handle, value); RootCreates++; return handle;
    }
    public nint il2cpp_gchandle_get_target(nuint handle) { RootTargets++; return roots[handle]; }
    public void il2cpp_gchandle_free(nuint handle)
    {
        if (!roots.Remove(handle)) throw new Exception("Unknown/double-freed fixture root.");
        RootFrees++;
        if (FailFirstFree && RootFrees == 1) throw new InvalidOperationException("Synthetic uncertain cleanup outcome.");
    }

    private nint Allocate(int bytes) { var value = Marshal.AllocHGlobal(bytes); allocations.Add(value); return value; }
    internal BatchTreeFixture()
    {
        assemblyArray = Allocate(IntPtr.Size * 3);
        for (var i = 0; i < 3; i++) Marshal.WriteIntPtr(assemblyArray, i * IntPtr.Size, i + 1);
        foreach (var (id, name) in new[] { (11, "UnityEngine.UIElementsModule.dll"), (12, "UnityEngine.CoreModule.dll"), (13, "mscorlib.dll") })
        {
            var pointer = Marshal.StringToHGlobalAnsi(name); allocations.Add(pointer); names[id] = pointer;
        }
        countPayload = Allocate(4); Marshal.WriteInt32(countPayload, 1);
        panelCountPayload = Allocate(4);
        zeroPayload = Allocate(4); Marshal.WriteInt32(zeroPayload, 0);
        boolPayload = Allocate(1); Marshal.WriteByte(boolPayload, 1);
        rectPayload = Allocate(16); Marshal.Copy(new float[] { 0, 0, 10, 10 }, 0, rectPayload, 4);
        chars = Marshal.StringToHGlobalUni("fixture-native-path"); allocations.Add(chars);
    }
    internal Delegate Bind(string export, Type delegateType)
    {
        var method = GetType().GetMethod(export, BindingFlags.Public | BindingFlags.Instance) ?? throw new Exception("Unexpected export: " + export);
        return Delegate.CreateDelegate(delegateType, this, method);
    }
    public nint il2cpp_domain_get() => 100;
    public nint il2cpp_domain_get_assemblies(nint domain, out nuint count) { count = 3; return assemblyArray; }
    public nint il2cpp_assembly_get_image(nint assembly) => assembly + 10;
    public nint il2cpp_image_get_name(nint image) => names[image];
    public nint il2cpp_class_from_name(nint image, string ns, string name) => name switch
    { "VisualElement" => 27, "UIElementsRuntimeUtility" => 21, "TextElement" => 22, "Int32" => 23, "Boolean" => 24, "String" => 25, "Rect" => 26, _ => 0 };
    private void RequireRoot(nint value)
    { if (!roots.Values.Contains(value)) throw new Exception("Unrooted fixture object used after invocation: " + value); }
    public nint il2cpp_object_get_class(nint value)
    {
        ObjectClassReads++; RequireRoot(value);
        if (Children.ContainsKey(value)) return nodeTexts.ContainsKey(value) ? 22 : 33;
        if (textObjects.ContainsKey(value)) return 25;
        return value switch { 101 => 31, 102 => 32, 103 => 33, 104 => DerivedText ? 34 : 22, 105 => 32, 106 => DerivedText ? 34 : 22,
            201 or 205 or 206 => WrongBoxType ? 25 : 23, 202 => 24, 203 => 26, 204 => 25, _ => 0 };
    }
    public nint il2cpp_class_get_parent(nint value)
    {
        ParentLookups++;
        return InheritedContainerMethods ? value switch { 33 => 40, 40 => 41, 41 => 42, 42 => 27, _ => 0 } : 0;
    }
    public nint il2cpp_object_unbox(nint value)
    { UnboxReads++; RequireRoot(value); if (value == 205) PanelCountUnboxes++; return value switch { 201 => countPayload, 205 => panelCountPayload, 206 => zeroPayload, 202 => boolPayload, 203 => rectPayload, _ => 0 }; }
    public nint il2cpp_string_chars(nint value) { StringCharReads++; RequireRoot(value); return textObjects[value].Chars; }
    public int il2cpp_string_length(nint value) { StringLengthReads++; RequireRoot(value); return textObjects[value].Text.Length; }
    public bool il2cpp_class_is_assignable_from(nint parent, nint child)
    { AssignableChecks++; return parent == 22 && (child == 22 || child == 34); }
    public nint il2cpp_class_get_method_from_name(nint type, string name, int count)
    {
        MethodLookups++;
        if (InheritedContainerMethods && (type == 33 || type == 40 || type == 41 || type == 42)) return 0;
        var key = (type, name, count);
        if (!methodIds.TryGetValue(key, out var id)) { id = 1000 + methodIds.Count; methodIds[key] = id; methodNames[id] = name; }
        return id;
    }
    public nint il2cpp_runtime_invoke(nint method, nint instance, nint args, out nint exception)
    {
        if (instance != 0) RequireRoot(instance);
        var name = methodNames[method]; Invocations.Add(name);
        exception = GetterThrows || (name == "get_text" && ThrowingTextNodes.Contains(instance)) ? 999 : 0;
        if (name == "GetSortedPlayerPanels") { panelOpens++; return 101; }
        if (name == "get_Count") { Marshal.WriteInt32(panelCountPayload, 1); return 205; }
        if (name == "get_visualTree") return 103;
        if (name == "get_visible") { Marshal.WriteByte(boolPayload, HiddenNodes.Contains(instance) ? (byte)0 : (byte)1); return 202; }
        if (name == "get_worldBound") { Marshal.Copy(BoundsOverrides.TryGetValue(instance,out var rectangle)?rectangle:new float[]{0,0,ZeroBoundsNodes.Contains(instance)?0:10,10},0,rectPayload,4); return 203; }
        if (name == "get_childCount") { Marshal.WriteInt32(countPayload, Children[instance].Count); return 201; }
        if (name == "get_text") { TextReads.Add(instance); return ChangePostAnchor && panelOpens >= 4 && instance == anchor1 ? changedAnchor : nodeTexts[instance]; }
        if (name == "get_Item")
        {
            var index = Marshal.ReadInt32(Marshal.ReadIntPtr(args));
            if (instance == 101) { PanelIndices.Add(index); if (index != 0) throw new Exception("Wrong panel."); return 102; }
            ChildIndices.Add(index); ChildEdges.Add((instance, index)); return NullChildEdges.Contains((instance,index)) ? 0 : Children[instance][index];
        }
        throw new Exception("Unexpected getter.");
    }

    public void Dispose() { foreach (var allocation in allocations) Marshal.FreeHGlobal(allocation); }
}


