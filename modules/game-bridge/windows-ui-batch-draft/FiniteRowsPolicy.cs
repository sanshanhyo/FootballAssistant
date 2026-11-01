using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace FootballAssistant.GameBridge;

// Separate finite manifest. StableProfileAsserted/PageEpoch are operator assertions,
// never page identity proof. No arbitrary paths, automatic retry, or cached UI objects.
internal sealed record FiniteRowsApproval(SmokeContext Context, Guid BatchId, Guid PageEpoch,
    Guid FirstNonce, Guid SecondNonce, DateTimeOffset CreatedAt, DateTimeOffset ExpiresAt,
    bool StableProfileAsserted, bool ModeEnabled = false);
internal sealed record FiniteRowsRequest(int SchemaVersion, Guid BatchId, Guid PageEpoch,
    int ChunkIndex, Guid Nonce, string ApprovalSha256);
internal sealed record FiniteRowsGrant(FiniteRowsRequest Request, long Window, int RowStart,
    int RowCount, int MaximumOperations, double MaximumMilliseconds, string SelectionProfile);

internal sealed class FiniteRowsPolicy
{
    internal const int SchemaVersion = 4;
    internal const int MaximumChunks = 2, ChunkOperations = 2048, TotalOperationLimit = 4096;
    internal const double ChunkMilliseconds = 1000, TotalMillisecondLimit = 2000, CooldownMilliseconds = 2000;
    private readonly object gate = new();
    private readonly WindowsSmokePolicy identityPolicy;
    private FiniteRowsGrant? active;
    private bool terminal;
    private long? manifestWindow; // Equality fence only; every child still performs a fresh full scan.
    private int consumed;
    private double lastMonotonic = double.NegativeInfinity, notBeforeMonotonic, startedMonotonic;
    private DateTimeOffset lastUtc, started;
    internal FiniteRowsPolicy(FiniteRowsApproval approval)
    {
        ArgumentNullException.ThrowIfNull(approval); ArgumentNullException.ThrowIfNull(approval.Context);
        if (approval.BatchId == Guid.Empty || approval.PageEpoch == Guid.Empty || approval.FirstNonce == Guid.Empty ||
            approval.SecondNonce == Guid.Empty || approval.FirstNonce == approval.SecondNonce || !approval.StableProfileAsserted ||
            approval.ExpiresAt <= approval.CreatedAt || approval.ExpiresAt - approval.CreatedAt > TimeSpan.FromSeconds(120) ||
            approval.Context.Session is null || approval.Context.Session.Length > 128)
            throw new ArgumentException("Invalid finite goalkeeper-row manifest.");
        identityPolicy = new WindowsSmokePolicy(approval.Context);
        Approval = approval;
        ApprovalSha256 = Convert.ToHexString(SHA256.HashData(new UTF8Encoding(false,true)
            .GetBytes(JsonSerializer.Serialize(approval)))).ToLowerInvariant();
        lastUtc = approval.CreatedAt;
    }
    internal FiniteRowsApproval Approval { get; }
    internal string ApprovalSha256 { get; }
    internal bool Terminal { get { lock(gate) return terminal; } }
    internal int ChunksConsumed { get { lock(gate) return consumed; } }
    internal int NextChunkIndex { get { lock(gate) return consumed; } }
    internal bool Consumed { get { lock(gate) return consumed > 0; } }
    internal int TotalOperations { get; private set; }
    internal double TotalMilliseconds { get; private set; }
    internal double NotBeforeMonotonicMilliseconds { get { lock(gate) return notBeforeMonotonic; } }
    internal double NextEligibleMonotonicMilliseconds => NotBeforeMonotonicMilliseconds;
    internal void Stop() { lock(gate) terminal = true; }
    private bool Clock(DateTimeOffset now, double monotonic)
    {
        if (!double.IsFinite(monotonic) || monotonic < 0 || monotonic < lastMonotonic || now < lastUtc || now >= Approval.ExpiresAt)
        { terminal = true; return false; }
        lastMonotonic = monotonic; lastUtc = now; return true;
    }
    internal FiniteRowsGrant? TryBegin(FiniteRowsRequest request, WindowsThreadIdentity freshIdentity,
        DateTimeOffset now, double monotonicMilliseconds)
    {
        lock(gate)
        {
            if (!Approval.ModeEnabled || terminal) return null;
            if (!Clock(now,monotonicMilliseconds)) return null;
            if (active is not null || consumed >= MaximumChunks || request is null || request.SchemaVersion != SchemaVersion ||
                request.BatchId != Approval.BatchId || request.PageEpoch != Approval.PageEpoch || request.ChunkIndex != consumed ||
                request.Nonce != (consumed == 0 ? Approval.FirstNonce : Approval.SecondNonce) || request.ApprovalSha256 != ApprovalSha256 ||
                monotonicMilliseconds < notBeforeMonotonic || TotalOperations >= TotalOperationLimit || TotalMilliseconds >= TotalMillisecondLimit)
            { terminal = true; return null; }
            consumed++; // Consume even when fresh identity admission fails.
            long? window;
            try { window = identityPolicy.SelectWindow(freshIdentity); }
            catch { terminal = true; throw; }
            if (window is null || (manifestWindow is not null && manifestWindow != window))
            { terminal = true; return null; }
            manifestWindow = window;
            started = now; startedMonotonic = monotonicMilliseconds;
            active = new(request,window.Value,request.ChunkIndex * 2,2,ChunkOperations,ChunkMilliseconds,
                request.ChunkIndex == 0 ? "goalkeeper_rows0_1" : "goalkeeper_rows2_3");
            return active;
        }
    }
    // Composed with child DiscoveryPolicy's full fresh identity check at EVERY boundary.
    // This outer gate does not repeat the native scan; it never replaces the child guard.
    internal bool CheckActive(FiniteRowsGrant grant, DateTimeOffset now,
        double monotonicMilliseconds, CancellationToken cancellation = default)
    {
        lock(gate)
        {
            if (terminal || active != grant || grant is null || cancellation.IsCancellationRequested ||
                !Clock(now,monotonicMilliseconds) || monotonicMilliseconds - startedMonotonic >= ChunkMilliseconds ||
                TotalMilliseconds + monotonicMilliseconds - startedMonotonic >= TotalMillisecondLimit ||
                TotalOperations >= TotalOperationLimit)
            { terminal = true; return false; }
            return true;
        }
    }
    // Output is publishable only after matching child cleanup, final fresh guard, and this ack.
    // success also includes the parent's strict semantic group validation; never emit partial rows.
    internal bool Finish(FiniteRowsGrant grant, int operations, double elapsedMilliseconds, bool success,
        DateTimeOffset now, double monotonicMilliseconds)
    {
        lock(gate)
        {
            if (grant is null || active != grant) { terminal = true; return false; }
            active = null;
            if (operations < 0 || !double.IsFinite(elapsedMilliseconds) || elapsedMilliseconds < 0)
            { terminal = true; return false; }
            TotalOperations = (int)Math.Min(int.MaxValue,(long)TotalOperations + operations);
            // Caller elapsed may include extra measured work, but cannot under-report the monotonic interval.
            if (double.IsFinite(monotonicMilliseconds) && monotonicMilliseconds >= startedMonotonic)
                elapsedMilliseconds = Math.Max(elapsedMilliseconds, monotonicMilliseconds - startedMonotonic);
            TotalMilliseconds += elapsedMilliseconds;
            if (terminal || !Clock(now,monotonicMilliseconds) || !success || now < started ||
                operations > ChunkOperations || elapsedMilliseconds > ChunkMilliseconds ||
                TotalOperations > TotalOperationLimit || TotalMilliseconds > TotalMillisecondLimit)
            { terminal = true; return false; }
            if (consumed == MaximumChunks) { terminal = true; return true; }
            notBeforeMonotonic = monotonicMilliseconds + CooldownMilliseconds;
            if (TotalOperations >= TotalOperationLimit || TotalMilliseconds >= TotalMillisecondLimit ||
                Approval.ExpiresAt - now <= TimeSpan.FromMilliseconds(CooldownMilliseconds))
            { terminal = true; return false; }
            return true;
        }
    }
}
