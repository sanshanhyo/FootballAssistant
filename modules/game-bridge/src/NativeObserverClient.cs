using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace FootballAssistant.GameBridge;

[StructLayout(LayoutKind.Sequential, Pack = 8)]
internal struct NativeObserverRecord
{
    public ulong CallSequence, MonotonicNs, NativeThreadId, KeysCount, PayloadCount;
    public uint Flags, Reserved;
}

[StructLayout(LayoutKind.Sequential, Pack = 8)]
internal struct NativeObserverStats
{
    public uint AbiVersion, StructSize, InstallState, CaptureEnabled;
    public ulong InvocationCount, EnqueuedCount, DrainedCount, OverflowDropped, ContentionDropped,
        CaptureStoppedInvocations, InFlightInvocations, QueueCapacity, QueueApproxSize;
}

[StructLayout(LayoutKind.Sequential, Pack = 8)]
internal struct NativeObserverInstallReport
{
    public uint AbiVersion, StructSize;
    public int Result;
    public uint InstallState, Checks;
    public int PrepareResult, CommitResult;
    public uint Reserved;
    public ulong TargetAddress, OriginalAddress;
}

internal sealed record NativeObserverHeader(ulong call_sequence, ulong native_thread_id, ulong? keys_count, ulong? payload_count, uint flags, double? age_seconds);

// This client never receives a game callback. The native shim owns forwarding,
// exceptions and process-lifetime hook references; CoreCLR only drains records.
internal sealed class NativeObserverClient
{
    internal const string ShimHash = "9848cdf11e5470d9d5d63a97aeb0323686fe96714f32d3cb7af498d0bcc0e73c";
    private const string Anchor = "game_plugin__fm__gameplugin__i_plugin_data_receiver_send_data_response_set_func_ptr";
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate uint AbiVersion();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate ulong MonotonicNow();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Install(nint anchor, [MarshalAs(UnmanagedType.LPUTF8Str)] string dobbyPath, ref NativeObserverInstallReport report, uint size);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Control();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int GetStats(ref NativeObserverStats stats, uint size);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int Drain(nint records, uint capacity, uint recordSize, out uint count);
    [DllImport("/usr/lib/libSystem.B.dylib", EntryPoint = "dlopen")]
    private static extern nint AlreadyLoaded([MarshalAs(UnmanagedType.LPUTF8Str)] string path, int flags);

    private readonly nint library;
    private nint gamePluginHandle;
    private readonly Install install;
    private readonly Control start, stop;
    private readonly GetStats getStats;
    private readonly Drain drain;
    private readonly MonotonicNow now;
    private readonly string privateRoot;
    private readonly Action<string> trace;
    private bool attempted;
    private int installed;
    private int stopRequested;
    private sealed record InstallSnapshot(NativeObserverInstallReport Report);
    private InstallSnapshot? lastInstall;
    public NativeObserverInstallReport? LastInstall => Volatile.Read(ref lastInstall)?.Report;
    public bool CanAttempt => !attempted && Volatile.Read(ref installed) == 0 && Volatile.Read(ref stopRequested) == 0;
    public bool IsInstalled => Volatile.Read(ref installed) != 0;

    public NativeObserverClient(string privateRoot, Action<string> trace)
    {
        this.privateRoot = privateRoot;
        this.trace = trace;
        ValidateManagedLayouts();
        var path = Path.Combine(privateRoot, "native-observer", "libfootballassistant_native_observer.dylib");
        var bytes = File.ReadAllBytes(path);
        if (Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant() != ShimHash) throw new InvalidDataException("Native observer does not match the reviewed release.");
        library = NativeLibrary.Load(path);
        if (Bind<AbiVersion>("fa_observer_abi_version")() != 1) throw new NotSupportedException("Native observer ABI differs from version 1.");
        install = Bind<Install>("fa_observer_install");
        start = Bind<Control>("fa_observer_start_capture");
        stop = Bind<Control>("fa_observer_stop_capture");
        getStats = Bind<GetStats>("fa_observer_get_stats");
        drain = Bind<Drain>("fa_observer_drain");
        now = Bind<MonotonicNow>("fa_observer_monotonic_ns");
    }

    private T Bind<T>(string name) where T : Delegate => Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library, name));

    public static void ValidateManagedLayouts()
    {
        if (Marshal.SizeOf<NativeObserverRecord>() != 48 || Marshal.SizeOf<NativeObserverStats>() != 88 || Marshal.SizeOf<NativeObserverInstallReport>() != 48 ||
            Marshal.OffsetOf<NativeObserverRecord>(nameof(NativeObserverRecord.Flags)).ToInt32() != 40 ||
            Marshal.OffsetOf<NativeObserverInstallReport>(nameof(NativeObserverInstallReport.TargetAddress)).ToInt32() != 32)
            throw new NotSupportedException("Managed/native observer layout mismatch.");
    }

    internal static NativeObserverHeader DescribeHeader(NativeObserverRecord record, ulong current) => new(record.CallSequence, record.NativeThreadId,
        (record.Flags & 1) != 0 ? record.KeysCount : null,
        (record.Flags & 2) != 0 ? record.PayloadCount : null,
        record.Flags, current >= record.MonotonicNs ? (current - record.MonotonicNs) / 1_000_000_000d : null);

    // One explicit control-plane operation, only at a protected fresh main menu.
    // File hashing/install work is not part of the 15ms UI or 5ms registry budgets.
    public void InstallAtMainMenuCheckpoint()
    {
        if (!CanAttempt) return;
        if (!MainThreadGuard.IsCurrent()) throw new InvalidOperationException("Native installation checkpoint must be on the OS main thread.");
        attempted = true;
        var original = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_PLUGIN_PATH") ?? throw new InvalidOperationException("Explicit already-loaded game plugin path required.");
        // Darwin RTLD_NOW|RTLD_NOLOAD from the local SDK dlfcn.h. Never load a
        // game module earlier than the game's own loader/constructors.
        gamePluginHandle = AlreadyLoaded(original, 0x2 | 0x10);
        if (gamePluginHandle == 0 || !NativeLibrary.TryGetExport(gamePluginHandle, Anchor, out var anchor))
        { trace("Native observer not installed: game plugin/anchor not already loaded; no retry patch attempted."); return; }
        var report = new NativeObserverInstallReport { AbiVersion = 1, StructSize = 48 };
        var result = install(anchor, Path.Combine(privateRoot, "BepInEx", "core", "libdobby.dylib"), ref report, 48);
        Volatile.Write(ref lastInstall, new InstallSnapshot(report));
        if (result != 0 || report.Result != 0 || report.AbiVersion != 1 || report.StructSize != 48 || report.InstallState != 3 ||
            (report.Checks & 0x1FF) != 0x1FF || report.OriginalAddress == 0 || report.TargetAddress == 0 || report.OriginalAddress == report.TargetAddress)
        { trace($"Native observer installation stopped: result={result}, state={report.InstallState}, checks={report.Checks}; no original call was requested by the host."); return; }
        var capture = Volatile.Read(ref stopRequested) == 0 ? start() : 19;
        Volatile.Write(ref installed, capture == 0 ? 1 : 0);
        if (Volatile.Read(ref stopRequested) != 0) stop();
        trace($"Native observer installed at protected main-menu checkpoint; capture={capture == 0}; payload_data_read=false.");
    }

    public object DrainSnapshot()
    {
        var stats = new NativeObserverStats { AbiVersion = 1, StructSize = 88 };
        if (getStats(ref stats, 88) != 0 || stats.AbiVersion != 1 || stats.StructSize != 88)
            throw new InvalidOperationException("Native stats unavailable or ABI mismatch.");
        var records = new List<NativeObserverHeader>();
        if (Volatile.Read(ref installed) != 0)
        {
            var buffer = Marshal.AllocHGlobal(48 * 256);
            try
            {
                var result = drain(buffer, 256, 48, out var count);
                if (result != 0 || count > 256) throw new InvalidOperationException("Native drain contract failed.");
                var current = now(); // Same native monotonic basis as records.
                for (var index = 0; index < count; index++)
                {
                    var record = Marshal.PtrToStructure<NativeObserverRecord>(buffer + checked(index * 48));
                    records.Add(DescribeHeader(record, current));
                }
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }
        var report = LastInstall;
        return new
        {
            abi_version = stats.AbiVersion, installed = Volatile.Read(ref installed) != 0, install_state = stats.InstallState,
            capture_enabled = stats.CaptureEnabled != 0, invocation_count = stats.InvocationCount,
            enqueued_count = stats.EnqueuedCount, drained_count = stats.DrainedCount,
            overflow_dropped = stats.OverflowDropped, contention_dropped = stats.ContentionDropped,
            stopped_invocations = stats.CaptureStoppedInvocations, in_flight = stats.InFlightInvocations,
            queue_size = stats.QueueApproxSize, queue_capacity = stats.QueueCapacity,
            completeness = "bounded_header_observation_only", payload_data_read = false,
            install_report = report is null ? null : new
            {
                abi_version = report.Value.AbiVersion, struct_size = report.Value.StructSize,
                result = report.Value.Result, install_state = report.Value.InstallState,
                checks = report.Value.Checks, prepare_result = report.Value.PrepareResult,
                commit_result = report.Value.CommitResult,
                target_address = report.Value.TargetAddress.ToString("x"),
                original_address = report.Value.OriginalAddress.ToString("x")
            },
            records
        };
    }

    public void StopCapture()
    {
        Volatile.Write(ref stopRequested, 1);
        if (Volatile.Read(ref installed) != 0) stop();
        // No unload/destroy/free: forwarding hook, trampoline, game module, Dobby
        // and shim remain pinned for the complete native process lifetime.
    }
}
