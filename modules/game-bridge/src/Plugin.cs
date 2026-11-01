using System.Reflection;
using BepInEx;
using BepInEx.Unity.IL2CPP;

namespace FootballAssistant.GameBridge;

[BepInPlugin("io.footballassistant.readonlybridge", "FootballAssistant Read-only Bridge", ObservationFactory.AdapterVersion)]
public sealed class Plugin : BasePlugin
{
    private readonly string sessionId = Guid.NewGuid().ToString();
    private EventInfo? tickEvent;
    private Delegate? tickHandler;
    private SnapshotPublisher? publisher;
    private NativeUiReader? reader;
    private DateTime nextCapture;
    private bool stopped;
    private int tickObserved;
    private int mainThreadObserved;

    public override void Load()
    {
        if (OperatingSystem.IsWindows())
        {
            Log.LogError("Windows candidate is probe-only. Use the direct diagnostic entry; UI sampling remains disabled.");
            return;
        }
        var runtimeFile = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_RUNTIME_FILE");
        var gameAssembly = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_ASSEMBLY");
        if (string.IsNullOrWhiteSpace(runtimeFile) || string.IsNullOrWhiteSpace(gameAssembly) || !File.Exists(gameAssembly))
        {
            Log.LogError("Bridge disabled: explicit runtime file and GameAssembly paths are required.");
            return;
        }

        tickEvent = typeof(IL2CPPChainloader).GetEvent("MainThreadTick", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (tickEvent?.EventHandlerType != typeof(Action))
        {
            Log.LogError("Bridge disabled: verified main-thread tick is unavailable. No background-thread sampling fallback is used.");
            return;
        }

        publisher = new SnapshotPublisher(() => ConnectionSettings.Read(runtimeFile), message => Log.LogWarning(message));
        // Native API access happens only inside the loader's main-thread callback.
        Action tick = () => Capture(gameAssembly);
        tickHandler = tick;
        tickEvent.AddEventHandler(null, tickHandler);
        Log.LogInfo("Read-only bridge armed: current UI text only; no input, scrolling, game changes or hidden attribute reads.");
    }

    private void Capture(string gameAssembly)
    {
        if (Interlocked.Exchange(ref tickObserved, 1) == 0)
            Log.LogInfo("Bridge tick observed; waiting for independently verified OS main thread.");
        // The community event can also be raised on other runtime-invoke threads.
        // Verify the OS UI/main thread independently before any native UI getter.
        if (!MainThreadGuard.IsCurrent()) return;
        if (Interlocked.Exchange(ref mainThreadObserved, 1) == 0)
            Log.LogInfo("Bridge OS main thread verified; native UI reads enabled.");
        if (stopped || DateTime.UtcNow < nextCapture) return;
        nextCapture = DateTime.UtcNow.AddSeconds(3);
        try
        {
            reader ??= new NativeUiReader(gameAssembly);
            var texts = reader.Capture();
            if (texts.Count == 0 && texts is not UiCapture)
            {
                Log.LogInfo("Bridge capture: 0 eligible UI text nodes.");
                return;
            }
            // Capture again even if the screen is unchanged, so an offline/restarted
            // backend receives the next snapshot and freshness is based on observation.
            var measuredBuild = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_BUILD");
            var observation = ObservationFactory.Create(texts, measuredBuild ?? (texts.Count > 0 ? reader.ReadApplicationVersion() : null), sessionId);
            var queued = publisher?.Offer(observation) == true;
            Log.LogInfo($"Bridge capture: {texts.Count} UI text nodes; queued={queued}.");
        }
        catch (Exception error)
        {
            stopped = true;
            Log.LogError($"Bridge sampling disabled ({error.GetType().Name}: {error.Message}); game execution continues.");
        }
    }

    public override bool Unload()
    {
        stopped = true;
        if (tickEvent is not null && tickHandler is not null) tickEvent.RemoveEventHandler(null, tickHandler);
        publisher?.Dispose();
        reader?.Dispose();
        return true;
    }
}
