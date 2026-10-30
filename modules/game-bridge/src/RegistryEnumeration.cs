using System.Diagnostics;
using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

internal sealed record RuntimeRegistryEntry(uint id, string? name, string? owner = null, string? display_name = null, string? value_type = null);
internal sealed record RegistryEnumerationSnapshot(string registry_id, string enumeration_id, int? dictionary_version, int? expected_count, bool complete, int scanned_slots, string status, string reason, RuntimeRegistryEntry[] entries);

internal sealed partial class NativeUiReader
{
    // This exact Unity 6.3 build returns a pointer-sized tagged slot handle.
    // See ignored native-channel-abi/gchandle-width/evidence.json; old uint APIs
    // truncate it and must never be used to free a handle from this runtime.
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nuint GcRootNew(nint value, [MarshalAs(UnmanagedType.I1)] bool pinned);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void GcRootFree(nuint handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint GcRootTarget(nuint handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nuint ArrayLength(nint array);

    private sealed class RegistryScan
    {
        public readonly string Id = Guid.NewGuid().ToString();
        public readonly string Stamp;
        public readonly int Version, Expected;
        public int Cursor;
        public bool Complete;
        public string? Error;
        public nint ArrayIdentity;
        public readonly Dictionary<uint, RuntimeRegistryEntry> Entries = new();
        public RegistryScan(ExistingRegistryContext context) { Stamp = context.Stamp; Version = context.Version!.Value; Expected = context.Expected!.Value; }
    }

    private readonly Dictionary<string, RegistryScan> registryScans = new();
    private nint arrayGetValue;
    private FieldsGet? classMethods;
    private ArrayLength? arrayLength;
    private GcRootNew? gcRootNew;
    private GcRootFree? gcRootFree;
    private GcRootTarget? gcRootTarget;
    private bool gcHandleGatePassed;
    private bool gcHandleGateFailed;
    public string GcHandleDiagnostic { get; private set; } = "not_probed";
    private int nextRegistry;

    private nint ArrayGetValueMethod()
    {
        if (arrayGetValue != 0) return arrayGetValue;
        classMethods ??= Bind<FieldsGet>("il2cpp_class_get_methods");
        var type = FindClass("mscorlib.dll", "System", "Array");
        if (Identity(type).Token != 33554754) throw new NotSupportedException("Array type token differs from the verified build.");
        nint iterator = 0;
        for (var index = 0; index < 512; index++)
        {
            var method = classMethods(type, ref iterator);
            if (method == 0) break;
            // Fixed metadata + binary proves this exact token is instance Object
            // GetValue(Int32), not Int64 or params Int32[]. No overload guessing.
            if (Inspection.MethodToken(method) != 100666585) continue;
            if (Marshal.PtrToStringUTF8(Inspection.MethodName(method)) != "GetValue") break;
            return arrayGetValue = method;
        }
        throw new NotSupportedException("Verified Array.GetValue(Int32) is unavailable.");
    }

    private unsafe nint ExistingArrayItem(nint array, int index)
    {
        nint* arguments = stackalloc nint[1];
        arguments[0] = (nint)(&index);
        var method = ArrayGetValueMethod();
        var result = invoke(method, array, (nint)arguments, out var exception);
        if (exception != 0) throw new InvalidOperationException("Read-only Array.GetValue failed.");
        RecordMethodProof(method, "existing-registry-entry-array");
        return result;
    }

    private uint? ExistingUInt(nint instance, string field, string context)
    {
        var boxed = ExistingFieldObject(instance, field, context);
        if (boxed == 0) return null;
        var identity = Identity(objectClass(boxed));
        return identity.Namespace == "System" && identity.Name == "UInt32" ? unchecked((uint)Marshal.ReadInt32(unbox(boxed))) : null;
    }

    private bool VerifyGcHandleAbi(nint existingObject)
    {
        if (gcHandleGatePassed) return true;
        if (gcHandleGateFailed) return false;
        gcRootNew ??= Bind<GcRootNew>("il2cpp_gchandle_new");
        gcRootFree ??= Bind<GcRootFree>("il2cpp_gchandle_free");
        gcRootTarget ??= Bind<GcRootTarget>("il2cpp_gchandle_get_target");
        var handle = gcRootNew(existingObject, false);
        if (handle == 0 || gcRootTarget(handle) != existingObject)
        {
            gcHandleGateFailed = true;
            GcHandleDiagnostic = "failed: pointer-sized new/get_target did not match the existing object; handle quarantined, not freed or reused; no enumeration";
            return false;
        }
        // A handle is freed exactly once, only after its target has been validated.
        gcRootFree(handle);
        if (IntPtr.Size != 8 || handle <= uint.MaxValue)
        {
            gcHandleGateFailed = true;
            GcHandleDiagnostic = "round-trip/free succeeded but did not exercise nonzero high32 handle bits; enumeration withheld";
            return false;
        }
        gcHandleGatePassed = true;
        GcHandleDiagnostic = "passed: nonzero high32 pointer-sized new -> exact existing target -> one free; no old uint handle reused";
        return true;
    }

    public RegistryEnumerationSnapshot[] AdvanceRegistryEnumerations(Stopwatch sharedProbeBudget)
    {
        if (!MainThreadGuard.IsCurrent()) throw new InvalidOperationException("Registry enumeration requires the verified main thread.");
        if (!gcHandleGatePassed)
        {
            if (!gcHandleGateFailed && currentRegistryContexts.Count > 0)
                VerifyGcHandleAbi(currentRegistryContexts.Values.First().Dictionary);
            // Publish the gate result for a full tick before any entry scanning.
            return RegistryEnumerationSnapshots();
        }
        var names = new[] { "PropertyIdentifierSet", "ContextIdentifierSet", "ReferenceIdentifierSet" };
        var start = nextRegistry++ % names.Length;
        var copiedSlots = 0;
        for (var order = 0; order < names.Length; order++)
        {
            var name = names[(start + order) % names.Length];
            if (!currentRegistryContexts.TryGetValue(name, out var context) || context.Version is null || context.Expected is null or < 0 or > 100_000)
                continue;
            if (!registryScans.TryGetValue(name, out var scan) || scan.Stamp != context.Stamp || scan.Version != context.Version || scan.Expected != context.Expected)
                registryScans[name] = scan = new RegistryScan(context);
            if (scan.Complete || scan.Error is not null || sharedProbeBudget.Elapsed.TotalMilliseconds >= 5) continue;
            nuint dictionaryRoot = 0, arrayRoot = 0;
            try
            {
                gcRootNew ??= Bind<GcRootNew>("il2cpp_gchandle_new");
                gcRootFree ??= Bind<GcRootFree>("il2cpp_gchandle_free");
                dictionaryRoot = gcRootNew(context.Dictionary, false);
                var before = ExistingInt(context.Dictionary, "_version", name + ".version-before-copy");
                if (before != scan.Version) { registryScans.Remove(name); continue; }
                var rawCount = ExistingInt(context.Dictionary, "_count", name + ".physical-count");
                var array = ExistingFieldObject(context.Dictionary, "_entries", name + ".entries-array");
                if (rawCount is null or < 0 or > 100_000) throw new NotSupportedException("Dictionary physical count is unavailable or exceeds the read budget.");
                // These registration tables are add-only on the observed build.
                // Do not guess another corlib's free-list encoding or confuse a
                // uint32 key's high bit with an unoccupied slot.
                var freeCount = ExistingInt(context.Dictionary, "_freeCount", name + ".free-count");
                if (freeCount != 0 || rawCount != scan.Expected) throw new NotSupportedException("Free-slot layout is not supported by this bounded add-only registry enumerator.");
                if (array == 0)
                {
                    if (rawCount == 0 && scan.Expected == 0) { scan.Complete = true; continue; }
                    throw new InvalidOperationException("Nonempty dictionary has no existing entries array.");
                }
                if (scan.ArrayIdentity != 0 && scan.ArrayIdentity != array)
                { registryScans[name] = new RegistryScan(context); continue; }
                scan.ArrayIdentity = array; // Compared only next frame; never dereferenced after the current callback.
                arrayRoot = gcRootNew(array, false);
                arrayLength ??= Bind<ArrayLength>("il2cpp_array_length");
                if ((nuint)rawCount.Value > arrayLength(array)) throw new InvalidOperationException("Dictionary count exceeds its existing array length.");
                while (scan.Cursor < rawCount && copiedSlots < 200 && sharedProbeBudget.Elapsed.TotalMilliseconds < 5)
                {
                    var entry = ExistingArrayItem(array, scan.Cursor++);
                    copiedSlots++;
                    if (entry == 0) continue;
                    // Array.GetValue returns a boxed copy of an existing Entry. This
                    // temporary GC root does not instantiate any game business object.
                    var root = gcRootNew(entry, false);
                    try
                    {
                        var entryType = Identity(objectClass(entry));
                        if (entryType.Name != "Entry" || entryType.Token != 33555703) throw new NotSupportedException("Unexpected registry dictionary entry type/token.");
                        var hash = ExistingInt(entry, "hashCode", name + ".entry.hashCode");
                        if (hash is null) throw new NotSupportedException("Entry hashCode is not the verified Int32 layout.");
                        var key = ExistingUInt(entry, "key", name + ".entry.key");
                        var info = ExistingFieldObject(entry, "value", name + ".entry.info");
                        if (key is null || info == 0) continue;
                        var infoIdentity = Identity(objectClass(info));
                        if (infoIdentity.Namespace != "SI.Bindable.Reference.Core" || infoIdentity.Name != name.Replace("IdentifierSet", "IDInfo", StringComparison.Ordinal))
                            throw new NotSupportedException("Registry value is not an existing identifier info object.");
                        var id = ExistingUInt(info, "<ID>k__BackingField", name + ".info.id");
                        if (id != key) throw new InvalidOperationException("Registry key and existing info ID disagree.");
                        var textObject = ExistingFieldObject(info, "<Name>k__BackingField", name + ".info.name");
                        if (textObject != 0)
                        {
                            var textType = Identity(objectClass(textObject));
                            if (textType.Namespace != "System" || textType.Name != "String") throw new NotSupportedException("Identifier Name is not the verified System.String field.");
                        }
                        var text = textObject == 0 ? null : Text(textObject);
                        var item = new RuntimeRegistryEntry(key.Value, text);
                        if (scan.Entries.TryGetValue(key.Value, out var previous) && previous != item)
                            throw new InvalidOperationException("One registry ID produced conflicting info in the same version.");
                        scan.Entries[key.Value] = item; // ID zero is valid.
                    }
                    finally { gcRootFree(root); }
                }
                var after = ExistingInt(context.Dictionary, "_version", name + ".version-after-copy");
                if (after is null) throw new InvalidOperationException("Dictionary version became unavailable during copy.");
                if (after != scan.Version)
                { registryScans.Remove(name); continue; }
                if (scan.Cursor >= rawCount)
                {
                    if (scan.Entries.Count != scan.Expected) throw new InvalidOperationException("Physical traversal ended without the expected unique real IDs.");
                    scan.Complete = true;
                }
            }
            catch (Exception error) { scan.Error = error.GetType().Name + ": " + error.Message; }
            finally
            {
                if (arrayRoot != 0) gcRootFree!(arrayRoot);
                if (dictionaryRoot != 0) gcRootFree!(dictionaryRoot);
            }
        }
        return RegistryEnumerationSnapshots();
    }

    public RegistryEnumerationSnapshot[] RegistryEnumerationSnapshots() => registryScans.Where(pair =>
        currentRegistryContexts.TryGetValue(pair.Key, out var current) && pair.Value.Stamp == current.Stamp && pair.Value.Version == current.Version && pair.Value.Expected == current.Expected).Select(pair =>
        new RegistryEnumerationSnapshot(pair.Key, pair.Value.Id, pair.Value.Version, pair.Value.Expected, pair.Value.Complete,
            pair.Value.Cursor, pair.Value.Error is null ? (pair.Value.Complete ? "complete" : "enumerating") : "error",
            pair.Value.Error ?? "Unique existing uint32 IDs copied under a stable dictionary version; no business constructor, registration or setter invoked.", pair.Value.Entries.Values.ToArray())).ToArray();
}
