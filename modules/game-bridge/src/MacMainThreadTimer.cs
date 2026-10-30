using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

// CoreFoundation schedules the callback on the existing process main runloop.
// It does not create a Unity object, patch game state or run native getters on a worker.
internal sealed class MacMainThreadTimer : IDisposable
{
    private const string CoreFoundation = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate void TimerCallback(nint timer, nint context);
    [StructLayout(LayoutKind.Sequential)]
    private struct TimerContext { public nint Version, Info, Retain, Release, CopyDescription; }
    [DllImport(CoreFoundation)] private static extern nint CFRunLoopGetMain();
    [DllImport(CoreFoundation)] private static extern double CFAbsoluteTimeGetCurrent();
    [DllImport(CoreFoundation)] private static extern nint CFRunLoopTimerCreate(nint allocator, double fireDate, double interval, ulong flags, nint order, TimerCallback callback, ref TimerContext context);
    [DllImport(CoreFoundation)] private static extern void CFRunLoopAddTimer(nint runloop, nint timer, nint mode);
    [DllImport(CoreFoundation)] private static extern void CFRunLoopTimerInvalidate(nint timer);
    [DllImport(CoreFoundation)] private static extern void CFRelease(nint value);
    [DllImport(CoreFoundation)] private static extern int CFRunLoopRunInMode(nint mode, double seconds, [MarshalAs(UnmanagedType.I1)] bool returnAfterSourceHandled);

    private readonly nint framework;
    private readonly TimerCallback callback;
    private nint timer;
    private int inCallback;

    public MacMainThreadTimer(Action action, double intervalSeconds = 3)
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.OSX)) throw new PlatformNotSupportedException("macOS main-runloop scheduler only.");
        framework = NativeLibrary.Load(CoreFoundation);
        callback = (_, _) =>
        {
            if (Interlocked.Exchange(ref inCallback, 1) != 0) return;
            try { action(); }
            catch (Exception error)
            {
                try { Console.Error.WriteLine($"[FootballAssistant] Main-runloop callback stopped safely ({error.GetType().Name})."); }
                catch { /* A diagnostics failure must not cross an unmanaged callback boundary. */ }
            }
            finally { Volatile.Write(ref inCallback, 0); }
        };
        var context = new TimerContext();
        timer = CFRunLoopTimerCreate(0, CFAbsoluteTimeGetCurrent() + intervalSeconds, intervalSeconds, 0, 0, callback, ref context);
        if (timer == 0) throw new InvalidOperationException("Could not create main-runloop timer.");
        var commonModes = Marshal.ReadIntPtr(NativeLibrary.GetExport(framework, "kCFRunLoopCommonModes"));
        CFRunLoopAddTimer(CFRunLoopGetMain(), timer, commonModes);
    }

    internal static void RunLoopForTest(double seconds)
    {
        var library = NativeLibrary.Load(CoreFoundation);
        try
        {
            var mode = Marshal.ReadIntPtr(NativeLibrary.GetExport(library, "kCFRunLoopDefaultMode"));
            CFRunLoopRunInMode(mode, seconds, false);
        }
        finally { NativeLibrary.Free(library); }
    }

    public void Dispose()
    {
        var value = Interlocked.Exchange(ref timer, IntPtr.Zero);
        if (value == IntPtr.Zero) return;
        CFRunLoopTimerInvalidate(value);
        CFRelease(value);
        NativeLibrary.Free(framework);
        GC.KeepAlive(callback);
    }
}
