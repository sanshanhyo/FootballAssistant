namespace FootballAssistant.GameBridge;

internal sealed record MetadataSummary(bool DomainPresent, ulong AssemblyCount);
internal readonly record struct AssemblySpan(nint Pointer, nuint Count);

// No object traversal, image names, class scans, runtime_invoke, registry, observer or UI.
internal static class MetadataSmoke
{
    internal static MetadataSummary? Execute(WindowsSmokePolicy policy, SmokeRequest request, string moduleHash,
        Func<WindowsThreadIdentity> freshIdentity, Func<DateTimeOffset> now,
        Func<nint> domainGet, Func<nint, AssemblySpan> assembliesGet, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (request.Stage != SmokeStage.Metadata || !policy.MatchesModuleHash(moduleHash)) return null;
        var grant = policy.TryConsume(request, freshIdentity(), now());
        if (grant is null) return null;
        var succeeded = false;
        try
        {
            if (!policy.TryBeginCall(grant, freshIdentity(), now())) return null;
            cancellationToken.ThrowIfCancellationRequested();
            var domain = domainGet();
            if (domain == 0) throw new InvalidOperationException("IL2CPP domain unavailable.");
            // No second call if identity/window/expiry changes after domain_get.
            if (!policy.CheckStartedMetadata(grant, freshIdentity(), now()))
                throw new InvalidOperationException("Window/thread identity changed after domain query.");
            cancellationToken.ThrowIfCancellationRequested();
            var assemblies = assembliesGet(domain);
            if (assemblies.Pointer == 0 || assemblies.Count == 0 || assemblies.Count > 1024)
                throw new InvalidOperationException("IL2CPP assembly span unavailable or exceeds metadata budget.");
            succeeded = true;
            return new(true, (ulong)assemblies.Count);
        }
        finally { policy.CompleteMetadata(grant, succeeded); }
    }
}
