using System.Diagnostics;
using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

internal static class MainThreadGuard
{
    private static int verifiedManagedThread;

    [DllImport("/usr/lib/libSystem.B.dylib", EntryPoint = "pthread_main_np")]
    private static extern int IsMacMainThread();
    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(nint window, out uint processId);

    public static bool IsCurrent()
    {
        var current = Environment.CurrentManagedThreadId;
        var verified = Volatile.Read(ref verifiedManagedThread);
        if (verified != 0) return current == verified;
        bool isMain;
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            isMain = IsMacMainThread() != 0;
        else if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            using var process = Process.GetCurrentProcess();
            var window = process.MainWindowHandle;
            isMain = window != IntPtr.Zero && GetWindowThreadProcessId(window, out var owner) == GetCurrentThreadId() && owner == (uint)process.Id;
        }
        else return false;
        if (isMain) Interlocked.CompareExchange(ref verifiedManagedThread, current, 0);
        return isMain;
    }
}
