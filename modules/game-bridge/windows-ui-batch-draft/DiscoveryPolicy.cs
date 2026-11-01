using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace FootballAssistant.GameBridge;

// Offline, opt-in structural discovery only. No host activation or business/page identity claim.
internal sealed record DiscoveryApproval(SmokeContext Context, Guid Nonce, int PanelIndex,
    string FocusPath, DateTimeOffset CreatedAt, DateTimeOffset ExpiresAt, bool ModeEnabled = false);
// The fingerprint binds every immutable server-approved context/path/time field; no client override.
internal sealed record DiscoveryRequest(int SchemaVersion, Guid Nonce, string ApprovalSha256);
internal sealed record DiscoveryGrant(DiscoveryRequest Request, long Window,
    int MaximumOperations, double MaximumMilliseconds);

internal sealed class DiscoveryPolicy
{
    internal const int SchemaVersion = 3;
    internal const int MaximumOperations = 2048;
    internal const double MaximumMilliseconds = 1000;
    private readonly object gate = new();
    private readonly WindowsSmokePolicy identityPolicy;
    private DiscoveryGrant? active;
    private DateTimeOffset started;
    private bool consumed, terminal;

    internal DiscoveryPolicy(DiscoveryApproval approval)
    {
        ArgumentNullException.ThrowIfNull(approval);
        ArgumentNullException.ThrowIfNull(approval.Context);
        if (approval.Nonce == Guid.Empty || approval.PanelIndex is < 0 or > 31 ||
            !ValidPath(approval.FocusPath) || approval.ExpiresAt <= approval.CreatedAt ||
            approval.ExpiresAt - approval.CreatedAt > TimeSpan.FromSeconds(120) ||
            approval.Context.Session is null || approval.Context.Session.Length > 128)
            throw new ArgumentException("Invalid bounded discovery approval.");
        identityPolicy = new WindowsSmokePolicy(approval.Context);
        Approval = approval; // Records contain immutable scalar/string values only.
        ApprovalSha256 = Convert.ToHexString(SHA256.HashData(new UTF8Encoding(false, true)
            .GetBytes(JsonSerializer.Serialize(approval)))).ToLowerInvariant();
    }

    internal DiscoveryApproval Approval { get; }
    internal string ApprovalSha256 { get; }
    internal bool Terminal { get { lock (gate) return terminal; } }
    internal bool Consumed { get { lock (gate) return consumed; } }
    internal int TotalOperations { get; private set; }
    internal double TotalMilliseconds { get; private set; }
    internal void Stop() { lock (gate) terminal = true; }

    internal static bool ValidPath(string? path)
    {
        if (path is null || path.Length > 127) return false;
        if (path.Length == 0) return true;
        var parts = path.Split('/');
        if (parts.Length > 32) return false;
        foreach (var part in parts)
            if (part.Length is < 1 or > 3 || (part.Length > 1 && part[0] == '0') ||
                part.Any(c => c is < '0' or > '9') || !int.TryParse(part, out var index) || index > 511)
                return false;
        return true;
    }

    internal DiscoveryGrant? TryBegin(DiscoveryRequest request, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
        {
            if (!Approval.ModeEnabled || terminal || consumed || request is null || now < Approval.CreatedAt) return null;
            if (now >= Approval.ExpiresAt) { terminal = true; return null; }
            if (request.SchemaVersion != SchemaVersion || request.Nonce != Approval.Nonce ||
                request.ApprovalSha256 != ApprovalSha256) return null;
            // An authenticated attempt consumes the only slot even if fresh identity rejects it.
            consumed = true;
            var window = identityPolicy.SelectWindow(freshIdentity);
            if (window is null) { terminal = true; return null; }
            started = now;
            active = new(request, window.Value, MaximumOperations, MaximumMilliseconds);
            return active;
        }
    }

    // Caller supplies a newly acquired full scan at every native boundary; never cache identity.
    internal bool CheckActive(DiscoveryGrant grant, WindowsThreadIdentity freshIdentity,
        DateTimeOffset now, CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            if (grant is null || active != grant || terminal || cancellationToken.IsCancellationRequested ||
                now < started || now >= Approval.ExpiresAt ||
                identityPolicy.SelectWindow(freshIdentity) != grant.Window)
            { terminal = true; return false; }
            return true;
        }
    }

    // Call after mandatory cleanup and final guard, including failure paths. No continuation.
    // Actual cost includes cleanup and all timing overhead; a soft overshoot denies output.
    internal bool Finish(DiscoveryGrant grant, int operations, double elapsedMilliseconds, bool success, DateTimeOffset now)
    {
        lock (gate)
        {
            if (grant is null || active != grant) { terminal = true; return false; }
            active = null;
            var wasTerminal = terminal;
            terminal = true;
            if (operations < 0 || !double.IsFinite(elapsedMilliseconds) || elapsedMilliseconds < 0) return false;
            TotalOperations = operations;
            TotalMilliseconds = elapsedMilliseconds;
            return !wasTerminal && success && now >= started && now < Approval.ExpiresAt &&
                operations <= MaximumOperations && elapsedMilliseconds <= MaximumMilliseconds;
        }
    }
}
