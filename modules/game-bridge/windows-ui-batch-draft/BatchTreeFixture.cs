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
    internal bool ChangePostAnchor, CycleBody;
    internal string BodyPath { get; private set; } = "";
    internal const string Anchor1Path = "0/0/0/0/0/0/0/0/0/0/0/0/0/0";
    internal const string Anchor2Path = "1/0/0/0/0/0/0/0/0/0/0/0/0/0";
    private nint anchor1, changedAnchor;
    private nint TextObject(string text)
    {
        var id = nextText++; var pointer = Marshal.StringToHGlobalUni(text); allocations.Add(pointer);
        textObjects[id] = (text, pointer); return id;
    }
    private nint Chain(int depth)
    {
        nint parent = 103;
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
    public int LiveRoots => roots.Count;
    public nuint il2cpp_gchandle_new(nint value, bool pinned)
    {
        if (pinned) throw new Exception("Fixture expected strong non-pinned root.");
        var handle = nextHandle++; roots.Add(handle, value); RootCreates++; return handle;
    }
    public nint il2cpp_gchandle_get_target(nuint handle) { RootTargets++; return roots[handle]; }
    public void il2cpp_gchandle_free(nuint handle)
    { if (!roots.Remove(handle)) throw new Exception("Unknown/double-freed fixture root."); RootFrees++; }

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
        RequireRoot(value);
        if (Children.ContainsKey(value)) return nodeTexts.ContainsKey(value) ? 22 : 33;
        if (textObjects.ContainsKey(value)) return 25;
        return value switch { 101 => 31, 102 => 32, 103 => 33, 104 => DerivedText ? 34 : 22, 105 => 32, 106 => DerivedText ? 34 : 22,
            201 or 205 or 206 => WrongBoxType ? 25 : 23, 202 => 24, 203 => 26, 204 => 25, _ => 0 };
    }
    public nint il2cpp_class_get_parent(nint value) => 0;
    public nint il2cpp_object_unbox(nint value)
    { RequireRoot(value); if (value == 205) PanelCountUnboxes++; return value switch { 201 => countPayload, 205 => panelCountPayload, 206 => zeroPayload, 202 => boolPayload, 203 => rectPayload, _ => 0 }; }
    public nint il2cpp_string_chars(nint value) { RequireRoot(value); return textObjects[value].Chars; }
    public int il2cpp_string_length(nint value) { RequireRoot(value); return textObjects[value].Text.Length; }
    public bool il2cpp_class_is_assignable_from(nint parent, nint child) => parent == 22 && (child == 22 || child == 34);
    public nint il2cpp_class_get_method_from_name(nint type, string name, int count)
    {
        var key = (type, name, count);
        if (!methodIds.TryGetValue(key, out var id)) { id = 1000 + methodIds.Count; methodIds[key] = id; methodNames[id] = name; }
        return id;
    }
    public nint il2cpp_runtime_invoke(nint method, nint instance, nint args, out nint exception)
    {
        if (instance != 0) RequireRoot(instance);
        var name = methodNames[method]; Invocations.Add(name);
        exception = GetterThrows ? 999 : 0;
        if (name == "GetSortedPlayerPanels") { panelOpens++; return 101; }
        if (name == "get_Count") { Marshal.WriteInt32(panelCountPayload, 1); return 205; }
        if (name == "get_visualTree") return 103;
        if (name == "get_visible") return 202;
        if (name == "get_worldBound") return 203;
        if (name == "get_childCount") { Marshal.WriteInt32(countPayload, Children[instance].Count); return 201; }
        if (name == "get_text") return ChangePostAnchor && panelOpens >= 4 && instance == anchor1 ? changedAnchor : nodeTexts[instance];
        if (name == "get_Item")
        {
            var index = Marshal.ReadInt32(Marshal.ReadIntPtr(args));
            if (instance == 101) { PanelIndices.Add(index); if (index != 0) throw new Exception("Wrong panel."); return 102; }
            ChildIndices.Add(index); return Children[instance][index];
        }
        throw new Exception("Unexpected getter.");
    }

    public void Dispose() { foreach (var allocation in allocations) Marshal.FreeHGlobal(allocation); }
}


