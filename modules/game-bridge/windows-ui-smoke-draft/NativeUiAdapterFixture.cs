using System.Reflection;
using System.Runtime.InteropServices;
using FootballAssistant.GameBridge;

// Own allocated fixture buffers + managed delegates; never loads or calls GameAssembly.
sealed class NativeUiAdapterFixture : IDisposable
{
    private readonly List<nint> allocations = new();
    private readonly Dictionary<nint, nint> names = new();
    private readonly Dictionary<(nint, string, int), nint> methodIds = new();
    private readonly Dictionary<nint, string> methodNames = new();
    private readonly nint assemblyArray, countPayload, boolPayload, rectPayload, chars;
    public readonly List<string> Invocations = new();
    public bool WrongBoxType, GetterThrows;
    public int TextDepth = 1;
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
    internal NativeUiAdapterFixture()
    {
        assemblyArray = Allocate(IntPtr.Size * 3);
        for (var i = 0; i < 3; i++) Marshal.WriteIntPtr(assemblyArray, i * IntPtr.Size, i + 1);
        foreach (var (id, name) in new[] { (11, "UnityEngine.UIElementsModule.dll"), (12, "UnityEngine.CoreModule.dll"), (13, "mscorlib.dll") })
        {
            var pointer = Marshal.StringToHGlobalAnsi(name); allocations.Add(pointer); names[id] = pointer;
        }
        countPayload = Allocate(4); Marshal.WriteInt32(countPayload, 1);
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
        if (value >= 300 && value < 400) return value - 300 >= TextDepth ? 22 : 33;
        return value switch { 101 => 31, 102 => 32, 103 => 33, 104 => 22, 201 => WrongBoxType ? 25 : 23, 202 => 24, 203 => 26, 204 => 25, _ => 0 };
    }
    public nint il2cpp_class_get_parent(nint value) => 0;
    public nint il2cpp_object_unbox(nint value)
    { RequireRoot(value); return value switch { 201 => countPayload, 202 => boolPayload, 203 => rectPayload, _ => 0 }; }
    public nint il2cpp_string_chars(nint value) { RequireRoot(value); return chars; }
    public int il2cpp_string_length(nint value) { RequireRoot(value); return "fixture-native-path".Length; }
    public bool il2cpp_class_is_assignable_from(nint parent, nint child) => parent == 22 && child == 22;
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
        return name switch
        {
            "GetSortedPlayerPanels" => 101, "get_Count" => 201, "get_visualTree" => 103,
            "get_visible" => 202, "get_worldBound" => 203, "get_childCount" => 201,
            "get_Item" => instance == 101 ? 102 : TextDepth == 1 ? 104 : instance == 103 ? 301 : instance + 1, "get_text" => 204,
            _ => throw new Exception("Unexpected getter: " + name)
        };
    }
    public void Dispose() { foreach (var allocation in allocations) Marshal.FreeHGlobal(allocation); }
}
