using System.Diagnostics;
using System.Reflection.PortableExecutable;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace FootballAssistant.GameBridge;

internal sealed record ApprovedModule(string AbsolutePath, string Sha256, uint VolumeSerial, ulong FileIndex,
    string ExecutablePath, string ExecutableSha256);

internal static class VerifiedWindowsBuild
{
    // Operator-provided Windows build evidence; no Mac offsets or version inference.
    internal const string GameAssemblySha256 = "820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a";
    internal const string ExecutableSha256 = "2a7318c6984bcb3a19ff3304432b63462581cee33ba203f9a0a118f11c69e27e";
    internal static readonly string[] MetadataExports = { "il2cpp_domain_get", "il2cpp_domain_get_assemblies" };
}

// DRAFT: current-process module reference only; never calls LoadLibrary/NativeLibrary.Load.
// Expected file identity must come from trusted launch evidence, not this factory itself.
internal sealed class WindowsLoadedModuleLease : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] private struct FileInformation
    {
        public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh, WriteLow, WriteHigh;
        public uint VolumeSerial, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [StructLayout(LayoutKind.Sequential)] private struct MemoryInformation
    {
        public nint BaseAddress, AllocationBase;
        public uint AllocationProtect;
        public ushort PartitionId;
        public nuint RegionSize;
        public uint State, Protect, Type;
    }
    [DllImport("kernel32.dll", EntryPoint = "GetModuleHandleExW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ReferenceModule(uint flags, nint address, out nint module);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetModuleFileNameW(nint module, StringBuilder path, uint capacity);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
    private static extern nint GetProcAddress(nint module, string name);
    [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool FreeLibrary(nint module);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInformation information);
    [DllImport("kernel32.dll")] private static extern nuint VirtualQuery(nint address, out MemoryInformation information, nuint size);

    private readonly object lifetime = new();
    private nint module;
    private readonly FileStream file, executableFile;
    private readonly Dictionary<string, nint> exports;
    internal string VerifiedHash { get; }
    private WindowsLoadedModuleLease(nint module, FileStream file, FileStream executableFile, Dictionary<string, nint> exports, string hash)
    { this.module = module; this.file = file; this.executableFile = executableFile; this.exports = exports; VerifiedHash = hash; }

    internal static WindowsLoadedModuleLease Acquire(ApprovedModule approval)
    {
        if (!OperatingSystem.IsWindows() || !Environment.Is64BitProcess) throw new PlatformNotSupportedException("Windows x64 only.");
        if (!approval.Sha256.Equals(VerifiedWindowsBuild.GameAssemblySha256, StringComparison.OrdinalIgnoreCase) ||
            !approval.ExecutableSha256.Equals(VerifiedWindowsBuild.ExecutableSha256, StringComparison.OrdinalIgnoreCase) || approval.FileIndex == 0)
            throw new InvalidOperationException("Exact verified Windows game/executable hashes and trusted file identity required.");
        WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(approval.AbsolutePath);
        var expectedPath = Path.GetFullPath(approval.AbsolutePath);
        if (!Path.GetFileName(expectedPath).Equals("GameAssembly.dll", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Only the approved GameAssembly is in scope.");
        var file = new FileStream(expectedPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        nint referenced = 0;
        FileStream? executableFile = null;
        try
        {
            WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(approval.ExecutablePath);
            using var process = Process.GetCurrentProcess();
            var executablePath = Path.GetFullPath(approval.ExecutablePath);
            if (!Path.GetFileName(executablePath).Equals("fm.exe", StringComparison.OrdinalIgnoreCase) ||
                process.MainModule is not { } executable || !Path.GetFullPath(executable.FileName).Equals(executablePath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Current process is not the approved fm.exe path.");
            executableFile = new FileStream(executablePath, FileMode.Open, FileAccess.Read, FileShare.Read);
            var exeHash = Convert.ToHexString(SHA256.HashData(executableFile));
            if (!exeHash.Equals(approval.ExecutableSha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Current fm.exe SHA256 mismatch.");
            if (!GetFileInformationByHandle(file.SafeFileHandle, out var identity) ||
                identity.VolumeSerial != approval.VolumeSerial || (((ulong)identity.IndexHigh << 32) | identity.IndexLow) != approval.FileIndex)
                throw new InvalidOperationException("GameAssembly file identity differs from trusted launch evidence.");
            var hash = Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant();
            if (!hash.Equals(approval.Sha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("GameAssembly SHA256 mismatch.");
            file.Position = 0;
            using var pe = new PEReader(file, PEStreamOptions.LeaveOpen);
            var headers = pe.PEHeaders;
            if (headers.CoffHeader.Machine != Machine.Amd64 || headers.PEHeader?.Magic != PEMagic.PE32Plus)
                throw new InvalidOperationException("Expected x64 PE32+ GameAssembly.");
            using var current = Process.GetCurrentProcess();
            var candidates = current.Modules.Cast<ProcessModule>().Where(m =>
                Path.GetFileName(m.FileName).Equals("GameAssembly.dll", StringComparison.OrdinalIgnoreCase)).ToArray();
            if (candidates.Length != 1 || !Path.GetFullPath(candidates[0].FileName).Equals(expectedPath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Exactly one already-loaded approved module is required.");
            var existing = candidates[0];
            if (!ReferenceModule(4, existing.BaseAddress, out referenced) || referenced != existing.BaseAddress)
                throw new InvalidOperationException("Unable to reference the existing module mapping.");
            var path = new StringBuilder(32768);
            var length = GetModuleFileNameW(referenced, path, (uint)path.Capacity);
            if (length == 0 || length >= path.Capacity || !Path.GetFullPath(path.ToString()).Equals(expectedPath, StringComparison.OrdinalIgnoreCase) ||
                existing.ModuleMemorySize != headers.PEHeader.SizeOfImage)
                throw new InvalidOperationException("Loaded module path/image size mismatch.");
            var exports = new Dictionary<string, nint>(StringComparer.Ordinal);
            foreach (var name in VerifiedWindowsBuild.MetadataExports)
            {
                var address = GetProcAddress(referenced, name);
                var rva = address.ToInt64() - referenced.ToInt64();
                var executableSection = headers.SectionHeaders.Any(s =>
                    (s.SectionCharacteristics & (SectionCharacteristics.MemExecute | SectionCharacteristics.MemRead)) ==
                        (SectionCharacteristics.MemExecute | SectionCharacteristics.MemRead) &&
                    (s.SectionCharacteristics & SectionCharacteristics.MemWrite) == 0 &&
                    rva >= s.VirtualAddress && rva < (long)s.VirtualAddress + s.VirtualSize);
                if (address == 0 || rva < 0 || rva >= headers.PEHeader.SizeOfImage || !executableSection ||
                    VirtualQuery(address, out var memory, (nuint)Marshal.SizeOf<MemoryInformation>()) == 0 ||
                    memory.AllocationBase != referenced || memory.Type != 0x1000000 || memory.State != 0x1000 ||
                    (memory.Protect & 0x100) != 0 || (memory.Protect & 0xff) != 0x20)
                    throw new InvalidOperationException("Export is missing, forwarded, guarded or outside executable module memory: " + name);
                exports.Add(name, address);
            }
            WindowsProbeConfiguration.ValidateAbsoluteNonReparsePath(expectedPath);
            return new WindowsLoadedModuleLease(referenced, file, executableFile, exports, hash);
        }
        catch { if (referenced != 0) FreeLibrary(referenced); file.Dispose(); executableFile?.Dispose(); throw; }
    }

    private T Bind<T>(string name) where T : Delegate
    {
        if (module == 0) throw new ObjectDisposedException(nameof(WindowsLoadedModuleLease));
        return Marshal.GetDelegateForFunctionPointer<T>(exports[name]);
    }
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint DomainGet();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint DomainAssemblies(nint domain, out nuint count);

    internal MetadataSummary? RunMetadata(WindowsSmokePolicy policy, SmokeRequest request, CancellationToken cancellationToken = default)
    {
        lock (lifetime) return RunMetadataLocked(policy, request, cancellationToken);
    }

    private MetadataSummary? RunMetadataLocked(WindowsSmokePolicy policy, SmokeRequest request, CancellationToken cancellationToken)
    {
        // This module is never exposed as an ungated native reader. Only these two functions
        // are invoked, and Execute consumes/revalidates the policy grant before either call.
        var domain = Bind<DomainGet>("il2cpp_domain_get");
        var assemblies = Bind<DomainAssemblies>("il2cpp_domain_get_assemblies");
        return MetadataSmoke.Execute(policy, request, VerifiedHash,
            () => { cancellationToken.ThrowIfCancellationRequested(); return MainThreadGuard.ReadWindowsIdentity(MainThreadGuard.CurrentWindowsThreadId()); },
            () => DateTimeOffset.UtcNow, () => domain(), value =>
            {
                var pointer = assemblies(value, out var count);
                return new AssemblySpan(pointer, count);
            }, cancellationToken);
    }

    public void Dispose()
    {
        lock (lifetime)
        {
            var handle = Interlocked.Exchange(ref module, 0);
            if (handle == 0) return;
            FreeLibrary(handle);
            file.Dispose();
            executableFile.Dispose();
        }
    }
}
