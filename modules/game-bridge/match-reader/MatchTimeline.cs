using System.Text.Json;
using FMMatchLens.Plugin.Domain;
using FMMatchLens.Plugin.Memory;

namespace FMMatchLens.Plugin.Services;

// Minimal sink for the upstream capture hook. No upstream server or archive is used.
internal sealed class RealtimeMatchTimeline : IDisposable
{
    private readonly object gate = new();
    private readonly string path;
    private readonly Timer writer;
    private nint address;
    private string? matchId;
    private string status = "waiting";
    private int lastTick = -1, count;
    private long missing, duplicate, outOfOrder;
    private long metadataTime;
    private object? latest;
    private RealtimeTeamMetadata? home, away;
    private RealtimePlayerMetadata[]? players;
    private string? date;
    private RealtimeCompetitionMetadata? competition;
    private int writing;

    public RealtimeMatchTimeline(string path)
    {
        this.path = path;
        // Replace any previous run's live snapshot before installing the hook.
        Write();
        writer = new Timer(_ => Write(), null, TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(1));
    }
    public bool NeedsPlayerMetadata { get { lock (gate) return players is null || Environment.TickCount64 - metadataTime >= 1000; } }
    public void Begin(nint source)
    {
        if (source == default) return;
        lock (gate)
        {
            if (source == address && status != "ended") return;
            address = source; matchId = Guid.NewGuid().ToString("N"); status = "live";
            lastTick = -1; count = 0; missing = duplicate = outOfOrder = 0;
            latest = null; home = away = null; players = null; date = null; competition = null;
        }
    }
    public bool Append(RawRealtimeTickFrame raw)
    {
        lock (gate)
        {
            if (raw.MatchAddress != address || matchId is null || status != "live") return false;
            if (raw.Tick == lastTick) { duplicate++; return false; }
            if (raw.Tick < lastTick) { outOfOrder++; return false; }
            if (lastTick >= 0 && raw.Tick > lastTick + 1) missing += raw.Tick - lastTick - 1;
            lastTick = raw.Tick; count++;
            // Copy pooled arrays before the hook returns them to the pool.
            var framePlayers = raw.Players.Take(raw.PlayerCount).ToArray();
            latest = new { schema_version = "fa-match-snapshot/0.1", source = "native_match_hook",
                synthetic = false, match_id = matchId, status, captured_at = DateTimeOffset.UtcNow,
                tick = raw.Tick, display_tick = raw.DisplayTick, period = raw.Period,
                home = raw.Home, away = raw.Away, home_metadata = home, away_metadata = away,
                players = framePlayers, player_metadata = players, match_date = date, competition };
            return true;
        }
    }
    public void SetMetadata(RealtimeTeamMetadata h, RealtimeTeamMetadata a,
        IReadOnlyList<RealtimePlayerMetadata> p, string? matchDate, RealtimeCompetitionMetadata? c)
    {
        lock (gate) { home = h; away = a; players = p.ToArray(); date = matchDate; competition = c; metadataTime = Environment.TickCount64; }
    }
    public void MarkEnded(nint source) { lock (gate) { if (source == address) { status = "ended"; latest = null; } } }
    public TimelineStatus GetStatus() { lock (gate) return new(count, lastTick, missing, duplicate, outOfOrder); }
    private void Write()
    {
        if (Interlocked.Exchange(ref writing, 1) != 0) return;
        try
        {
            lock (gate)
            {
                var json = JsonSerializer.Serialize(latest ?? new { schema_version = "fa-match-snapshot/0.1", source = "native_match_hook", synthetic = false, status });
                var tmp = path + ".tmp";
                File.WriteAllText(tmp, json);
                File.Move(tmp, path, true);
            }
        }
        catch (Exception e) { FMMatchLens.Plugin.Diagnostics.PluginLogger.Warning($"Match output failed: {e.Message}"); }
        finally { Volatile.Write(ref writing, 0); }
    }
    public void Dispose() { writer.Dispose(); lock (gate) { status = "stopped"; latest = null; } Write(); }
}
internal readonly record struct TimelineStatus(int FrameCount, int LastTick, long MissingTickCount, long DuplicateTickCount, long OutOfOrderTickCount);
