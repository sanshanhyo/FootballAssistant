using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

internal sealed partial class WindowsLoadedModuleLease
{
    // Only the separate explicitly configured single-shot discovery host calls this.
    // The lifetime lock covers binding, all native work, cleanup and final accounting.
    internal DiscoveryResult? RunDiscoveryOnce(DiscoveryPolicy policy, DiscoveryRequest request,
        CancellationToken cancellationToken = default)
    {
        lock (lifetime)
        {
            if (!string.Equals(VerifiedHash, policy.Approval.Context.GameHash, StringComparison.Ordinal))
            { policy.Stop(); return null; }
            return DiscoveryCollector.Run(policy, request, () =>
            {
                EnsureExports(BatchNativeBackend.RequiredExports.ToArray());
                return new BatchNativeBackend(VerifiedHash,
                    (name, type) => Marshal.GetDelegateForFunctionPointer(exports[name], type));
            }, () => MainThreadGuard.ReadWindowsScanIdentity(policy.Approval.Context.EntryThread),
                () => DateTimeOffset.UtcNow, cancellationToken);
        }
    }
}
