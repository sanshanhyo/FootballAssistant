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

    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate bool EnumWindowProc(nint window, nint parameter);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowProc callback, nint parameter);

    internal static uint CurrentWindowsThreadId() => GetCurrentThreadId();

    internal static WindowsThreadIdentity ReadWindowsIdentity(uint installerThread = 0)
    {
        using var process = Process.GetCurrentProcess();
        // Without an explicitly selected window this is diagnostic-only, never proof.
        var explicitWindow = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_WINDOWS_GAME_HWND");
        var selected = ulong.TryParse(explicitWindow, out var parsed) && parsed != 0 && parsed <= long.MaxValue;
        process.Refresh();
        var window = selected ? (nint)(long)parsed : process.MainWindowHandle;
        uint owner = 0;
        var thread = window == 0 ? 0 : GetWindowThreadProcessId(window, out owner);
        var identity = new WindowsThreadIdentity(window, (uint)process.Id, owner, GetCurrentThreadId(), thread, installerThread, selected);
        if (window != 0) return identity;
        // No titles/text or other-process window details retained; diagnostics never authorize a window.
        var owned = 0;
        var visited = 0;
        nint first = 0;
        uint firstThread = 0;
        var bounded = false;
        var callbackFailed = false;
        EnumWindowProc callback = (candidate, _) =>
        {
            try
            {
                if (++visited > 512) { bounded = true; return false; }
                var candidateThread = GetWindowThreadProcessId(candidate, out var candidateOwner);
                if (candidateOwner == (uint)process.Id && candidateThread != 0)
                {
                    if (owned++ == 0) { first = candidate; firstThread = candidateThread; }
                    if (owned >= 32) { bounded = true; return false; }
                }
                return true;
            }
            catch { callbackFailed = true; return false; }
        };
        var completed = EnumWindows(callback, 0);
        var error = completed || bounded || callbackFailed ? 0 : Marshal.GetLastWin32Error();
        GC.KeepAlive(callback);
        return identity with { WindowScanCount = owned, WindowScanVisited = Math.Min(visited, 512), FirstOwnedWindow = first, FirstOwnedThreadId = firstThread,
            WindowScanStatus = callbackFailed ? "callback_failed" : completed ? "complete" : bounded ? "bounded" : "failed", WindowScanError = error };
    }

    public static bool IsCurrent()
    {
        // Windows identities are never cached: windows can be destroyed/recreated.
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return ReadWindowsIdentity().Matches();
        var current = Environment.CurrentManagedThreadId;
        var verified = Volatile.Read(ref verifiedManagedThread);
        if (verified != 0) return current == verified;
        bool isMain;
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            isMain = IsMacMainThread() != 0;
        else return false;
        if (isMain) Interlocked.CompareExchange(ref verifiedManagedThread, current, 0);
        return isMain;
    }
}
