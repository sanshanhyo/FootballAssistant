using System.Diagnostics;
using System.Security.Cryptography;

namespace FootballAssistant.OffseasonReader;

// Interpretation is permitted only for the exact independently researched files.
// Hashes are evidence of a supported layout, not a game-save or account identity.
public sealed record NativeReadProfile(string Status, string? Reason = null,
    string? GamePluginSha256 = null, string? GameAssemblySha256 = null, string? MetadataSha256 = null)
{
    public const string NativeHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
    public const string AssemblyHash = "820D6618ACAFAC7DFFC1EF3B489582EDDB84B0343D4F34D55FFF9FB70881E00A";
    public const string MetadataHash = "A380792F33BA4EB048FA2FFEBC6C504B001F85C76E4128E4D41CA24D7B017C4C";
    public bool Matched => Status == "available" && GamePluginSha256 == NativeHash &&
        GameAssemblySha256 == AssemblyHash && MetadataSha256 == MetadataHash;

    public static NativeReadProfile Read(int pid) => Read(pid, null);
    public static NativeReadProfile Read(int pid, NativeReadContext? context)
    {
        if (pid <= 0) return new("unavailable", "invalid_input");
        try
        {
            using var process = Process.GetProcessById(pid);
            if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("unavailable", "wrong_process");
            var modules = process.Modules.Cast<ProcessModule>().ToArray();
            var native = modules.SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
            var assembly = modules.SingleOrDefault(m => string.Equals(m.ModuleName, "GameAssembly.dll", StringComparison.OrdinalIgnoreCase));
            var executable = process.MainModule?.FileName;
            var nativePath = native?.FileName;
            var assemblyPath = assembly?.FileName;
            if (string.IsNullOrEmpty(nativePath) || string.IsNullOrEmpty(assemblyPath) || string.IsNullOrEmpty(executable)) return new("unavailable", "profile_files_unavailable");
            // Derive Unity's standard metadata location from the running executable,
            // never from a hard-coded installation directory or a private capture.
            var metadata = Path.Combine(Path.GetDirectoryName(executable)!, Path.GetFileNameWithoutExtension(executable) + "_Data", "il2cpp_data", "Metadata", "global-metadata.dat");
            return FromHashes(NativeReadContext.Hash(process, native!, context), Hash(assemblyPath), Hash(metadata));
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or NotSupportedException or CryptographicException)
        { return new("unavailable", "profile_files_unavailable"); }
    }
    internal static NativeReadProfile FromHashes(string native, string assembly, string metadata) =>
        new(native == NativeHash && assembly == AssemblyHash && metadata == MetadataHash ? "available" : "unavailable",
            native == NativeHash && assembly == AssemblyHash && metadata == MetadataHash ? null : "unsupported_native_profile", native, assembly, metadata);
    private static string Hash(string path)
    {
        using var stream = File.OpenRead(path);
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(stream));
    }
}
