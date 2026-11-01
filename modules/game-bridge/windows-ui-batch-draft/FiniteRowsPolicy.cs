using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace FootballAssistant.GameBridge;

// Separate finite manifest. StableProfileAsserted/PageEpoch are operator assertions,
// never page identity proof. No arbitrary paths, automatic retry, or cached UI objects.
internal sealed record FiniteRowsApproval(SmokeContext Context, Guid BatchId, Guid PageEpoch,
    Guid FirstNonce, Guid SecondNonce, DateTimeOffset CreatedAt, DateTimeOffset ExpiresAt,
    bool StableProfileAsserted, bool ModeEnabled = false, string Manifest = "goalkeeper_rows0_3");
internal sealed record FiniteRowsRequest(int SchemaVersion, Guid BatchId, Guid PageEpoch,
    int ChunkIndex, Guid Nonce, string ApprovalSha256);
internal sealed record FiniteRowsGrant(FiniteRowsRequest Request, long Window, int RowStart,
    int RowCount, int MaximumOperations, double MaximumMilliseconds, string SelectionProfile);

internal sealed class FiniteRowsPolicy
{
    internal const int SchemaVersion = 4;
    internal const int MaximumChunks = 18, ChunkOperations = 2048, TotalOperationLimit = 36864;
    internal const double ChunkMilliseconds = 1000, TotalMillisecondLimit = 18000, CooldownMilliseconds = 2000;
    private readonly object gate = new();
    private readonly WindowsSmokePolicy identityPolicy;
    private readonly string[] profiles;
    private readonly Guid[] nonces;
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
            approval.Context.Session is null || approval.Context.Session.Length > 128 || !ValidManifest(approval.Manifest))
            throw new ArgumentException("Invalid finite goalkeeper-row manifest.");
        identityPolicy = new WindowsSmokePolicy(approval.Context);
        Approval = approval;
        profiles = AttributeRowSelection.ManifestProfiles(approval.Manifest);
        if (profiles.Length is < 1 or > MaximumChunks || profiles.Any(profile => !AttributeRowSelection.TryGet(profile,out _)))
            throw new ArgumentException("Invalid fixed manifest profiles.");
        nonces = Enumerable.Range(0,profiles.Length).Select(index => DeriveNonce(approval,index)).ToArray();
        if (nonces.Any(nonce => nonce == Guid.Empty) || nonces.Distinct().Count() != nonces.Length)
            throw new ArgumentException("Manifest child nonces must all be distinct.");
        ApprovalSha256 = Convert.ToHexString(SHA256.HashData(new UTF8Encoding(false,true)
            .GetBytes(JsonSerializer.Serialize(approval)))).ToLowerInvariant();
        lastUtc = approval.CreatedAt;
    }
    internal static bool ValidManifest(string? name) => name is "goalkeeper_rows0_3" or "profile_rows0_3" or "profile_all_rows";
    // First two operator-approved nonces remain unchanged. Additional fixed chunks are
    // deterministic from immutable manifest identifiers; no caller-supplied nonce array.
    private static Guid DeriveNonce(FiniteRowsApproval approval,int index)
    {
        if(index == 0) return approval.FirstNonce;
        if(index == 1) return approval.SecondNonce;
        var input = "finite-rows-child-v1|" + approval.BatchId.ToString("D") + "|" + approval.FirstNonce.ToString("D") +
            "|" + approval.SecondNonce.ToString("D") + "|" + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
        var digest = SHA256.HashData(Encoding.ASCII.GetBytes(input));
        return new Guid(digest.AsSpan(0,16));
    }
    internal Guid NonceAt(int index) => index >= 0 && index < nonces.Length ? nonces[index] : throw new ArgumentOutOfRangeException(nameof(index));
    internal int MaximumDeclaredChunks => profiles.Length;
    internal int MaximumDeclaredOperations => MaximumDeclaredChunks * ChunkOperations;
    internal double MaximumDeclaredMilliseconds => MaximumDeclaredChunks * ChunkMilliseconds;
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
            if (active is not null || consumed >= MaximumDeclaredChunks || request is null || request.SchemaVersion != SchemaVersion ||
                request.BatchId != Approval.BatchId || request.PageEpoch != Approval.PageEpoch || request.ChunkIndex != consumed ||
                request.Nonce != NonceAt(consumed) || request.ApprovalSha256 != ApprovalSha256 ||
                monotonicMilliseconds < notBeforeMonotonic || TotalOperations >= MaximumDeclaredOperations || TotalMilliseconds >= MaximumDeclaredMilliseconds)
            { terminal = true; return null; }
            consumed++; // Consume even when fresh identity admission fails.
            long? window;
            try { window = identityPolicy.SelectWindow(freshIdentity); }
            catch { terminal = true; throw; }
            if (window is null || (manifestWindow is not null && manifestWindow != window))
            { terminal = true; return null; }
            manifestWindow = window;
            started = now; startedMonotonic = monotonicMilliseconds;
            var profile = profiles[request.ChunkIndex];
            if (!AttributeRowSelection.TryGet(profile,out var selection)) { terminal = true; return null; }
            active = new(request,window.Value,selection.RowStart,selection.RowCount,ChunkOperations,ChunkMilliseconds,profile);
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
                TotalMilliseconds + monotonicMilliseconds - startedMonotonic >= MaximumDeclaredMilliseconds ||
                TotalOperations >= MaximumDeclaredOperations)
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
                TotalOperations > MaximumDeclaredOperations || TotalMilliseconds > MaximumDeclaredMilliseconds)
            { terminal = true; return false; }
            if (consumed == MaximumDeclaredChunks) { terminal = true; return true; }
            notBeforeMonotonic = monotonicMilliseconds + CooldownMilliseconds;
            if (TotalOperations >= MaximumDeclaredOperations || TotalMilliseconds >= MaximumDeclaredMilliseconds ||
                Approval.ExpiresAt - now <= TimeSpan.FromMilliseconds(CooldownMilliseconds))
            { terminal = true; return false; }
            return true;
        }
    }
}
