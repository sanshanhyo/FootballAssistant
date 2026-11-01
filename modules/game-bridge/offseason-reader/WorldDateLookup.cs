using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace FootballAssistant.OffseasonReader;

// Experimental fixed-build date candidate. One normal day advance matched;
// save/session switching and behavior on other builds remain unverified.
// Corroborating research (GPL-3.0, no code copied):
// https://github.com/barak14/fm-editor/blob/b377ec5bba4ffb7dd37c9347c9d0dac051cf8fd1/docs/fm27/memory-layout.md
public static class WorldDateLookup
{
    private const string ExpectedHash = "BC940E472418FC5C214208D7CF30FECF600F689B6F9D71C11BA19A2DF0FE057F";
    public static WorldDateResult Read(int pid)
    {
        if (pid <= 0) return new("invalid_input", null, null);
        try
        {
            using var process = Process.GetProcessById(pid);
            if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("wrong_process", null, null);
            var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
            if (module is null || string.IsNullOrEmpty(module.FileName)) return new("module_unavailable", null, null);
            using (var file = File.OpenRead(module.FileName))
            using (var sha = SHA256.Create())
                if (Convert.ToHexString(sha.ComputeHash(file)) != ExpectedHash) return new("unsupported_binary", null, null);
            using var memory = new SafeProcessHandle(OpenProcess(0x1010, false, pid));
            if (memory.IsInvalid) return new("process_unavailable", null, null);
            long address = module.BaseAddress.ToInt64() + 0x056AD378;
            if (!ReadPackedDate(memory, address, out uint first) || !ReadPackedDate(memory, address, out uint second))
                return new("unavailable", null, null);
            if (first != second) return new("changed_during_read", null, null);
            int year = (int)(first >> 16);
            var date = year <= 1900 ? null : PlayerValueDecoder.Date(first);
            return date is null ? new("unavailable", null, null) : new("experimental", date, DateTimeOffset.UtcNow);
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException)
        { return new("unavailable", null, null); }
    }
    private static bool ReadPackedDate(SafeProcessHandle p, long address, out uint value)
    {
        value = 0; var bytes = new byte[4];
        if (address <= 0 || !ReadProcessMemory(p, (nint)address, bytes, bytes.Length, out var read) || read != 4) return false;
        value = BitConverter.ToUInt32(bytes, 0); return true;
    }
    [DllImport("kernel32.dll", SetLastError = true)] private static extern nint OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool ReadProcessMemory(SafeProcessHandle process, nint address, byte[] buffer, int size, out nuint read);
    private sealed class SafeProcessHandle : Microsoft.Win32.SafeHandles.SafeHandleZeroOrMinusOneIsInvalid
    {
        public SafeProcessHandle(nint handle) : base(true) { SetHandle(handle); }
        protected override bool ReleaseHandle() => CloseHandle(handle);
        [DllImport("kernel32.dll")] private static extern bool CloseHandle(nint handle);
    }
}
public sealed record WorldDateResult(string Status, string? Date, DateTimeOffset? ObservedAt);
