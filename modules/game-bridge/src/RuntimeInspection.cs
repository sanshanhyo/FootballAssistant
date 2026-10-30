using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace FootballAssistant.GameBridge;

internal sealed record RuntimeReadProof(string member_kind, string assembly, string @namespace, string type, string name, uint member_token, uint type_token, string verification, string last_verified_at, string context);
internal sealed record RegistryDiagnostic(string registry, string status, string reason, string? instance_type = null, int? id_count = null, int? name_hash_count = null, string[]? dictionary_fields = null, int? dictionary_version = null, string? context_stamp = null);
internal readonly record struct ExistingRegistryContext(nint Dictionary, string Stamp, int? Version, int? Expected);

internal sealed partial class NativeUiReader
{
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate uint UIntGet(nint value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] [return: MarshalAs(UnmanagedType.I1)] private delegate bool BoolGet(nint value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nuint OffsetGet(nint value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint FieldsGet(nint type, ref nint iterator);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint FieldValueObject(nint field, nint instance);

    private sealed class InspectionApi
    {
        public readonly PointerGet ClassImage, ClassName, ClassNamespace, MethodClass, MethodName, StaticData, FieldName, FieldParent, FieldType;
        public readonly UIntGet ClassToken, MethodToken, FieldFlags, TypeKind;
        public readonly BoolGet ClassIsInflated;
        public readonly OffsetGet FieldOffset;
        public readonly FieldsGet ClassFields;
        public readonly FieldValueObject ReadField;

        public InspectionApi(NativeUiReader reader)
        {
            ClassImage = reader.Bind<PointerGet>("il2cpp_class_get_image");
            ClassName = reader.Bind<PointerGet>("il2cpp_class_get_name");
            ClassNamespace = reader.Bind<PointerGet>("il2cpp_class_get_namespace");
            ClassToken = reader.Bind<UIntGet>("il2cpp_class_get_type_token");
            MethodClass = reader.Bind<PointerGet>("il2cpp_method_get_class");
            MethodName = reader.Bind<PointerGet>("il2cpp_method_get_name");
            MethodToken = reader.Bind<UIntGet>("il2cpp_method_get_token");
            ClassIsInflated = reader.Bind<BoolGet>("il2cpp_class_is_inflated");
            StaticData = reader.Bind<PointerGet>("il2cpp_class_get_static_field_data");
            ClassFields = reader.Bind<FieldsGet>("il2cpp_class_get_fields");
            FieldName = reader.Bind<PointerGet>("il2cpp_field_get_name");
            FieldParent = reader.Bind<PointerGet>("il2cpp_field_get_parent");
            FieldType = reader.Bind<PointerGet>("il2cpp_field_get_type");
            FieldFlags = reader.Bind<UIntGet>("il2cpp_field_get_flags");
            FieldOffset = reader.Bind<OffsetGet>("il2cpp_field_get_offset");
            ReadField = reader.Bind<FieldValueObject>("il2cpp_field_get_value_object");
            TypeKind = reader.Bind<UIntGet>("il2cpp_type_get_type");
        }
    }

    private InspectionApi? inspection;
    private readonly Dictionary<string, RuntimeReadProof> readProofs = new();
    private readonly HashSet<nint> methodProofsThisFrame = new();
    private readonly HashSet<(nint, string)> fieldProofsThisFrame = new();
    private readonly Dictionary<string, ExistingRegistryContext> currentRegistryContexts = new();
    private readonly Dictionary<(nint, string), nint> fields = new();
    private readonly Dictionary<nint, (string Assembly, string Namespace, string Name, uint Token)> identities = new();
    public string? InspectionError { get; private set; }

    private InspectionApi Inspection => inspection ??= new InspectionApi(this);

    private (string Assembly, string Namespace, string Name, uint Token) Identity(nint type)
    {
        if (identities.TryGetValue(type, out var identity)) return identity;
        var api = Inspection;
        identity = (Marshal.PtrToStringUTF8(imageName(api.ClassImage(type))) ?? "unknown",
            Marshal.PtrToStringUTF8(api.ClassNamespace(type)) ?? "",
            Marshal.PtrToStringUTF8(api.ClassName(type)) ?? "unknown", api.ClassToken(type));
        identities[type] = identity;
        return identity;
    }

    private void RecordMethodProof(nint methodInfo, string context)
    {
        if (!methodProofsThisFrame.Add(methodInfo)) return;
        try
        {
            var api = Inspection;
            var owner = Identity(api.MethodClass(methodInfo));
            var token = api.MethodToken(methodInfo);
            // Resolve the name only from the method handle that actually succeeded.
            var name = Marshal.PtrToStringUTF8(api.MethodName(methodInfo)) ?? "unknown";
            var key = $"method:{owner.Assembly}:{token}";
            readProofs[key] = new RuntimeReadProof("method", owner.Assembly, owner.Namespace, owner.Name, name, token, owner.Token,
                "Successful bounded read-only runtime invocation; no setter, constructor or business action called.", DateTimeOffset.UtcNow.ToString("O"), context);
        }
        catch (Exception error) { InspectionError = error.GetType().Name; }
    }

    private void RecordFieldProof(nint field, string context)
    {
        if (!fieldProofsThisFrame.Add((field, context))) return;
        var api = Inspection;
        var owner = Identity(api.FieldParent(field));
        var name = Marshal.PtrToStringUTF8(api.FieldName(field)) ?? "unknown";
        var key = $"field:{owner.Assembly}:{owner.Token}:{name}:{context}";
        readProofs[key] = new RuntimeReadProof("field", owner.Assembly, owner.Namespace, owner.Name, name, 0, owner.Token,
            "Read from an existing object or existing closed-generic static storage via IL2CPP field metadata; no initialization, setter or registration invoked.",
            DateTimeOffset.UtcNow.ToString("O"), context);
    }

    public RuntimeReadProof[] ReadProofs() => readProofs.Values.ToArray();

    private nint Field(nint type, string name)
    {
        if (fields.TryGetValue((type, name), out var cached)) return cached;
        var api = Inspection;
        var depth = 0;
        for (var current = type; current != 0 && depth++ < 24; current = classParent(current))
        {
            nint iterator = 0;
            for (var index = 0; index < 256; index++)
            {
                var field = api.ClassFields(current, ref iterator);
                if (field == 0) break;
                if (Marshal.PtrToStringUTF8(api.FieldName(field)) != name) continue;
                fields[(type, name)] = field;
                return field;
            }
        }
        return 0;
    }

    private nint ExistingFieldObject(nint instance, string name, string context)
    {
        var api = Inspection;
        var field = Field(objectClass(instance), name);
        if (field == 0 || (api.FieldFlags(field) & 0x10) != 0) return 0;
        var declaredBy = api.FieldParent(field);
        var belongs = false;
        var depth = 0;
        for (var current = objectClass(instance); current != 0 && depth++ < 24; current = classParent(current))
            if (current == declaredBy) { belongs = true; break; }
        if (!belongs) throw new NotSupportedException("Instance field is not declared in this object's existing inflated parent chain.");
        var value = api.ReadField(field, instance);
        RecordFieldProof(field, context);
        return value;
    }

    private int? ExistingInt(nint instance, string name, string context)
    {
        var boxed = ExistingFieldObject(instance, name, context);
        if (boxed == 0) return null;
        var type = Identity(objectClass(boxed));
        return type.Namespace == "System" && type.Name == "Int32" ? Marshal.ReadInt32(unbox(boxed)) : null;
    }

    private (int? Count, string[] Fields) DictionaryCount(nint dictionary, string context)
    {
        if (dictionary == 0) return (null, Array.Empty<string>());
        var type = objectClass(dictionary);
        var identity = Identity(type);
        if (identity.Namespace != "System.Collections.Generic" || !identity.Name.StartsWith("Dictionary`2", StringComparison.Ordinal))
            return (null, Array.Empty<string>());
        var count = ExistingInt(dictionary, "_count", context);
        var free = ExistingInt(dictionary, "_freeCount", context);
        // Older Unity corlib may use unprefixed names; only exact Int32 instance fields are read.
        count ??= ExistingInt(dictionary, "count", context);
        free ??= ExistingInt(dictionary, "freeCount", context);
        var fieldNames = new List<string>();
        nint iterator = 0;
        for (var index = 0; index < 24; index++)
        {
            var field = Inspection.ClassFields(type, ref iterator);
            if (field == 0) break;
            fieldNames.Add(Marshal.PtrToStringUTF8(Inspection.FieldName(field)) ?? "unknown");
        }
        return (count is >= 0 && free is >= 0 && free <= count ? count - free : null, fieldNames.ToArray());
    }

    public RegistryDiagnostic[] ProbeExistingIdentifierRegistries()
    {
        currentRegistryContexts.Clear();
        if (!MainThreadGuard.IsCurrent()) throw new InvalidOperationException("Registry probes require the verified main thread.");
        if (domainGet() == 0)
            return new[] { new RegistryDiagnostic("all", "needs_context", "IL2CPP domain not ready; no registry lookup or initializer invoked.") };
        if (Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_ASSEMBLY_SHA256") != "266d02a57471b44f381b7b647828c58fd394e8222c3083613324a93a9db09dd7" ||
            Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_METADATA_SHA256") != "ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d")
            return new[] { new RegistryDiagnostic("all", "unsupported", "The pure-static-API evidence is pinned to a different GameAssembly; no registry fields read.") };
        var api = Inspection;
        var output = new List<RegistryDiagnostic>();
        var budget = Stopwatch.StartNew();
        foreach (var name in new[] { "PropertyIdentifierSet", "ContextIdentifierSet", "ReferenceIdentifierSet" })
        {
            if (budget.ElapsedMilliseconds > 5) { output.Add(new RegistryDiagnostic(name, "not_probed", "Main-thread probe budget exhausted; no fallback invocation.")); continue; }
            try
            {
                var concrete = FindClass("SI.Bindable.Reference.Core.dll", "SI.Bindable.Reference.Core", name);
                var parent = classParent(concrete);
                if (parent == 0 || !api.ClassIsInflated(parent) || !Identity(parent).Name.StartsWith("IdentifierSet`3", StringComparison.Ordinal))
                { output.Add(new RegistryDiagnostic(name, "needs_context", "Expected closed-generic parent is unavailable.")); continue; }
                // This exported API was disassembled on this build: one load + return,
                // no class init/cctor. Never replace it with get_Instance/StaticGetValue.
                var data = api.StaticData(parent);
                if (data == 0)
                { output.Add(new RegistryDiagnostic(name, "needs_context", "Existing static storage is null; no initializer invoked.")); continue; }
                var singleton = Field(parent, "s_instance");
                if (singleton == 0 || (api.FieldFlags(singleton) & 0x10) == 0)
                { output.Add(new RegistryDiagnostic(name, "unsupported", "Reviewed static singleton field is unavailable.")); continue; }
                if (api.FieldParent(singleton) != parent)
                { output.Add(new RegistryDiagnostic(name, "needs_context", "Singleton field owner is not this exact closed-generic parent; static offset is not applied to a different storage context.")); continue; }
                var offset = api.FieldOffset(singleton);
                if (offset > 65536)
                { output.Add(new RegistryDiagnostic(name, "unsupported", "Static offset is outside the bounded supported layout.")); continue; }
                var instance = Marshal.ReadIntPtr(data, checked((int)offset));
                RecordFieldProof(singleton, name + ".existing-closed-generic-static");
                if (instance == IntPtr.Zero)
                { output.Add(new RegistryDiagnostic(name, "needs_context", "Existing singleton is null; no get_Instance or constructor invoked.")); continue; }
                var actual = Identity(objectClass(instance));
                if (actual.Namespace != "SI.Bindable.Reference.Core" || actual.Name != name)
                { output.Add(new RegistryDiagnostic(name, "unsupported", "Existing singleton type does not match reviewed context.")); continue; }
                var idDictionary = ExistingFieldObject(instance, "m_idToInfo", name + ".m_idToInfo");
                var hashDictionary = ExistingFieldObject(instance, "m_nameHashToInfo", name + ".m_nameHashToInfo");
                var ids = DictionaryCount(idDictionary, name + ".m_idToInfo.count");
                var hashes = DictionaryCount(hashDictionary, name + ".m_nameHashToInfo.count");
                var version = idDictionary == 0 ? null : ExistingInt(idDictionary, "_version", name + ".m_idToInfo.version") ?? ExistingInt(idDictionary, "version", name + ".m_idToInfo.version");
                var contextStamp = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"{name}:{instance}:{idDictionary}"))).ToLowerInvariant();
                if (idDictionary != 0) currentRegistryContexts[name] = new ExistingRegistryContext(idDictionary, contextStamp, version, ids.Count);
                output.Add(new RegistryDiagnostic(name, "available", "Existing singleton/dictionary fields only; business registration/getters/cctors were not called.", actual.Namespace + "." + actual.Name, ids.Count, hashes.Count, ids.Fields, version, contextStamp));
            }
            catch (Exception error) { output.Add(new RegistryDiagnostic(name, "error", error.GetType().Name + ": " + error.Message)); }
        }
        return output.ToArray();
    }
}
