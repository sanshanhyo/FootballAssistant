using System.Collections.Concurrent;
using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

// A matching window owner is necessary, not proof of a safe Unity PlayerLoop phase.
internal readonly record struct WindowsThreadIdentity(nint Window, uint ProcessId, uint OwnerProcessId,
    uint CurrentThreadId, uint OwnerThreadId, uint InstallerThreadId, bool ExplicitWindow)
{
    internal int WindowScanCount { get; init; }
    internal int WindowScanVisited { get; init; }
    internal nint FirstOwnedWindow { get; init; }
    internal uint FirstOwnedThreadId { get; init; }
    internal string? WindowScanStatus { get; init; }
    internal int WindowScanError { get; init; }
    internal bool Matches() => ExplicitWindow && Window != 0 && ProcessId != 0 && OwnerProcessId == ProcessId &&
        CurrentThreadId != 0 && OwnerThreadId == CurrentThreadId &&
        (InstallerThreadId == 0 || InstallerThreadId == CurrentThreadId);
}

internal interface IWindowsProbePlatform
{
    uint ThreadId { get; }
    nuint Start(Action<nuint> callback, uint interval);
    bool Kill(nuint timer);
    WindowsThreadIdentity Identity(uint installerThread);
}

// Deliberately has NO capture/reader callback. Even verified ticks are diagnostics only.
internal sealed class WindowsProbeScheduler : IDisposable
{
    private readonly IWindowsProbePlatform platform;
    private readonly Action<string> trace;
    private readonly uint installerThread;
    private nuint timer;
    private int stopped, entered;
    private long ticks;

    internal WindowsProbeScheduler(Action<string> trace, IWindowsProbePlatform? platform = null, uint interval = 3000)
    {
        this.trace = trace;
        this.platform = platform ?? new Win32ProbePlatform();
        installerThread = this.platform.ThreadId;
        Log($"windows_probe_entry native_tid={installerThread}; mode=probe_only; native_reads=disabled");
        timer = this.platform.Start(Tick, interval);
        if (timer == 0) throw new InvalidOperationException("Windows probe SetTimer failed.");
    }

    private void Log(string message) { try { trace(message); } catch { /* No diagnostics exception escapes native callback. */ } }

    private void Tick(nuint id)
    {
        if (Interlocked.Exchange(ref entered, 1) != 0) return;
        try
        {
            if (id == 0 || id != timer) return;
            if (Volatile.Read(ref stopped) != 0) { CancelOnOwner(); return; }
            var identity = platform.Identity(installerThread); // Re-read OS identity on EVERY callback.
            Log($"windows_probe_tick tick={++ticks}; entry_tid={installerThread}; callback_tid={identity.CurrentThreadId}; hwnd={identity.Window}; pid={identity.ProcessId}; owner_pid={identity.OwnerProcessId}; owner_tid={identity.OwnerThreadId}; explicit_hwnd={identity.ExplicitWindow}; owner_match={identity.Matches()}; window_scan={identity.WindowScanStatus ?? "not_needed"}; scanned_windows={identity.WindowScanVisited}; owned_windows={identity.WindowScanCount}; first_owned_hwnd={identity.FirstOwnedWindow}; first_owned_tid={identity.FirstOwnedThreadId}; window_scan_error={identity.WindowScanError}; native_reads=disabled");
        }
        catch (Exception error) { Log($"windows_probe_callback_error type={error.GetType().Name}; native_reads=disabled"); }
        finally { Volatile.Write(ref entered, 0); }
    }

    private void CancelOnOwner()
    {
        if (timer == 0 || platform.ThreadId != installerThread) return;
        if (platform.Kill(timer)) timer = 0;
        else Log("windows_probe_cancel_failed; callback_remains_noop");
    }

    public void Dispose()
    {
        Interlocked.Exchange(ref stopped, 1);
        // Off-thread stop sets the gate now; actual kill occurs on the next owner callback.
        // If that thread no longer pumps, timer/delegate survive harmlessly to process exit.
        if (Interlocked.Exchange(ref entered, 1) != 0) return;
        try { CancelOnOwner(); }
        catch (Exception error) { Log($"windows_probe_cancel_error type={error.GetType().Name}"); }
        finally { Volatile.Write(ref entered, 0); }
    }
}

internal sealed class Win32ProbePlatform : IWindowsProbePlatform
{
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] private delegate void TimerProc(nint hwnd, uint message, nuint timer, uint time);
    [DllImport("user32.dll", SetLastError = true)] private static extern nuint SetTimer(nint hwnd, nuint id, uint interval, TimerProc callback);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool KillTimer(nint hwnd, nuint id);
    // KillTimer does not remove queued WM_TIMER. Never unload/free these reverse P/Invoke delegates.
    private static readonly ConcurrentBag<TimerProc> ProcessLifetimeCallbacks = new();
    internal Win32ProbePlatform()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows probe only.");
    }
    public uint ThreadId => MainThreadGuard.CurrentWindowsThreadId();
    public nuint Start(Action<nuint> callback, uint interval)
    {
        TimerProc native = (_, _, id, _) => { try { callback(id); } catch { /* Absolute unmanaged boundary. */ } };
        ProcessLifetimeCallbacks.Add(native);
        return SetTimer(0, 0, interval, native);
    }
    public bool Kill(nuint timer) => KillTimer(0, timer);
    public WindowsThreadIdentity Identity(uint installerThread) => MainThreadGuard.ReadWindowsIdentity(installerThread);
}
