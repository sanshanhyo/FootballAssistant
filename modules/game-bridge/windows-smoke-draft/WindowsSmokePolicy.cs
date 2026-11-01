namespace FootballAssistant.GameBridge;

// Experimental candidates/tests only; not src/*.cs or any production host.
// This validates authorization records; it does NOT validate a loaded native module, call a
// native export, read request files, or provide a capability accepted by NativeUiReader.
internal enum SmokeStage { Metadata, UiResolve, UiText }
internal sealed record SmokeContext(int Pid, string Session, string BridgeHash, string GameHash,
    string ConfirmedWindowClass, uint EntryThread);
internal sealed record SmokeRequest(Guid Nonce, int Pid, string Session, string BridgeHash, string GameHash,
    string ConfirmedWindowClass, SmokeStage Stage, DateTimeOffset CreatedAt, DateTimeOffset ExpiresAt, int PanelIndex = 0);
internal sealed record SmokeGrant(Guid Nonce, SmokeStage Stage, long Window, DateTimeOffset ExpiresAt, int PanelIndex = 0);

internal sealed class WindowsSmokePolicy
{
    private readonly SmokeContext context;
    private readonly HashSet<Guid> consumed = new();
    private readonly object gate = new();
    private bool metadataAttempted, metadataSucceeded, resolveAttempted, resolveSucceeded, uiAttempted;
    private SmokeGrant? pendingResolve, activeResolve;
    private SmokeGrant? pendingMetadata;
    private readonly Dictionary<Guid, SmokeGrant> armed = new();
    private bool metadataStarted;
    private SmokeGrant? activeUi;

    internal WindowsSmokePolicy(SmokeContext context)
    {
        if (context.Pid <= 0 || context.EntryThread == 0 || string.IsNullOrWhiteSpace(context.Session) ||
            string.IsNullOrWhiteSpace(context.ConfirmedWindowClass) || context.ConfirmedWindowClass.Length > 126 ||
            !ValidHash(context.BridgeHash) || !ValidHash(context.GameHash))
            throw new ArgumentException("Explicit session, verified class and module/build hash context required.");
        this.context = context;
    }
    private static bool ValidHash(string hash) => hash is { Length: 64 } && hash.All(Uri.IsHexDigit);

    // Fresh complete scan required; do not pass a cached HWND or previously selected row.
    internal long? SelectWindow(WindowsThreadIdentity identity)
    {
        if (identity.WindowScanStatus != "complete" || identity.ProcessId != (uint)context.Pid ||
            identity.CurrentThreadId != context.EntryThread || identity.InstallerThreadId != context.EntryThread ||
            identity.WindowCandidates is not { } windows || windows.Length != identity.WindowScanCount || windows.Length > 32)
            return null;
        // Incomplete class/owner evidence could hide a second qualifying window; reject the entire scan.
        if (windows.Any(w => w.Hwnd == 0 || !w.OwnerStable || w.OwnerPid != (uint)context.Pid || !w.ClassNameComplete))
            return null;
        var matchingClass = windows.Where(w => w.ClassName == context.ConfirmedWindowClass && w.VisibleStyle).ToArray();
        if (matchingClass.Any(w => !w.ClientRectAvailable)) return null;
        var eligible = matchingClass.Where(w => w.ClientWidth > 0 && w.ClientHeight > 0).ToArray();
        return eligible.Length == 1 && eligible[0].OwnerTid == context.EntryThread ? eligible[0].Hwnd : null;
    }

    internal SmokeGrant? TryConsume(SmokeRequest request, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
        {
            if (request.PanelIndex is < 0 or > 31 || (request.Stage != SmokeStage.UiText && request.PanelIndex != 0)) return null;
            if (request.Nonce == Guid.Empty || consumed.Count >= 64 || consumed.Contains(request.Nonce) ||
                request.Pid != context.Pid || request.Session != context.Session || request.BridgeHash != context.BridgeHash ||
                request.GameHash != context.GameHash || request.ConfirmedWindowClass != context.ConfirmedWindowClass ||
                request.CreatedAt > now || now - request.CreatedAt > TimeSpan.FromSeconds(30) ||
                request.ExpiresAt <= now || request.ExpiresAt <= request.CreatedAt ||
                request.ExpiresAt - request.CreatedAt > TimeSpan.FromSeconds(30)) return null;
            if (request.Stage == SmokeStage.Metadata ? metadataAttempted :
                request.Stage == SmokeStage.UiResolve ? !metadataSucceeded || resolveAttempted :
                request.Stage == SmokeStage.UiText ? !resolveSucceeded || uiAttempted : true) return null;
            var window = SelectWindow(freshIdentity);
            if (window is null) return null;
            consumed.Add(request.Nonce); // Always before any external call. Failure never restores an attempt.
            var grant = new SmokeGrant(request.Nonce, request.Stage, window.Value, request.ExpiresAt, request.PanelIndex);
            armed.Add(grant.Nonce, grant);
            if (request.Stage == SmokeStage.Metadata) { metadataAttempted = true; pendingMetadata = grant; }
            else if (request.Stage == SmokeStage.UiResolve) { resolveAttempted = true; pendingResolve = grant; }
            else uiAttempted = true;
            return grant;
        }
    }

    // Call immediately before the single native operation. Even a failed revalidation
    // consumes the grant; holding the record cannot trigger repeated reads.
    internal bool TryBeginCall(SmokeGrant grant, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
        {
            if (!armed.TryGetValue(grant.Nonce, out var expected) || expected != grant) return false;
            armed.Remove(grant.Nonce);
            if (grant.ExpiresAt <= now || SelectWindow(freshIdentity) != grant.Window) return false;
            if (grant.Stage == SmokeStage.Metadata) metadataStarted = true;
            else if (grant.Stage == SmokeStage.UiResolve) activeResolve = grant;
            else if (grant.Stage == SmokeStage.UiText) activeUi = grant;
            return true;
        }
    }

    internal string Session => context.Session;
    internal bool ResolveAttempted { get { lock (gate) return resolveAttempted; } }
    internal bool UiAttempted { get { lock (gate) return uiAttempted; } }
    internal bool MetadataAttempted { get { lock (gate) return metadataAttempted; } }

    internal bool MatchesModuleHash(string hash) => string.Equals(context.GameHash, hash, StringComparison.OrdinalIgnoreCase);

    internal bool CheckStartedMetadata(SmokeGrant grant, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
            return pendingMetadata == grant && metadataStarted && grant.Stage == SmokeStage.Metadata &&
                grant.ExpiresAt > now && SelectWindow(freshIdentity) == grant.Window;
    }

    internal bool CheckStartedResolve(SmokeGrant grant, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
            return activeResolve == grant && metadataSucceeded && grant.ExpiresAt > now && SelectWindow(freshIdentity) == grant.Window;
    }
    internal void CompleteResolve(SmokeGrant grant, bool succeeded)
    {
        lock (gate)
        {
            if (pendingResolve != grant || (succeeded && activeResolve != grant))
                throw new InvalidOperationException("Unknown resolve attempt.");
            pendingResolve = activeResolve = null; armed.Remove(grant.Nonce);
            resolveSucceeded = succeeded;
        }
    }

    internal bool CheckStartedUi(SmokeGrant grant, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
            return activeUi == grant && resolveSucceeded && grant.ExpiresAt > now && SelectWindow(freshIdentity) == grant.Window;
    }

    internal void CompleteUi(SmokeGrant grant)
    {
        lock (gate)
        {
            if (activeUi == grant) activeUi = null;
            armed.Remove(grant.Nonce);
        }
    }

    internal void CompleteMetadata(SmokeGrant grant, bool succeeded)
    {
        lock (gate)
        {
            if (pendingMetadata != grant || (succeeded && !metadataStarted)) throw new InvalidOperationException("Unknown or completed metadata attempt.");
            armed.Remove(grant.Nonce); // Completing/abandoning a stage revokes any not-yet-started grant.
            pendingMetadata = null;
            metadataSucceeded = succeeded;
        }
    }
}
