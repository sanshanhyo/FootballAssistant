using System.Runtime.InteropServices;
using System.Text;

namespace FootballAssistant.GameBridge;

// Separate OFFLINE batch draft. No host/lease factory activates this backend.
// A backend, its method cache, and every object token belong to ONE request only.
internal sealed class BatchNativeBackend : IDisposable
{
    internal static readonly IReadOnlyList<string> RequiredExports = Array.AsReadOnly(new[]
    {
        "il2cpp_domain_get", "il2cpp_domain_get_assemblies", "il2cpp_assembly_get_image", "il2cpp_image_get_name",
        "il2cpp_object_get_class", "il2cpp_class_get_parent", "il2cpp_object_unbox", "il2cpp_string_chars",
        "il2cpp_class_from_name", "il2cpp_class_get_method_from_name", "il2cpp_runtime_invoke",
        "il2cpp_string_length", "il2cpp_class_is_assignable_from", "il2cpp_gchandle_new",
        "il2cpp_gchandle_get_target", "il2cpp_gchandle_free"
    });

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint DomainGet();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint DomainAssemblies(nint domain, out nuint count);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint PointerGet(nint value);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint ClassGet(nint image,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string ns, [MarshalAs(UnmanagedType.LPUTF8Str)] string name);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint MethodGet(nint type,
            [MarshalAs(UnmanagedType.LPUTF8Str)] string name, int count);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint Invoke(nint method, nint instance, nint args, out nint exception);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Length(nint value);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] [return: MarshalAs(UnmanagedType.I1)]
        private delegate bool Assignable(nint parent, nint child);

        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate nuint GcNew(nint value, [MarshalAs(UnmanagedType.I1)] bool pinned);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint GcTarget(nuint handle);
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void GcFree(nuint handle);


    private readonly GcNew gcNew;
    private readonly GcTarget gcTarget;
    private readonly GcFree gcFree;
    private readonly nuint[] roots = new nuint[MaximumLiveRoots];
    private readonly BatchObject?[] tokens = new BatchObject?[MaximumLiveRoots];
    private bool disposed, cleanupFaulted;
    private readonly string verifiedHash;
    private readonly DomainGet domain;
    private readonly DomainAssemblies assemblies;
    private readonly PointerGet assemblyImage, imageName, objectClass, classParent, unbox, stringChars;
    private readonly ClassGet classGet;
    private readonly MethodGet methodGet;
    private readonly Invoke invoke;
    private readonly Length stringLength;
    private readonly Assignable assignable;
    private readonly Dictionary<(nint, string, int), nint> methods = new();
    private nint runtimeUtility, textElement, int32Type, boolType, rectType, stringType;
    internal string VerifiedModuleHash => verifiedHash;
    internal int TotalAllocated { get; private set; }
    internal int TotalFreed { get; private set; }
    internal int LiveRoots { get; private set; }
    internal int PeakLiveRoots { get; private set; }
    internal int CleanupFailures { get; private set; }
    internal const int MaximumLiveRoots = 64, MaximumTotalRoots = 512;

    internal BatchNativeBackend(string verifiedHash, Func<string, Type, Delegate> binder)
    {
            if (verifiedHash is not { Length: 64 } || !verifiedHash.All(Uri.IsHexDigit))
                throw new ArgumentException("Verified module hash required.", nameof(verifiedHash));
            this.verifiedHash = verifiedHash;
            T BindApi<T>(string name) where T : Delegate => (T)binder(name, typeof(T));
            domain = BindApi<DomainGet>("il2cpp_domain_get");
            assemblies = BindApi<DomainAssemblies>("il2cpp_domain_get_assemblies");
            assemblyImage = BindApi<PointerGet>("il2cpp_assembly_get_image");
            imageName = BindApi<PointerGet>("il2cpp_image_get_name");
            objectClass = BindApi<PointerGet>("il2cpp_object_get_class");
            classParent = BindApi<PointerGet>("il2cpp_class_get_parent");
            unbox = BindApi<PointerGet>("il2cpp_object_unbox");
            stringChars = BindApi<PointerGet>("il2cpp_string_chars");
            classGet = BindApi<ClassGet>("il2cpp_class_from_name");
            methodGet = BindApi<MethodGet>("il2cpp_class_get_method_from_name");
            invoke = BindApi<Invoke>("il2cpp_runtime_invoke");
            stringLength = BindApi<Length>("il2cpp_string_length");
            assignable = BindApi<Assignable>("il2cpp_class_is_assignable_from");
            gcNew = BindApi<GcNew>("il2cpp_gchandle_new");
            gcTarget = BindApi<GcTarget>("il2cpp_gchandle_get_target");
            gcFree = BindApi<GcFree>("il2cpp_gchandle_free");
        }

    private void EnsureUsable()
    {
        if (disposed) throw new ObjectDisposedException(nameof(BatchNativeBackend));
        if (cleanupFaulted) throw new InvalidOperationException("Batch root cleanup previously failed.");
    }
    internal nint ObjectValue(BatchObject token)
    {
        EnsureUsable();
        if (!ReferenceEquals(token.Owner, this) || token.Released || !ReferenceEquals(tokens[token.Slot], token) ||
            roots[token.Slot] == 0 || token.RawValue == 0)
            throw new ObjectDisposedException(nameof(BatchObject));
        return token.RawValue;
    }
        private static T Native<T>(UiSmokeBudget budget, Func<T> call) { budget.BeforeNative(); return call(); }
        private static nint Required(nint value, string context) => value != 0 ? value : throw new InvalidOperationException(context + " unavailable.");
        private static string AsciiName(nint pointer, UiSmokeBudget budget)
        {
            Required(pointer, "image name");
            var bytes = new List<byte>(128);
            // One bounded metadata-string read, at most 128 bytes and no intervening runtime calls.
            // Do not turn each byte into a fresh full desktop-window enumeration.
            budget.BeforeNative();
            for (var i = 0; i < 128; i++)
            {
                var value = Marshal.ReadByte(pointer, i);
                if (value == 0) return Encoding.ASCII.GetString(bytes.ToArray());
                if (value > 127) throw new InvalidOperationException("Unexpected non-ASCII assembly name.");
                bytes.Add(value);
            }
            throw new InvalidOperationException("Assembly name exceeds bound.");
        }

        private nint ResolveClass(nint image, string ns, string name, UiSmokeBudget budget) =>
            Required(Native(budget, () => classGet(image, ns, name)), ns + "." + name);

        internal void Prepare(UiSmokeBudget budget)
        {
            EnsureUsable();
            if (prepared) throw new InvalidOperationException("Batch backend already prepared.");
            budget.Stage = "resolve_ui_classes";
            var d = Required(Native(budget, () => domain()), "domain");
            nuint count = 0;
            var array = Native(budget, () => assemblies(d, out count));
            if (array == 0 || count == 0 || count > 1024) throw new InvalidOperationException("Invalid assembly span.");
            nint uiImage = 0, coreImage = 0, corlibImage = 0;
            for (nuint index = 0; index < count; index++)
            {
                var assembly = Native(budget, () => Marshal.ReadIntPtr(array, checked((int)index * IntPtr.Size)));
                var image = Required(Native(budget, () => assemblyImage(Required(assembly, "assembly"))), "image");
                var name = AsciiName(Native(budget, () => imageName(image)), budget);
                if (name == "UnityEngine.UIElementsModule.dll") uiImage = image;
                else if (name == "UnityEngine.CoreModule.dll") coreImage = image;
                else if (name == "mscorlib.dll") corlibImage = image;
                if (uiImage != 0 && coreImage != 0 && corlibImage != 0) break;
            }
            Required(uiImage, "UIElementsModule image"); Required(coreImage, "CoreModule image"); Required(corlibImage, "mscorlib image");
            runtimeUtility = ResolveClass(uiImage, "UnityEngine.UIElements", "UIElementsRuntimeUtility", budget);
            textElement = ResolveClass(uiImage, "UnityEngine.UIElements", "TextElement", budget);
            int32Type = ResolveClass(corlibImage, "System", "Int32", budget);
            boolType = ResolveClass(corlibImage, "System", "Boolean", budget);
            stringType = ResolveClass(corlibImage, "System", "String", budget);
            rectType = ResolveClass(coreImage, "UnityEngine", "Rect", budget);
            budget.Stage = "resolve_ui_methods";
            var visualElement = ResolveClass(uiImage, "UnityEngine.UIElements", "VisualElement", budget);
            Method(runtimeUtility, "GetSortedPlayerPanels", 0, budget);
            Method(textElement, "get_text", 0, budget);
            foreach (var getter in new[] { "get_visible", "get_worldBound", "get_childCount" }) Method(visualElement, getter, 0, budget);
            Method(visualElement, "get_Item", 1, budget);
            prepared = true;
        }
        private bool prepared;

    internal BatchObject? OpenPanel(int panelIndex, UiSmokeBudget budget)
    {
        EnsureUsable();
        if (panelIndex is < 0 or > 31) throw new ArgumentOutOfRangeException(nameof(panelIndex));
        if (!prepared) throw new InvalidOperationException("Prepare is required for this request.");
        budget.Stage = "first_panel_root";
        using var panels = Call(runtimeUtility, 0, "GetSortedPlayerPanels", 0, 0, budget);
        if (panels is null) return null;
        int count;
        using (var boxedCount = Get(panels, "get_Count", budget)) count = Int32(boxedCount, budget);
        if (count < 0 || count > 1024) throw new InvalidOperationException("Invalid panel count.");
        if (count == 0) return null;
        if (panelIndex >= count) throw new UiSmokeStopped("panel_index_unavailable");
        using var panel = Item(panels, panelIndex, budget);
        return panel is null ? null : Get(panel, "get_visualTree", budget);
    }
        private nint Method(nint type, string name, int count, UiSmokeBudget budget)
        {
            if (methods.TryGetValue((type, name, count), out var known)) return known;
            var current = type;
            for (var depth = 0; current != 0 && depth < 16; depth++)
            {
                if (methods.TryGetValue((current, name, count), out var inherited))
                { methods[(type, name, count)] = inherited; return inherited; }
                var method = Native(budget, () => methodGet(current, name, count));
                if (method != 0) { methods[(type, name, count)] = method; return method; }
                current = Native(budget, () => classParent(current));
            }
            throw new NotSupportedException("Bounded required getter resolution failed: " + name);
        }

    private BatchObject? Call(nint type, nint instance, string name, nint args, int count, UiSmokeBudget budget)
    {
        EnsureUsable();
        var method = Method(Required(type, "getter type"), name, count, budget);
        if (TotalAllocated >= MaximumTotalRoots) throw new UiSmokeStopped("gc_total_root_budget");
        var slot = Array.FindIndex(tokens, static token => token is null);
        if (slot < 0) throw new UiSmokeStopped("gc_live_root_budget");
        // Allocate the wrapper BEFORE invoke. A freed slot gets a NEW wrapper, never a
        // recycled identity: stale disposed wrappers cannot alias later objects.
        var token = new BatchObject(this, slot);
        tokens[slot] = token;
        try
        {
            // Same native critical region as the one-shot adapter: reserve all three
            // boundaries BEFORE obtaining an unrooted return. No managed allocation,
            // instrumentation, callback or fresh guard between invoke and gcNew.
            budget.BeforeNative(); budget.BeforeNative(); budget.BeforeNative();
            var value = invoke(method, instance, args, out var exception);
            if (exception != 0) throw new InvalidOperationException("IL2CPP getter returned an exception: " + name);
            if (value == 0) { Release(token); return null; }
            var handle = gcNew(value, false);
            if (handle == 0) throw new InvalidOperationException("Unable to root returned IL2CPP object.");
            roots[slot] = handle; // Retain before any target-validation failure.
            TotalAllocated++; LiveRoots++; PeakLiveRoots = Math.Max(PeakLiveRoots, LiveRoots);
            var target = gcTarget(handle);
            if (target != value) throw new InvalidOperationException("GC handle target roundtrip mismatch.");
            token.RawValue = target;
            return token;
        }
        catch
        {
            Release(token);
            throw;
        }
    }
    private BatchObject? Get(BatchObject value, string name, UiSmokeBudget budget)
    {
        var pointer = ObjectValue(value);
        return Call(Native(budget, () => objectClass(pointer)), pointer, name, 0, 0, budget);
    }
    private unsafe BatchObject? Item(BatchObject value, int index, UiSmokeBudget budget)
    {
        if (index is < 0 or > 511) throw new ArgumentOutOfRangeException(nameof(index));
        var pointer = ObjectValue(value);
        var type = Native(budget, () => objectClass(pointer));
        nint* arguments = stackalloc nint[1];
        arguments[0] = (nint)(&index);
        return Call(type, pointer, "get_Item", (nint)arguments, 1, budget);
    }
    private nint Unbox(BatchObject? value, nint expectedType, UiSmokeBudget budget)
    {
        var pointer = value is null ? 0 : ObjectValue(value);
        if (pointer == 0 || Native(budget, () => objectClass(pointer)) != expectedType)
            throw new InvalidOperationException("Getter boxed type does not match expected runtime class.");
        return Required(Native(budget, () => unbox(pointer)), "boxed payload");
    }
    private int Int32(BatchObject? value, UiSmokeBudget budget)
    {
        var payload = Unbox(value, int32Type, budget);
        return Native(budget, () => Marshal.ReadInt32(payload));
    }
    internal bool Visible(BatchObject element, UiSmokeBudget budget)
    {
        using var boxed = Get(element, "get_visible", budget);
        var payload = Unbox(boxed, boolType, budget);
        return Native(budget, () => Marshal.ReadByte(payload)) != 0;
    }
    internal UiSmokeBounds Bounds(BatchObject element, UiSmokeBudget budget)
    {
        using var boxed = Get(element, "get_worldBound", budget);
        var payload = Unbox(boxed, rectType, budget);
        var values = new float[4];
        budget.BeforeNative(); Marshal.Copy(payload, values, 0, 4);
        return new(values[0], values[1], values[2], values[3]);
    }
    internal bool IsTextElement(BatchObject element, UiSmokeBudget budget)
    {
        var pointer = ObjectValue(element);
        var type = Native(budget, () => objectClass(pointer));
        return Native(budget, () => assignable(textElement, type));
    }
    internal string ReadText(BatchObject element, int maximumCodeUnits, UiSmokeBudget budget) =>
        ReadTextCore(element, maximumCodeUnits, budget, requireComplete: false);
    internal string ReadAnchorText(BatchObject element, UiSmokeBudget budget) =>
        ReadTextCore(element, 128, budget, requireComplete: true);
    private string ReadTextCore(BatchObject element, int maximumCodeUnits, UiSmokeBudget budget, bool requireComplete)
    {
        if (maximumCodeUnits is < 1 or > 128) throw new ArgumentOutOfRangeException(nameof(maximumCodeUnits));
        using var textObject = Get(element, "get_text", budget);
        if (textObject is null) return "";
        var pointer = ObjectValue(textObject);
        if (Native(budget, () => objectClass(pointer)) != stringType)
            throw new InvalidOperationException("Text getter did not return System.String.");
        var length = Native(budget, () => stringLength(pointer));
        if (length < 0 || length > 4_000_000) throw new InvalidOperationException("Invalid string length.");
        if (requireComplete && length > maximumCodeUnits)
            throw new InvalidOperationException("Anchor text exceeds complete-text limit.");
        var chars = Required(Native(budget, () => stringChars(pointer)), "string chars");
        var text = Native(budget, () => Marshal.PtrToStringUni(chars, Math.Min(length, maximumCodeUnits))) ?? "";
        if (requireComplete)
        {
            if (text.Length != length) throw new InvalidOperationException("Incomplete anchor text.");
            for (var index = 0; index < text.Length; index++)
            {
                if (char.IsHighSurrogate(text[index]))
                {
                    if (++index >= text.Length || !char.IsLowSurrogate(text[index]))
                        throw new InvalidOperationException("Invalid anchor UTF-16.");
                }
                else if (char.IsLowSurrogate(text[index])) throw new InvalidOperationException("Invalid anchor UTF-16.");
            }
        }
        else if (text.Length > 0 && char.IsHighSurrogate(text[^1])) text = text[..^1];
        return text;
    }
    internal int ChildCount(BatchObject element, UiSmokeBudget budget)
    {
        using var boxed = Get(element, "get_childCount", budget);
        var count = Int32(boxed, budget);
        if (count < 0) throw new InvalidOperationException("Negative child count rejected.");
        return count;
    }
    internal BatchObject? Child(BatchObject element, int index, UiSmokeBudget budget) => Item(element, index, budget);

    internal void Release(BatchObject token)
    {
        if (!ReferenceEquals(token.Owner, this)) throw new InvalidOperationException("Foreign batch object.");
        if (token.Released) return;
        if (!ReferenceEquals(tokens[token.Slot], token)) throw new InvalidOperationException("Stale batch object token.");
        var handle = roots[token.Slot];
        roots[token.Slot] = 0; tokens[token.Slot] = null; token.Released = true; token.RawValue = 0;
        if (handle == 0) return;
        LiveRoots--;
        // Mandatory cleanup is never blocked by grant loss, elapsed or operation limits.
        // Caller measures wall time through disposal. A failed native free is NOT retried:
        // its outcome is uncertain, backend becomes unusable, and remaining roots are attempted.
        try { gcFree(handle); TotalFreed++; }
        catch { cleanupFaulted = true; CleanupFailures++; throw; }
    }
    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        Exception? first = null;
        for (var slot = 0; slot < tokens.Length; slot++)
        {
            if (tokens[slot] is not { } token) continue;
            try { Release(token); }
            catch (Exception error) { first ??= error; }
        }
        if (first is not null || cleanupFaulted)
            throw new InvalidOperationException("Batch root cleanup failed or an earlier free had an uncertain outcome.", first);
    }
}

// A non-reusable capability owned by exactly one backend/request. No finalizer: cleanup
// must occur synchronously on the guarded callback while the module lease remains alive.
internal sealed class BatchObject : IDisposable
{
    internal readonly BatchNativeBackend Owner;
    internal readonly int Slot;
    internal nint RawValue;
    internal bool Released;
    internal BatchObject(BatchNativeBackend owner, int slot) { Owner = owner; Slot = slot; }
    internal nint Value => Owner.ObjectValue(this);
    public void Dispose() => Owner.Release(this);
}
