using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

// Compiled ONLY by the isolated offline batch project. No candidate project/host
// registers this entry. Keep module lease locked through roots cleanup and accounting.
internal sealed partial class WindowsLoadedModuleLease
{
    internal BatchChunkResult? RunBatchChunk(BatchPolicy policy, BatchRequest request,
        CancellationToken cancellationToken = default)
    {
        lock (lifetime)
        {
            if (!string.Equals(VerifiedHash, policy.Approval.Context.GameHash, StringComparison.Ordinal)) return null;
            return BatchCollector.Run(policy, request, () =>
            {
                EnsureExports(BatchNativeBackend.RequiredExports.ToArray());
                return new BatchNativeBackend(VerifiedHash,
                    (name, type) => Marshal.GetDelegateForFunctionPointer(exports[name], type));
            }, () => MainThreadGuard.ReadWindowsScanIdentity(MainThreadGuard.CurrentWindowsThreadId()),
                () => DateTimeOffset.UtcNow, cancellationToken);
        }
    }
}
