using FootballAssistant.GameBridge;
namespace Doorstop;

// Separate assembly. No ordinary/probe/UI-candidate/batch entrypoint is changed.
public static class Entrypoint
{
    private static int started;
    private static FiniteRowsCandidateHost? host;
    public static void Start()
    {
        if (Interlocked.Exchange(ref started, 1) != 0) return;
        try
        {
            host = new FiniteRowsCandidateHost(typeof(Entrypoint).Assembly.Location);
            AppDomain.CurrentDomain.ProcessExit += (_, _) => Stop();
        }
        catch { /* Absent/invalid explicit configuration: no timer or module query. */ }
    }
    public static void Stop() => host?.Dispose();
}
