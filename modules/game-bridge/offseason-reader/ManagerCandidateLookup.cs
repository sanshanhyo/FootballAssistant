using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using ManagerCandidates;
using Microsoft.Win32.SafeHandles;

namespace FootballAssistant.OffseasonReader;

public static class ManagerCandidateLookup
{
    private const string ExpectedHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
    public static Result Read(int pid, uint clubUid)
    {
        if (pid <= 0 || clubUid is 0 or uint.MaxValue) return Unknown();
        return ReadCandidates(pid, clubUid);
    }
    // These are human-manager candidates, not proof of the current user.
    public static Result ReadAll(int pid) => pid <= 0 ? Unknown() : ReadCandidates(pid, 0);
    private static Result ReadCandidates(int pid, uint clubUid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return Unknown();
            var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
            if (module is null || string.IsNullOrEmpty(module.FileName)) return Unknown();
            using (var file = File.OpenRead(module.FileName))
            using (var sha = SHA256.Create())
                if (Convert.ToHexString(sha.ComputeHash(file)) != ExpectedHash) return Unknown();
            using var handle = Native.OpenProcess(0x1010, false, pid);
            if (handle.IsInvalid) return Unknown();
            var reader = new ManagerCandidateReader(new ProcessMemory(handle), module.BaseAddress.ToInt64());
            var result = clubUid == 0 ? reader.ReadAll() : reader.Read(clubUid);
            return result.Status == "experimental_candidates_incomplete" ? result : Unknown();
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException)
        { return Unknown(); }
    }
    private static Result Unknown() => new("unknown", 0, 0, Array.Empty<Candidate>());
    private sealed class ProcessMemory : IReadOnlyMemory
    {
        private readonly SafeProcessHandle handle;
        public ProcessMemory(SafeProcessHandle handle) => this.handle = handle;
        public byte[] Read(long address, int length)
        {
            if (address < 65536 || length <= 0 || length > 64) throw new InvalidOperationException();
            var buffer = new byte[length];
            if (!Native.ReadProcessMemory(handle, (IntPtr)address, buffer, (nuint)length, out nuint read) || read != (nuint)length) throw new InvalidOperationException();
            return buffer;
        }
    }
    private static class Native
    {
        [DllImport("kernel32.dll", SetLastError = true)] public static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool ReadProcessMemory(SafeProcessHandle process, IntPtr address, byte[] buffer, nuint size, out nuint read);
    }
}
