using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace FootballAssistant.GameBridge;

// Separate offline draft. Neither constructing a policy nor possessing a request
// enables a host. Only a locally approved, explicitly enabled allowlist can admit work.
internal sealed record BatchAnchor(string Path, string TextSha256);
internal sealed record BatchLimits(int MaximumRequests = 4, int RequestOperations = 2048,
    double RequestMilliseconds = 1000, int TotalOperations = 8192,
    double TotalMilliseconds = 4000, double CooldownSeconds = 2);
internal sealed record BatchApproval(SmokeContext Context, Guid BatchId, Guid PageEpoch,
    int PanelIndex, string SubtreePath, BatchAnchor Anchor1, BatchAnchor Anchor2,
    DateTimeOffset ApprovedAt, DateTimeOffset ExpiresAt, BatchLimits Limits, bool ModeEnabled = false);
internal sealed record BatchRequest(int SchemaVersion, Guid Nonce, Guid BatchId, int Sequence,
    Guid PageEpoch, int Pid, string Session, string BridgeHash, string GameHash,
    string ConfirmedWindowClass, int PanelIndex, string SubtreePath, string ApprovalSha256,
    string CursorSha256, DateTimeOffset CreatedAt, DateTimeOffset ExpiresAt, string Cursor = "");
internal sealed record BatchGrant(BatchRequest Request, long Window,
    int MaximumOperations, double MaximumMilliseconds);
internal enum BatchCompletion { Rejected, Continue, Complete, Terminal }

internal sealed class BatchPolicy
{
    internal const int SchemaVersion = 2;
    internal static readonly string EmptyCursorSha256 = Digest("");
    private readonly object gate = new();
    private readonly BatchApproval approval;
    private readonly WindowsSmokePolicy identityPolicy;
    private readonly HashSet<Guid> consumed = new(); // At most four entries.
    private BatchGrant? active;
    private DateTimeOffset activeStarted, availableAt;
    private string expectedCursor = EmptyCursorSha256;
    private int requests, totalOperations;
    private double totalMilliseconds;
    private bool terminal;

    internal BatchPolicy(BatchApproval approval)
    {
        ArgumentNullException.ThrowIfNull(approval);
        ArgumentNullException.ThrowIfNull(approval.Context);
        ArgumentNullException.ThrowIfNull(approval.Limits);
        var limits = approval.Limits;
        if (approval.BatchId == Guid.Empty || approval.PageEpoch == Guid.Empty ||
            approval.PanelIndex is < 0 or > 31 || !ValidPath(approval.SubtreePath) ||
            !ValidAnchor(approval.Anchor1) || !ValidAnchor(approval.Anchor2) ||
            approval.Anchor1.Path == approval.Anchor2.Path ||
            approval.ExpiresAt <= approval.ApprovedAt ||
            approval.ExpiresAt - approval.ApprovedAt > TimeSpan.FromSeconds(120) ||
            limits.MaximumRequests is < 1 or > 4 || limits.RequestOperations is < 1 or > 2048 ||
            limits.TotalOperations is < 1 or > 8192 || limits.TotalOperations < limits.RequestOperations ||
            !double.IsFinite(limits.RequestMilliseconds) || limits.RequestMilliseconds is <= 0 or > 1000 ||
            !double.IsFinite(limits.TotalMilliseconds) || limits.TotalMilliseconds is <= 0 or > 4000 ||
            limits.TotalMilliseconds < limits.RequestMilliseconds ||
            !double.IsFinite(limits.CooldownSeconds) || limits.CooldownSeconds is < 2 or > 120)
            throw new ArgumentException("Invalid bounded batch approval.");
        // All nested values are immutable records containing immutable scalar/string values.
        // No caller-owned arrays, dictionaries, delegates or UI pointers enter the approval.
        this.approval = approval;
        identityPolicy = new WindowsSmokePolicy(approval.Context);
        ApprovalSha256 = Digest(JsonSerializer.Serialize(approval));
        availableAt = approval.ApprovedAt;
    }

    internal BatchApproval Approval => approval;
    internal string ApprovalSha256 { get; }
    internal bool Terminal { get { lock (gate) return terminal; } }
    internal int RequestsConsumed { get { lock (gate) return requests; } }
    internal int TotalOperations { get { lock (gate) return totalOperations; } }
    internal double TotalMilliseconds { get { lock (gate) return totalMilliseconds; } }
    internal string ExpectedCursorSha256 { get { lock (gate) return expectedCursor; } }
    // Explicit cancellation also works during cooldown/idle. An active grant remains
    // accountable by Finish; stopping never discards its cleanup/accounting obligation.
    internal void Stop() { lock (gate) terminal = true; }

    internal static bool ValidPath(string? path)
    {
        if (path is null || path.Length > 191) return false; // 48 * 3 + 47 separators.
        if (path.Length == 0) return true;
        var parts = path.Split('/');
        if (parts.Length > 48) return false;
        foreach (var part in parts)
            if (part.Length is < 1 or > 3 || (part.Length > 1 && part[0] == '0') ||
                part.Any(c => c is < '0' or > '9') || !int.TryParse(part, out var index) || index > 511)
                return false;
        return true;
    }
    internal static bool IsWithinSubtree(string path, string subtree) =>
        ValidPath(path) && ValidPath(subtree) &&
        (subtree.Length == 0 || path == subtree || path.StartsWith(subtree + "/", StringComparison.Ordinal));
    internal static bool ValidDigest(string? value) => value is { Length: 64 } &&
        value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static bool ValidAnchor(BatchAnchor? anchor) => anchor is not null &&
        ValidPath(anchor.Path) && (anchor.Path.Length == 0 || anchor.Path.Split('/').Length <= 16) && ValidDigest(anchor.TextSha256) && anchor.TextSha256 != EmptyCursorSha256;
    internal static string Digest(string value)
    {
        ArgumentNullException.ThrowIfNull(value);
        if (value.Length > 8192) throw new ArgumentException("Digest input exceeds bound.");
        return Convert.ToHexString(SHA256.HashData(new UTF8Encoding(false, true).GetBytes(value))).ToLowerInvariant();
    }

    internal static string ComputeCursorHash(string cursor)
    {
        ArgumentNullException.ThrowIfNull(cursor);
        if (cursor.Length > 16384) throw new ArgumentException("Cursor exceeds bound.");
        return Convert.ToHexString(SHA256.HashData(new UTF8Encoding(false, true).GetBytes(cursor))).ToLowerInvariant();
    }
    private static bool CursorMatches(BatchRequest request)
    {
        if (request.Cursor is null || request.Cursor.Length > 16384) return false;
        try { return request.CursorSha256 == ComputeCursorHash(request.Cursor); }
        catch (ArgumentException) { return false; }
    }

    // The host calls this only for a new explicit request. No timer, retry or fallback lives here.
    internal BatchGrant? TryBegin(BatchRequest request, WindowsThreadIdentity freshIdentity, DateTimeOffset now)
    {
        lock (gate)
        {
            if (request is null || !approval.ModeEnabled || terminal || active is not null || now < availableAt) return null;
            if (now >= approval.ExpiresAt || requests >= approval.Limits.MaximumRequests ||
                totalOperations >= approval.Limits.TotalOperations || totalMilliseconds >= approval.Limits.TotalMilliseconds)
            { terminal = true; return null; }
            var context = approval.Context;
            if (request.SchemaVersion != SchemaVersion || request.Nonce == Guid.Empty || consumed.Contains(request.Nonce) ||
                request.BatchId != approval.BatchId || request.Sequence != requests + 1 || request.PageEpoch != approval.PageEpoch ||
                request.Pid != context.Pid || request.Session != context.Session || request.BridgeHash != context.BridgeHash ||
                request.GameHash != context.GameHash || request.ConfirmedWindowClass != context.ConfirmedWindowClass ||
                request.PanelIndex != approval.PanelIndex || request.SubtreePath != approval.SubtreePath ||
                request.ApprovalSha256 != ApprovalSha256 || request.CursorSha256 != expectedCursor || !CursorMatches(request) ||
                request.CreatedAt > now || now - request.CreatedAt > TimeSpan.FromSeconds(30) ||
                request.ExpiresAt <= now || request.ExpiresAt <= request.CreatedAt ||
                request.ExpiresAt - request.CreatedAt > TimeSpan.FromSeconds(30) || request.ExpiresAt > approval.ExpiresAt)
                return null;
            var window = identityPolicy.SelectWindow(freshIdentity); // Complete fresh scan, identical policy.
            if (window is null) { terminal = true; return null; }
            consumed.Add(request.Nonce);
            requests++;
            activeStarted = now;
            active = new(request, window.Value,
                Math.Min(approval.Limits.RequestOperations, approval.Limits.TotalOperations - totalOperations),
                Math.Min(approval.Limits.RequestMilliseconds, approval.Limits.TotalMilliseconds - totalMilliseconds));
            return active;
        }
    }

    // Called at every native boundary by the collector's budget. An invalid active grant,
    // ownership loss, cancellation or expiration terminates the batch, never caches approval.
    internal bool CheckActive(BatchGrant grant, WindowsThreadIdentity freshIdentity, DateTimeOffset now,
        CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            if (grant is null || terminal || active != grant || cancellationToken.IsCancellationRequested || now < activeStarted ||
                now >= approval.ExpiresAt || now >= grant.Request.ExpiresAt ||
                identityPolicy.SelectWindow(freshIdentity) != grant.Window)
            { terminal = true; return false; }
            return true;
        }
    }

    // Call in finally, including exceptions and failed guards. Full measured cost is charged;
    // soft-deadline overshoot is never subtracted or represented as successful continuation.
    // anchorsValidated means BOTH approved anchors passed before AND after this chunk.
    internal BatchCompletion Finish(BatchGrant grant, int operations, double elapsedMilliseconds,
        bool anchorsValidated, bool complete, string? nextCursorSha256, DateTimeOffset now)
    {
        lock (gate)
        {
            if (grant is null || active != grant) { terminal = true; return BatchCompletion.Rejected; }
            active = null;
            if (operations < 0 || !double.IsFinite(elapsedMilliseconds) || elapsedMilliseconds < 0)
            { terminal = true; return BatchCompletion.Terminal; }
            totalOperations = (int)Math.Min(int.MaxValue, (long)totalOperations + operations);
            totalMilliseconds += elapsedMilliseconds;
            if (terminal || !anchorsValidated || now < activeStarted || now >= approval.ExpiresAt ||
                now >= grant.Request.ExpiresAt || operations > grant.MaximumOperations ||
                elapsedMilliseconds > grant.MaximumMilliseconds ||
                totalOperations > approval.Limits.TotalOperations || totalMilliseconds > approval.Limits.TotalMilliseconds)
            { terminal = true; return BatchCompletion.Terminal; }
            if (complete) { terminal = true; return BatchCompletion.Complete; }
            if (!ValidDigest(nextCursorSha256) || nextCursorSha256 == expectedCursor ||
                requests >= approval.Limits.MaximumRequests || totalOperations >= approval.Limits.TotalOperations ||
                totalMilliseconds >= approval.Limits.TotalMilliseconds)
            { terminal = true; return BatchCompletion.Terminal; }
            if (approval.ExpiresAt - now <= TimeSpan.FromSeconds(approval.Limits.CooldownSeconds))
            { terminal = true; return BatchCompletion.Terminal; }
            expectedCursor = nextCursorSha256!;
            availableAt = now.AddSeconds(approval.Limits.CooldownSeconds);
            return BatchCompletion.Continue;
        }
    }
}
