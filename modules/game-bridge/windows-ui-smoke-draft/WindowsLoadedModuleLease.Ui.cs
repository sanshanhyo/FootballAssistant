using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Text;

namespace FootballAssistant.GameBridge;

internal sealed partial class WindowsLoadedModuleLease
{
    private NativeUiBackend? uiBackend;
    private string? uiSession;
    // This partial is NOT compiled by the ordinary probe or metadata-only candidate.
    internal UiResolveResult? RunUiResolveOnce(WindowsSmokePolicy policy, SmokeRequest request, CancellationToken cancellationToken = default)
    {
        lock (lifetime)
        {
            if (request.Stage != SmokeStage.UiResolve || !policy.MatchesModuleHash(VerifiedHash)) return null;
            cancellationToken.ThrowIfCancellationRequested();
            var grant = policy.TryConsume(request, MainThreadGuard.ReadWindowsIdentity(MainThreadGuard.CurrentWindowsThreadId()), DateTimeOffset.UtcNow);
            if (grant is null) return null;
            var success = false;
            var watch = Stopwatch.StartNew();
            var budget = new UiSmokeBudget(() => watch.Elapsed.TotalMilliseconds, () =>
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!policy.CheckStartedResolve(grant, MainThreadGuard.ReadWindowsScanIdentity(MainThreadGuard.CurrentWindowsThreadId()), DateTimeOffset.UtcNow))
                    throw new UiSmokeStopped("grant_or_window_changed");
            }, 250, 2048);
            UiResolveResult Finish(bool succeeded, string reason)
            {
                var diagnostics = budget.Snapshot();
                return new(succeeded, reason, diagnostics.ElapsedMs, budget.Stage, budget.Operations, diagnostics);
            }
            try
            {
                if (!policy.TryBeginCall(grant, MainThreadGuard.ReadWindowsIdentity(MainThreadGuard.CurrentWindowsThreadId()), DateTimeOffset.UtcNow))
                    return Finish(false, "grant_revalidation_failed");
                uiBackend = new NativeUiBackend(this);
                uiBackend.PrepareTypesAndMethods(budget); // No panels/getters/object traversal.
                success = true; uiSession = policy.Session;
                return Finish(true, "resolved");
            }
            catch (UiSmokeStopped error) { return Finish(false, error.Message); }
            catch (Exception error) { return Finish(false, "backend_failure:" + error.GetType().Name); }
            finally
            {
                policy.CompleteResolve(grant, success);
                if (!success) { uiBackend?.Dispose(); uiBackend = null; uiSession = null; }
            }
        }
    }

    internal UiSmokeResult? RunUiOnce(WindowsSmokePolicy policy, SmokeRequest request, CancellationToken cancellationToken = default)
    {
        lock (lifetime)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (uiBackend is null || uiSession != policy.Session) return null;
            try
            {
                return WindowsSmokeReader.TryReadAuthorized(policy, request, uiBackend,
                    () => MainThreadGuard.ReadWindowsScanIdentity(MainThreadGuard.CurrentWindowsThreadId()),
                    () => DateTimeOffset.UtcNow, cancellationToken);
            }
            finally
            {
                if (policy.UiAttempted) { uiBackend.Dispose(); uiBackend = null; uiSession = null; }
            }
        }
    }

    partial void ReleaseUiResources() { uiBackend?.Dispose(); uiBackend = null; uiSession = null; }

    private sealed class NativeUiBackend : IWindowsUiSmokeBackend
    {
        private static readonly string[] RequiredExports =
        {
            "il2cpp_domain_get", "il2cpp_domain_get_assemblies", "il2cpp_assembly_get_image", "il2cpp_image_get_name",
            "il2cpp_object_get_class", "il2cpp_class_get_parent", "il2cpp_object_unbox", "il2cpp_string_chars",
            "il2cpp_class_from_name", "il2cpp_class_get_method_from_name", "il2cpp_runtime_invoke",
            "il2cpp_string_length", "il2cpp_class_is_assignable_from",
            "il2cpp_gchandle_new", "il2cpp_gchandle_get_target", "il2cpp_gchandle_free"
        };
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
        private readonly nuint[] roots = new nuint[64]; // Allocate before any runtime object is returned.
        private int rootCount;
        private bool disposed;
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
        public string VerifiedModuleHash => verifiedHash;

        private static Func<string, Type, Delegate> ValidatedBinder(WindowsLoadedModuleLease lease)
        {
            lease.EnsureExports(RequiredExports); // One validation pass, no IL2CPP calls.
            return (name, type) => Marshal.GetDelegateForFunctionPointer(lease.exports[name], type);
        }
        internal NativeUiBackend(WindowsLoadedModuleLease lease) : this(lease.VerifiedHash, ValidatedBinder(lease)) { }

        // Private nested type: alternate constructor is reachable only by the separately compiled test partial.
        internal NativeUiBackend(string verifiedHash, Func<string, Type, Delegate> binder)
        {
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

        // Every export, pointer read and payload copy has a fresh gate/budget boundary.
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

        internal void PrepareTypesAndMethods(UiSmokeBudget budget)
        {
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
        public nint ResolveFirstPanelRoot(UiSmokeBudget budget)
        {
            if (!prepared) throw new InvalidOperationException("Explicit resolve-only warm-up required before capture.");
            budget.Stage = "first_panel_root";
            var panels = Call(runtimeUtility, 0, "GetSortedPlayerPanels", 0, 0, budget);
            if (panels == 0) return 0;
            var panelCount = Int32(Get(panels, "get_Count", budget), budget);
            if (panelCount < 0 || panelCount > 1024) throw new InvalidOperationException("Invalid panel count.");
            if (panelCount == 0) return 0;
            var panel = Item(panels, 0, budget);
            return panel == 0 ? 0 : Get(panel, "get_visualTree", budget);
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
        private nint Call(nint type, nint instance, string name, nint args, int count, UiSmokeBudget budget)
        {
            var method = Method(Required(type, "getter type"), name, count, budget);
            if (disposed) throw new ObjectDisposedException(nameof(NativeUiBackend));
            if (rootCount >= roots.Length) throw new UiSmokeStopped("gc_root_budget");
            // Reserve invoke/new/target BEFORE obtaining an unrooted return. No CoreCLR closure,
            // window enumeration, allocation or budget exception between return and gcNew.
            budget.BeforeNative(); budget.BeforeNative(); budget.BeforeNative();
            var value = invoke(method, instance, args, out var exception);
            if (exception != 0) throw new InvalidOperationException("IL2CPP getter returned an exception: " + name);
            if (value == 0) return 0;
            var handle = gcNew(value, false); // C++ bool is explicitly one-byte; modern handle is pointer-sized.
            if (handle == 0) throw new InvalidOperationException("Unable to root returned IL2CPP object.");
            roots[rootCount++] = handle; // Preallocated storage: retain even if target validation fails.
            var target = gcTarget(handle);
            if (target != value) throw new InvalidOperationException("GC handle target roundtrip mismatch; UI read stopped.");
            return target;
        }
        private nint Get(nint value, string name, UiSmokeBudget budget) =>
            Call(Native(budget, () => objectClass(Required(value, "object"))), value, name, 0, 0, budget);
        private unsafe nint Item(nint value, int index, UiSmokeBudget budget)
        {
            var type = Native(budget, () => objectClass(Required(value, "indexed object")));
            nint* arguments = stackalloc nint[1];
            arguments[0] = (nint)(&index);
            return Call(type, value, "get_Item", (nint)arguments, 1, budget);
        }
        private nint Unbox(nint value, nint expectedType, UiSmokeBudget budget)
        {
            if (value == 0 || Native(budget, () => objectClass(value)) != expectedType)
                throw new InvalidOperationException("Getter boxed type does not match expected runtime class.");
            return Required(Native(budget, () => unbox(value)), "boxed payload");
        }
        private int Int32(nint value, UiSmokeBudget budget)
        {
            var payload = Unbox(value, int32Type, budget);
            return Native(budget, () => Marshal.ReadInt32(payload));
        }
        public bool Visible(nint element, UiSmokeBudget budget)
        {
            var payload = Unbox(Get(element, "get_visible", budget), boolType, budget);
            return Native(budget, () => Marshal.ReadByte(payload)) != 0;
        }
        public UiSmokeBounds Bounds(nint element, UiSmokeBudget budget)
        {
            var payload = Unbox(Get(element, "get_worldBound", budget), rectType, budget);
            // Unity Rect is sequential four floats; same typed ABI as existing NativeUiReader.
            var floats = new float[4];
            budget.BeforeNative(); Marshal.Copy(payload, floats, 0, 4);
            return new(floats[0], floats[1], floats[2], floats[3]);
        }
        public bool IsTextElement(nint element, UiSmokeBudget budget)
        {
            var type = Native(budget, () => objectClass(element));
            return Native(budget, () => assignable(textElement, type));
        }
        public string ReadText(nint element, int maximumCodeUnits, UiSmokeBudget budget)
        {
            if (maximumCodeUnits is < 1 or > 128) throw new ArgumentOutOfRangeException(nameof(maximumCodeUnits));
            var value = Get(element, "get_text", budget);
            if (value == 0) return "";
            if (Native(budget, () => objectClass(value)) != stringType) throw new InvalidOperationException("Text getter did not return System.String.");
            var length = Native(budget, () => stringLength(value));
            if (length < 0 || length > 4_000_000) throw new InvalidOperationException("Invalid string length.");
            var chars = Required(Native(budget, () => stringChars(value)), "string chars");
            var text = Native(budget, () => Marshal.PtrToStringUni(chars, Math.Min(length, maximumCodeUnits))) ?? "";
            if (text.Length > 0 && char.IsHighSurrogate(text[^1])) text = text[..^1];
            return text;
        }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            Exception? first = null;
            // Required cleanup is NOT blocked by elapsed/call budget, cancellation or window loss.
            // The outer RunUiOnce lifetime lock keeps all exports/module alive until this completes.
            while (rootCount > 0)
            {
                var handle = roots[--rootCount]; roots[rootCount] = 0;
                try { gcFree(handle); }
                catch (Exception error) { first ??= error; } // Still attempt every other root exactly once.
            }
            if (first is not null) throw new InvalidOperationException("IL2CPP temporary-root cleanup failed.", first);
        }

        public int ChildCount(nint element, UiSmokeBudget budget) => Int32(Get(element, "get_childCount", budget), budget);
        public nint Child(nint element, int index, UiSmokeBudget budget) => Item(element, index, budget);
    }
}
