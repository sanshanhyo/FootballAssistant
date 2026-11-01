using System.Threading.Channels;

namespace FootballAssistant.GameBridge;

// Independent of BridgeRuntime: no NativeUiReader, publishers, observers or game API bindings.
internal sealed class WindowsProbeRuntime : IDisposable
{
    private readonly WindowsProbeScheduler scheduler;
    private readonly Channel<string> lines = Channel.CreateBounded<string>(new BoundedChannelOptions(100)
        { SingleReader = true, FullMode = BoundedChannelFullMode.DropOldest });

    internal WindowsProbeRuntime()
    {
        var root = WindowsProbeConfiguration.ResolvePrivateRoot(
            Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_PRIVATE_ROOT"),
            typeof(WindowsProbeRuntime).Assembly.Location);
        var directory = Path.Combine(root, "logs");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(directory);
        Directory.CreateDirectory(directory);
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(directory);
        var path = Path.Combine(directory, "windows-scheduler-probe.log");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
        _ = Task.Run(async () =>
        {
            await foreach (var line in lines.Reader.ReadAllAsync())
                try
                {
                    WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(path);
                    await File.AppendAllTextAsync(path, line + Environment.NewLine);
                }
                catch { /* Diagnostics cannot affect game execution. */ }
        });
        try { scheduler = new WindowsProbeScheduler(message => lines.Writer.TryWrite($"{DateTimeOffset.UtcNow:O} {message}")); }
        catch { lines.Writer.TryComplete(); throw; }
    }

    public void Dispose() { scheduler.Dispose(); lines.Writer.TryComplete(); }
}
