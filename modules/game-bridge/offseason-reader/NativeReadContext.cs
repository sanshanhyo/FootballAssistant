using System.Diagnostics;
using System.Security.Cryptography;

namespace FootballAssistant.OffseasonReader;

// A single CLI capture may reuse this verified file lease. Never cache it between
// captures. The retained read-only handle denies writes/replacement on Windows;
// every reuse still checks the PID, process start, module base and canonical path.
public sealed class NativeReadContext : IDisposable
{
    private readonly PinnedNativeBinary lease;
    private NativeReadContext(PinnedNativeBinary lease) => this.lease = lease;
    public string Sha256 => lease.Sha256;

    public static NativeReadContext Open(Process process, ProcessModule module)
    {
        var identity = Identity(process, module);
        var lease = PinnedNativeBinary.Open(identity);
        try
        {
            lease.ReadHash(Identity(process, module));
            return new NativeReadContext(lease);
        }
        catch { lease.Dispose(); throw; }
    }
    internal static string Hash(Process process, ProcessModule module, NativeReadContext? context)
    {
        var identity = Identity(process, module);
        if (context is not null) return context.lease.ReadHash(identity);
        // Old public lookup entry points remain independently hash-verified.
        using var standalone = PinnedNativeBinary.Open(identity);
        return standalone.ReadHash(identity);
    }
    public bool IsCurrent(Process process)
    {
        // Refresh the module list at the end of the capture rather than trusting
        // a ProcessModule snapshot from before the read.
        process.Refresh();
        var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
        if (module is null) return false;
        try { return lease.ReadHash(Identity(process, module)) == Sha256; }
        catch (InvalidOperationException) { return false; }
    }
    private static NativeBinaryIdentity Identity(Process process, ProcessModule module)
    {
        if (process.HasExited || !string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(module.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase) || string.IsNullOrEmpty(module.FileName))
            throw new InvalidOperationException("Native process identity is unavailable");
        return new(process.Id, process.StartTime.ToUniversalTime().Ticks, module.BaseAddress.ToInt64(), Path.GetFullPath(module.FileName));
    }
    public void Dispose() => lease.Dispose();
}

internal readonly record struct NativeBinaryIdentity(int ProcessId, long StartedAtTicks, long ImageBase, string Path);
internal sealed class PinnedNativeBinary : IDisposable
{
    private readonly NativeBinaryIdentity identity;
    private readonly FileStream file;
    private bool disposed;
    internal string Sha256 { get; }
    private PinnedNativeBinary(NativeBinaryIdentity identity, FileStream file)
    {
        this.identity = identity;
        this.file = file;
        using var sha = SHA256.Create();
        Sha256 = Convert.ToHexString(sha.ComputeHash(file));
    }
    internal static PinnedNativeBinary Open(NativeBinaryIdentity identity)
    {
        if (identity.ProcessId <= 0 || identity.StartedAtTicks <= 0 || identity.ImageBase < 65536 || !Path.IsPathFullyQualified(identity.Path))
            throw new InvalidOperationException("Invalid native binary identity");
        var file = new FileStream(identity.Path, FileMode.Open, FileAccess.Read, FileShare.Read);
        try { return new PinnedNativeBinary(identity, file); }
        catch { file.Dispose(); throw; }
    }
    internal string ReadHash(NativeBinaryIdentity current)
    {
        if (disposed || file.SafeFileHandle.IsClosed || current.ProcessId != identity.ProcessId ||
            current.StartedAtTicks != identity.StartedAtTicks || current.ImageBase != identity.ImageBase ||
            !string.Equals(current.Path, identity.Path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Native binary lease does not match this capture");
        return Sha256;
    }
    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        file.Dispose();
    }
}
