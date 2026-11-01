using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using FMMatchLens.Plugin.Memory;
using FMMatchLens.Plugin.Services;

namespace FMMatchLens.Plugin;

[BepInPlugin("io.footballassistant.matchreader", "FootballAssistant Match Reader", "0.1.0")]
public sealed class Plugin : BasePlugin
{
    internal static ManualLogSource PluginLog { get; private set; } = null!;
    private GameMatchTickHook? hook;
    private RealtimeMatchTimeline? timeline;
    private Timer? retry;
    private int installing;

    public override void Load()
    {
        PluginLog = Log;
        var configuredPath = Config.Bind("Output", "SnapshotPath", "", "Absolute path for the FA match snapshot.").Value;
        var path = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_MATCH_FILE");
        if (string.IsNullOrWhiteSpace(path)) path = configuredPath;
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path))
        {
            Log.LogWarning("Match reader disabled: configure an absolute snapshot output path.");
            return;
        }
        timeline = new RealtimeMatchTimeline(path);
        hook = new GameMatchTickHook(timeline);
        retry = new Timer(_ => Install(), null, TimeSpan.Zero, TimeSpan.FromSeconds(1));
    }

    private void Install()
    {
        if (Interlocked.Exchange(ref installing, 1) != 0) return;
        try
        {
            if (hook is not null && (hook.IsStarted || hook.Start(false)))
                Interlocked.Exchange(ref retry, null)?.Dispose();
        }
        catch (Exception e) { PluginLog.LogWarning($"Match reader hook: {e.Message}"); }
        finally { Volatile.Write(ref installing, 0); }
    }

    public override bool Unload()
    {
        Interlocked.Exchange(ref retry, null)?.Dispose();
        hook?.Dispose();
        timeline?.Dispose();
        return true;
    }
}
