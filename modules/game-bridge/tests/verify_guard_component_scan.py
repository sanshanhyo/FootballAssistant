"""Fail if the test-only instrumented collector drifts from production query/control flow."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
production = (root / "src/MainThreadGuard.cs").read_text(encoding="utf-8")
instrumented = (root / "tests/WindowsGuardComponentScan.cs").read_text(encoding="utf-8")
marker = "        // Same complete bounded enumeration"
original = production[production.index(marker):production.index("\n    public static bool IsCurrent()")]
measured = instrumented[instrumented.index(marker):instrumented.rfind("\n}")]
lines = []
for line in measured.splitlines():
    stripped = line.strip()
    if (stripped.startswith("var ") and stripped.endswith("Start = Stopwatch.GetTimestamp();") or
        stripped.startswith("metrics.Add(") or stripped == "finally { metrics.Add(1, callbackStart); }" or
        stripped == "return result;"):
        continue
    lines.append(line.replace("var result = identity with", "return identity with"))
assert original.strip() == "\n".join(lines).strip(), "Instrumented collector query/control flow drifted"
start = '    [DllImport("user32.dll")]\n    private static extern uint GetWindowThreadProcessId'
original_imports = production[production.index(start):production.index("    internal static uint CurrentWindowsThreadId()")]
measured_imports = instrumented[instrumented.index(start):instrumented.index("    internal static WindowsThreadIdentity Read(")]
assert original_imports == measured_imports, "Instrumented Win32 signatures drifted"
print("PASS instrumented collector retains production query/control flow and Win32 signatures")
