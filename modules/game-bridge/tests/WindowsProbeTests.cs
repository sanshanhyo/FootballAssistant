using System.Diagnostics;
using System.Runtime.InteropServices;
using FootballAssistant.GameBridge;

static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
var good = new WindowsThreadIdentity(123, 1, 1, 2, 2, 2, true);
Check(good.Matches(), "matching explicit owner");
foreach (var bad in new[] { good with { Window = 0 }, good with { ProcessId = 0 }, good with { OwnerProcessId = 9 },
    good with { CurrentThreadId = 9 }, good with { OwnerThreadId = 0 }, good with { InstallerThreadId = 9 }, good with { ExplicitWindow = false } })
    Check(!bad.Matches(), "reject incomplete/foreign/candidate identity");
var fake = new FakePlatform();
var logs = new List<string>();
using (var timer = new WindowsProbeScheduler(logs.Add, fake))
{
    fake.Fire(999); Check(fake.Reads == 0, "unknown timer ID ignored");
    fake.Fire(); fake.Window = 0; fake.Fire();
    Check(fake.Reads == 2 && logs.Last().Contains("owner_match=False"), "identity re-read after window invalidation");
    fake.Window = 123;
    fake.OnIdentity = () => fake.Fire();
    fake.Fire(); Check(fake.Reads == 3, "reentrant callback rejected");
    fake.OnIdentity = () => throw new Exception("identity failure");
    fake.Fire(); Check(logs.Last().Contains("callback_error"), "native callback catches exceptions");
    fake.OnIdentity = null;
    fake.ThreadId = 3; timer.Dispose(); Check(fake.Kills == 0, "worker cannot kill owner timer");
    var reads = fake.Reads;
    fake.ThreadId = 2; fake.Fire(); Check(fake.Kills == 1 && fake.Reads == reads, "owner callback cancels without reading");
    fake.Fire(); Check(fake.Reads == reads, "queued late callback remains no-op");
}
var noisy = new FakePlatform();
using (var timer = new WindowsProbeScheduler(_ => throw new Exception("log failure"), noisy)) noisy.Fire();
Check(noisy.Kills == 1, "same-thread dispose cancels even when diagnostics throw");
var failed = new FakePlatform { StartResult = 0 };
try { using var timer = new WindowsProbeScheduler(_ => { }, failed); throw new Exception("accepted zero timer"); }
catch (InvalidOperationException) { }
Console.WriteLine("PASS pure logic: fail-closed identity, fresh reads, reentry, exceptions, owner cancellation, late callbacks; no game/native reads.");
if (OperatingSystem.IsWindows()) WindowsHarness.Run(Check);
else Console.WriteLine("SKIP Win32 harness: non-Windows OS.");

sealed class FakePlatform : IWindowsProbePlatform
{
    public uint ThreadId { get; set; } = 2;
    public nint Window = 123;
    public int Reads, Kills;
    public nuint StartResult = 7;
    public Action? OnIdentity;
    private Action<nuint>? callback;
    public nuint Start(Action<nuint> callback, uint interval) { this.callback = callback; return StartResult; }
    public bool Kill(nuint timer) { Kills++; return true; }
    public WindowsThreadIdentity Identity(uint installer)
    {
        Reads++; OnIdentity?.Invoke(); return new(Window, 1, 1, ThreadId, 2, installer, true);
    }
    public void Fire(nuint id = 7) => callback!(id);
}

static class WindowsHarness
{
    [StructLayout(LayoutKind.Sequential)] private struct Message
    { public nint Window; public uint Id; public nuint WParam; public nint LParam; public uint Time; public int X, Y; public uint Private; }
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern nint CreateWindowExW(uint exStyle, string className, string title, uint style,
        int x, int y, int width, int height, nint parent, nint menu, nint instance, nint parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DestroyWindow(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool PeekMessageW(out Message message, nint window, uint min, uint max, uint remove);
    [DllImport("user32.dll")] private static extern nint DispatchMessageW(ref Message message);
    private static void Pump(int milliseconds)
    {
        var time = Stopwatch.StartNew();
        while (time.ElapsedMilliseconds < milliseconds)
        {
            while (PeekMessageW(out var message, 0, 0, 0, 1)) DispatchMessageW(ref message);
            Thread.Sleep(1);
        }
    }
    private static bool PumpUntil(Func<bool> condition)
    {
        var deadline = Stopwatch.StartNew();
        while (!condition() && deadline.Elapsed < TimeSpan.FromSeconds(3)) Pump(10);
        return condition();
    }
    internal static void Run(Action<bool, string> check)
    {
        var old = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_WINDOWS_GAME_HWND");
        var window = CreateWindowExW(0, "STATIC", "FootballAssistant isolated timer test (not game)", 0,
            0, 0, 10, 10, 0, 0, 0, 0);
        check(window != 0, "create owned test window");
        try
        {
            Environment.SetEnvironmentVariable("FOOTBALL_ASSISTANT_WINDOWS_GAME_HWND", window.ToInt64().ToString());
            check(MainThreadGuard.IsCurrent(), "owned window gate");
            check(!Task.Run(MainThreadGuard.IsCurrent).GetAwaiter().GetResult(), "worker rejected");
            var lines = new List<string>();
            using (var scheduler = new WindowsProbeScheduler(lines.Add, interval: 10))
            {
                check(PumpUntil(() => lines.Any(x => x.Contains("owner_match=True"))), "real timer fires on explicit window owner");
                DestroyWindow(window); window = 0;
                check(!MainThreadGuard.IsCurrent(), "cached thread cannot authorize destroyed window");
                check(PumpUntil(() => lines.Last().Contains("owner_match=False")), "timer rechecks destroyed window");
                Task.Run(scheduler.Dispose).GetAwaiter().GetResult();
                Pump(40);
            }
            var count = lines.Count; Pump(40);
            check(lines.Count == count, "disposed timer produces no further diagnostic ticks");
            Console.WriteLine("PASS Win32 owned-window timer harness; no FM, injection, loader or IL2CPP calls.");
        }
        finally
        {
            if (window != 0) DestroyWindow(window);
            Environment.SetEnvironmentVariable("FOOTBALL_ASSISTANT_WINDOWS_GAME_HWND", old);
        }
    }
}
