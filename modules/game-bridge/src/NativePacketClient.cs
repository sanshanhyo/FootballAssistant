using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace FootballAssistant.GameBridge;

[StructLayout(LayoutKind.Sequential, Pack = 8)]
internal struct NativePacketRequest
{
    public uint Version, StructSize, MinKeys, MaxKeys, MinPayloadBytes, MaxPayloadBytes, MaxTotalBytes, Flags;
    public ulong Reserved0, Reserved1;
}

[StructLayout(LayoutKind.Sequential, Pack = 8)]
internal struct NativePacketManifest
{
    public uint Version, StructSize, State, Flags;
    public ulong CaptureId, CallSequence, MonotonicNs, NativeThreadId, OriginalKeysCount, OriginalPayloadCount,
        CopiedKeysBytes, CopiedPayloadBytes, CheckedPackets, SkippedPackets;
    public uint LastSkipReason, Reserved;
    public ulong BusySkippedTotal;
}

// Only control/drain calls enter CoreCLR. The game callback and its deep copy
// stay entirely native. No borrowed game pointer crosses this C ABI.
internal sealed class NativePacketClient
{
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate uint AbiVersion();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate ulong MonotonicNow();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Arm(ref NativePacketRequest request, uint size, out ulong id);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int GetManifest(uint version, ulong id, ref NativePacketManifest manifest, uint size);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Copy(uint version, ulong id, nint keys, ulong keysCapacity, nint payload, ulong payloadCapacity, ref NativePacketManifest manifest, uint size);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Control(uint version, ulong id);

    private readonly nint library;
    private readonly Arm arm;
    private readonly GetManifest getManifest;
    private readonly Copy copy;
    private readonly Control cancel, release;
    private readonly MonotonicNow now;
    private readonly string privateRoot, observerSha;
    private readonly Action<string> trace;
    private string? consumedRequestId, activeRequestId;
    private ulong activeCaptureId;
    private int? lastControlResult;
    private string? lastSavedPacket;

    public NativePacketClient(string privateRoot, string expectedObserverSha, Action<string> trace)
    {
        this.privateRoot = privateRoot;
        this.trace = trace;
        observerSha = expectedObserverSha;
        ValidateManagedLayouts();
        var path = Path.Combine(privateRoot, "native-observer", "libfootballassistant_native_observer.dylib");
        if (Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant() != observerSha)
            throw new InvalidDataException("Packet observer does not match the reviewed build.");
        library = NativeLibrary.Load(path);
        if (Bind<AbiVersion>("fa_observer_packet_abi_version")() != 1)
            throw new NotSupportedException("Packet ABI differs from version 1.");
        arm = Bind<Arm>("fa_observer_packet_arm");
        getManifest = Bind<GetManifest>("fa_observer_packet_get_manifest");
        copy = Bind<Copy>("fa_observer_packet_copy");
        cancel = Bind<Control>("fa_observer_packet_cancel");
        release = Bind<Control>("fa_observer_packet_release");
        now = Bind<MonotonicNow>("fa_observer_monotonic_ns");
    }

    private T Bind<T>(string name) where T : Delegate => Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library, name));

    internal static NativePacketRequest DefaultRequest() => new()
    {
        Version = 1, StructSize = 48, MinKeys = 1, MaxKeys = 4096,
        MinPayloadBytes = 64, MaxPayloadBytes = 65_536, MaxTotalBytes = 98_304
    };

    public static void ValidateManagedLayouts()
    {
        if (Marshal.SizeOf<NativePacketRequest>() != 48 || Marshal.SizeOf<NativePacketManifest>() != 112 ||
            Marshal.OffsetOf<NativePacketRequest>(nameof(NativePacketRequest.Reserved0)).ToInt32() != 32 ||
            Marshal.OffsetOf<NativePacketManifest>(nameof(NativePacketManifest.CaptureId)).ToInt32() != 16 ||
            Marshal.OffsetOf<NativePacketManifest>(nameof(NativePacketManifest.CopiedPayloadBytes)).ToInt32() != 72 ||
            Marshal.OffsetOf<NativePacketManifest>(nameof(NativePacketManifest.BusySkippedTotal)).ToInt32() != 104)
            throw new NotSupportedException("Managed/native packet layout mismatch.");
    }

    internal static bool IsComplete(NativePacketManifest m) =>
        m.Version == 1 && m.StructSize == 112 && m.State == 4 && (m.Flags & 7) == 7 &&
        m.OriginalKeysCount is >= 1 and <= 4096 && m.OriginalPayloadCount is >= 64 and <= 65_536 &&
        m.CopiedKeysBytes == m.OriginalKeysCount * 8 && m.CopiedPayloadBytes == m.OriginalPayloadCount &&
        m.CopiedKeysBytes + m.CopiedPayloadBytes <= 98_304;

    private static object Describe(NativePacketManifest m) => new
    {
        version = m.Version, struct_size = m.StructSize, state = m.State, flags = m.Flags,
        capture_id = m.CaptureId.ToString(), call_sequence = m.CallSequence.ToString(), monotonic_ns = m.MonotonicNs.ToString(),
        native_thread_id = m.NativeThreadId == 0 ? null : m.NativeThreadId.ToString(),
        original_keys_count = m.OriginalKeysCount.ToString(), original_payload_count = m.OriginalPayloadCount.ToString(),
        copied_keys_bytes = m.CopiedKeysBytes.ToString(), copied_payload_bytes = m.CopiedPayloadBytes.ToString(),
        checked_packets = m.CheckedPackets.ToString(), skipped_packets = m.SkippedPackets.ToString(),
        last_skip_reason = m.LastSkipReason, busy_skipped_total = m.BusySkippedTotal.ToString(),
        original_callback_result_known = false
    };

    // Called by the single background drain task, never by a game callback.
    public void Tick(string sessionId, string managedSha, bool observerInstalled)
    {
        if (observerInstalled) ReadOneControl(sessionId, managedSha);
        var manifest = new NativePacketManifest { Version = 1, StructSize = 112 };
        var result = getManifest(1, activeCaptureId, ref manifest, 112);
        if (result == 0 && activeCaptureId != 0 && manifest.CaptureId == activeCaptureId)
        {
            if (manifest.State == 4)
            {
                SaveReadyPacket(sessionId, managedSha, manifest);
                // Only release after independent complete files + manifest exist.
                var released = release(1, activeCaptureId);
                if (released != 0) throw new InvalidOperationException("Saved packet release refused (" + released + ").");
                activeCaptureId = 0;
                activeRequestId = null;
            }
            else if (manifest.State == 5)
            {
                var released = release(1, activeCaptureId);
                if (released == 0) { activeCaptureId = 0; activeRequestId = null; }
            }
        }
        var path = Path.Combine(privateRoot, "diagnostics", "native-packet-status.json");
        var json = JsonSerializer.Serialize(new
        {
            pid = Environment.ProcessId, session_id = sessionId, captured_at = DateTimeOffset.UtcNow.ToString("O"),
            observer_sha256 = observerSha, managed_build_sha256 = managedSha,
            active_capture_id = activeCaptureId.ToString(), last_control_request_id = consumedRequestId,
            last_control_result = lastControlResult, manifest_result = result,
            native = result == 0 ? Describe(manifest) : null, last_saved_packet = lastSavedPacket,
            complete_business_values = false
        });
        File.WriteAllText(path + ".tmp", json);
        File.Move(path + ".tmp", path, true);
    }

    private void ReadOneControl(string sessionId, string managedSha)
    {
        var path = Path.Combine(privateRoot, "control", "native-packet-request.json");
        if (!File.Exists(path) || new FileInfo(path).Length > 4096) return;
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var signal = document.RootElement;
        var requestId = signal.GetProperty("request_id").GetString();
        if (requestId == consumedRequestId || !Guid.TryParse(requestId, out _)) return;
        var requested = signal.GetProperty("requested_at").GetDateTimeOffset();
        var current = DateTimeOffset.UtcNow;
        if (signal.GetProperty("pid").GetInt32() != Environment.ProcessId ||
            signal.GetProperty("session_id").GetString() != sessionId ||
            signal.GetProperty("managed_build_sha256").GetString() != managedSha ||
            signal.GetProperty("observer_sha256").GetString() != observerSha ||
            signal.GetProperty("game_plugin_sha256").GetString() != Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_PLUGIN_SHA256") ||
            requested > current || current - requested > TimeSpan.FromSeconds(30)) return;
        consumedRequestId = requestId; // Any valid operation is tried once only.
        var operation = signal.GetProperty("operation").GetString();
        if (operation == "arm")
        {
            var request = DefaultRequest();
            lastControlResult = arm(ref request, 48, out var id);
            if (lastControlResult == 0) { activeCaptureId = id; activeRequestId = requestId; }
            trace("Native one-shot packet arm result=" + lastControlResult + "; capture_id=" + id + "; limits=4096keys/65536payloadBytes.");
        }
        else if (operation == "cancel" && activeCaptureId != 0)
        {
            lastControlResult = cancel(1, activeCaptureId);
            trace("Native one-shot packet cancel result=" + lastControlResult + ".");
        }
    }

    private unsafe void SaveReadyPacket(string sessionId, string managedSha, NativePacketManifest before)
    {
        if (!IsComplete(before) || before.CaptureId != activeCaptureId || activeRequestId is null)
            throw new InvalidDataException("Native packet lacks complete bounded-copy evidence.");
        var keys = new byte[checked((int)before.CopiedKeysBytes)];
        var payload = new byte[checked((int)before.CopiedPayloadBytes)];
        var copied = new NativePacketManifest { Version = 1, StructSize = 112 };
        fixed (byte* keyPointer = keys)
        fixed (byte* payloadPointer = payload)
        {
            var result = copy(1, activeCaptureId, (nint)keyPointer, (ulong)keys.Length, (nint)payloadPointer, (ulong)payload.Length, ref copied, 112);
            if (result != 0) throw new InvalidOperationException("Native packet copy refused (" + result + ").");
        }
        if (!IsComplete(copied) || copied.CaptureId != before.CaptureId || copied.CallSequence != before.CallSequence ||
            copied.MonotonicNs != before.MonotonicNs || copied.NativeThreadId != before.NativeThreadId ||
            copied.OriginalKeysCount != before.OriginalKeysCount || copied.OriginalPayloadCount != before.OriginalPayloadCount)
            throw new InvalidDataException("Native packet changed while copying immutable ready bytes.");
        var directory = Path.Combine(privateRoot, "diagnostics", "native-packets", sessionId, activeRequestId);
        Directory.CreateDirectory(directory);
        var drained = DateTimeOffset.UtcNow;
        var nativeNow = now();
        var age = nativeNow >= copied.MonotonicNs ? (nativeNow - copied.MonotonicNs) / 1_000_000_000d : (double?)null;
        var captured = age is >= 0 and <= 86400 ? drained.AddSeconds(-age.Value) : drained;
        var keysSha = Convert.ToHexString(SHA256.HashData(keys)).ToLowerInvariant();
        var payloadSha = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
        // Files only contain our native deep copies, never retained game pointers.
        File.WriteAllBytes(Path.Combine(directory, "keys.bin.tmp"), keys);
        File.WriteAllBytes(Path.Combine(directory, "payload.bin.tmp"), payload);
        File.Move(Path.Combine(directory, "keys.bin.tmp"), Path.Combine(directory, "keys.bin"), true);
        File.Move(Path.Combine(directory, "payload.bin.tmp"), Path.Combine(directory, "payload.bin"), true);
        var manifest = new
        {
            schema_version = 1, packet_id = activeRequestId, pid = Environment.ProcessId, session_id = sessionId,
            synthetic = false, complete_copy = true, managed_build_sha256 = managedSha, observer_sha256 = observerSha,
            game_plugin_sha256 = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_PLUGIN_SHA256"),
            source = new
            {
                adapter_id = "footballassistant.native-packet", session_id = sessionId,
                game_build = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_BUILD"),
                bundle_version = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_BUNDLE_VERSION"),
                metadata_sha256 = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_METADATA_SHA256"),
                game_assembly_sha256 = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_ASSEMBLY_SHA256"),
                captured_at = captured.ToString("O"), synthetic = false
            },
            drained_at = drained.ToString("O"), native_header_age_seconds = age,
            captured_at_basis = age is >= 0 and <= 86400 ? "drain_utc_minus_native_monotonic_age" : "drain_utc_only_callback_time_unknown",
            keys_count = copied.OriginalKeysCount.ToString(), payload_bytes = copied.OriginalPayloadCount.ToString(),
            keys_file = "keys.bin", payload_file = "payload.bin", keys_sha256 = keysSha, payload_sha256 = payloadSha,
            native = Describe(copied), key_to_value_mapping_known = false, business_values_mapped = false
        };
        var path = Path.Combine(directory, "packet.json");
        File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(manifest));
        File.Move(path + ".tmp", path, true);
        lastSavedPacket = path;
        trace("Saved one complete native packet; keys=" + copied.OriginalKeysCount + "; payload_bytes=" + payload.Length + "; payload_sha256=" + payloadSha + "; no game parser invoked.");
    }
}
