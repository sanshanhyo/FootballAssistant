using FootballAssistant.GameBridge;

namespace Doorstop;

// Separate experimental DLL/project. The ordinary production/probe Start is untouched.
public static class Entrypoint
{
    private static int started;
    private static MetadataCandidateHost? host;
    public static void Start()
    {
        if (Interlocked.Exchange(ref started, 1) != 0) return;
        try
        {
            host = new MetadataCandidateHost(typeof(Entrypoint).Assembly.Location);
            AppDomain.CurrentDomain.ProcessExit += (_, _) => Stop();
        }
        catch (Exception error) { try { Console.Error.WriteLine("[FootballAssistant metadata candidate] Disabled: " + error.Message); } catch { } }
    }
    public static void Stop() => host?.Dispose();
}
