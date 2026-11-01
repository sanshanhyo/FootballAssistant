using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using FootballAssistant.GameBridge;

// Test-only instrumented copy of MainThreadGuard's complete scan at 3fb7a5c9.
// Never compiled into a bridge/candidate. Keep query order, error capture and bounds
// identical; native parity checks precede every batch. Timings include instrumentation.
internal sealed class GuardComponents
{
    internal readonly long[] Ticks = new long[9];
    internal readonly long[] Calls = new long[9];
    internal void Add(int component, long start)
    { Ticks[component] += Stopwatch.GetTimestamp() - start; Calls[component]++; }
    internal void Clear() { Array.Clear(Ticks); Array.Clear(Calls); }
}
internal static class WindowsGuardComponentScan
{
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(nint window, out uint processId);

    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate bool EnumWindowProc(nint window, nint parameter);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowProc callback, nint parameter);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int GetClassNameW(nint window, StringBuilder name, int maximum);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(nint window);
    [StructLayout(LayoutKind.Sequential)]
    private struct ClientRect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetClientRect(nint window, out ClientRect rect);

    internal static WindowsThreadIdentity Read(uint installerThread, GuardComponents metrics)
    {
        var identity = new WindowsThreadIdentity(0, (uint)Environment.ProcessId, 0,
            MainThreadGuard.CurrentWindowsThreadId(), 0, installerThread, false);
        // Same complete bounded enumeration for diagnostic and candidate-only callers.
        var setupStart = Stopwatch.GetTimestamp();
        var candidates = new List<WindowsWindowDiagnostic>(32);
        metrics.Add(7, setupStart);
        // No titles/text or other-process window details retained; diagnostics never authorize a window.
        var owned = 0;
        var visited = 0;
        nint first = 0;
        uint firstThread = 0;
        var bounded = false;
        var callbackFailed = false;
        EnumWindowProc callback = (candidate, _) =>
        {
            var callbackStart = Stopwatch.GetTimestamp();
            try
            {
                if (++visited > 512) { bounded = true; return false; }
                var ownerStart = Stopwatch.GetTimestamp();
                var candidateThread = GetWindowThreadProcessId(candidate, out var candidateOwner);
                metrics.Add(2, ownerStart);
                if (candidateOwner == identity.ProcessId && candidateThread != 0)
                {
                    if (owned++ == 0) { first = candidate; firstThread = candidateThread; }
                    var bufferStart = Stopwatch.GetTimestamp();
                    var name = new StringBuilder(128);
                    metrics.Add(7, bufferStart);
                    var classStart = Stopwatch.GetTimestamp();
                    var nameLength = GetClassNameW(candidate, name, name.Capacity);
                    var nameError = nameLength == 0 ? Marshal.GetLastWin32Error() : 0;
                    metrics.Add(3, classStart);
                    var visibleStart = Stopwatch.GetTimestamp();
                    var visible = IsWindowVisible(candidate);
                    metrics.Add(4, visibleStart);
                    var rectStart = Stopwatch.GetTimestamp();
                    var hasRect = GetClientRect(candidate, out var rect);
                    var rectError = hasRect ? 0 : Marshal.GetLastWin32Error();
                    metrics.Add(5, rectStart);
                    // Recheck owner after inspecting shape; a destroyed/reused HWND is not stable evidence.
                    var afterStart = Stopwatch.GetTimestamp();
                    var afterThread = GetWindowThreadProcessId(candidate, out var afterOwner);
                    metrics.Add(6, afterStart);
                    var rowStart = Stopwatch.GetTimestamp();
                    candidates.Add(new(candidate.ToInt64(), candidateOwner, candidateThread,
                        afterOwner == candidateOwner && afterThread == candidateThread,
                        nameLength == 0 ? null : name.ToString(), nameLength > 0 && nameLength < 127,
                        nameError, visible, hasRect,
                        hasRect ? (long)rect.Right - rect.Left : null,
                        hasRect ? (long)rect.Bottom - rect.Top : null, rectError));
                    metrics.Add(7, rowStart);
                    if (owned >= 32) { bounded = true; return false; }
                }
                return true;
            }
            catch { callbackFailed = true; return false; }
            finally { metrics.Add(1, callbackStart); }
        };
        var enumStart = Stopwatch.GetTimestamp();
        var completed = EnumWindows(callback, 0);
        var error = completed || bounded || callbackFailed ? 0 : Marshal.GetLastWin32Error();
        metrics.Add(0, enumStart); // Capture Win32 error above BEFORE timing calls.
        GC.KeepAlive(callback);
        var materializeStart = Stopwatch.GetTimestamp();
        var result = identity with { WindowCandidates = candidates.ToArray(), WindowScanCount = owned, WindowScanVisited = Math.Min(visited, 512), FirstOwnedWindow = first, FirstOwnedThreadId = firstThread,
            WindowScanStatus = callbackFailed ? "callback_failed" : completed ? "complete" : bounded ? "bounded" : "failed", WindowScanError = error };
        metrics.Add(8, materializeStart);
        return result;
    }
}
