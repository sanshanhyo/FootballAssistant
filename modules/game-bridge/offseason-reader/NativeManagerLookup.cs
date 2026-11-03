using System.Diagnostics;
using System.Runtime.InteropServices;
using ManagerCandidates;
using Microsoft.Win32.SafeHandles;

namespace FootballAssistant.OffseasonReader;

public static class NativeManagerLookup
{
    public static NativeManagerResult Read(int pid) => Read(pid, NativeReadProfile.Read(pid));
    public static NativeManagerResult Read(int pid, NativeReadProfile profile)
    {
        if (pid <= 0) return new("unavailable", "invalid_input");
        if (!profile.Matched) return new("unavailable", profile.Reason ?? "unsupported_native_profile");
        try
        {
            using var process = Process.GetProcessById(pid);
            if (!string.Equals(process.ProcessName, "fm", StringComparison.OrdinalIgnoreCase)) return new("unavailable", "wrong_process");
            var module = process.Modules.Cast<ProcessModule>().SingleOrDefault(m => string.Equals(m.ModuleName, "game_plugin.dll", StringComparison.OrdinalIgnoreCase));
            if (module is null) return new("unavailable", "module_unavailable");
            using var memory = Native.OpenProcess(0x1010, false, pid);
            if (memory.IsInvalid) return new("unavailable", "process_unavailable");
            return new NativeManagerReader(new ProcessMemory(memory), module.BaseAddress.ToInt64()).Read();
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception or IOException or UnauthorizedAccessException or OverflowException)
        { return new("unavailable", "read_failed"); }
    }
    private sealed class ProcessMemory : IReadOnlyMemory
    {
        private readonly SafeProcessHandle handle;
        public ProcessMemory(SafeProcessHandle handle) => this.handle = handle;
        public byte[] Read(long address, int length)
        {
            if (address < 65536 || length <= 0 || length > 128) throw new InvalidOperationException();
            var bytes = new byte[length];
            if (!Native.ReadProcessMemory(handle, (IntPtr)address, bytes, (nuint)length, out nuint read) || read != (nuint)length) throw new InvalidOperationException();
            return bytes;
        }
    }
    private static class Native
    {
        [DllImport("kernel32.dll", SetLastError = true)] public static extern SafeProcessHandle OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] public static extern bool ReadProcessMemory(SafeProcessHandle process, IntPtr address, byte[] buffer, nuint size, out nuint read);
    }
}
