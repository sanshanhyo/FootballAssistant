# Owned-window guard benchmark (no game)

This standalone executable compiles only the window collector, scheduler types, smoke
policy, and its own fixtures. It cannot load a candidate host, module lease, or IL2CPP
backend. No FM installation or user computer is needed. Run on Windows with .NET 10:

```sh
python modules/game-bridge/tests/verify_guard_component_scan.py
dotnet run -c Release --project modules/game-bridge/tests/WindowsGuardBenchmark.csproj -- baseline
dotnet run -c Release --project modules/game-bridge/tests/WindowsGuardBenchmark.csproj -- components
```

The existing no-game probe workflow runs these as **separate processes** and uploads
`guard-benchmark-baseline.json` and `guard-benchmark-components.json`. Production files
are unchanged. The instrumented collector is a test-only copy: the Python drift check
requires identical native signatures and collector query/control flow after removing
timing lines. Each fixture also compares its owned-window evidence against production.

## Fixtures and limitations

Each process creates 1, 8, then 31 owned top-level popup windows. One is visible,
the rest hidden. Native checks verify duplicate-visible rejection and wrong-thread
rejection and the 32-owned-window bound; existing `UiDraftTests.cs` retains the synthetic failure/ambiguity matrix.
All windows are destroyed on exit. No external windows are changed. As in production,
full desktop enumeration queries each visited window's owner but retains details only
for this process; output never includes handles, PIDs, TIDs, class strings or titles.

The first identity timing precedes policy setup. Only scenario 1 is process-cold;
subsequent scenarios are not independent cold starts. After setup and parity checks,
16 warm-ups precede 128 measured samples. Grants are fixture-only, expire normally,
and authorize pure policy checks, never game operations. Timing expiration is a real
failure, not bypassed for benchmarking.

`full_guard` measures one fresh identity scan plus `CheckStartedResolve` (including
UTC time, lock and window selection). `grant` is the latter part. `policy` separately
measures `SelectWindow` on that sample's identity and is **outside** full_guard.
`loop_allocated_bytes` covers the whole measured loop, including this extra policy call.
Reported integer microseconds and median/p95 are descriptive, not confidence intervals.
Do not compare separate CI runs as controlled experiments or use CI desktop cost as
an estimate of the user's desktop without further evidence.

## Component indices

Component arrays are totals/call counts for measured samples only; baseline arrays
are zero. Instrumented timing changes the cost. **Do not subtract it from operational
budgets or add overlapping components together.**

0. EnumWindows inclusive, including all callbacks.
1. Callback inclusive, including child components.
2. Initial owner/thread query for every visited window.
3. Owned-window class lookup and immediate error capture.
4. Owned-window visibility query.
5. Owned-window rectangle query and immediate error capture.
6. Owned-window owner/thread recheck.
7. List/buffer allocation and owned-row construction (multiple events per scan).
8. Final identity/array materialization.

EnumWindows time minus callback time is only a diagnostic residual, **not** a precise
kernel-time measurement: it includes marshalling and timing overhead. Component 7
does not capture every runtime allocation/JIT/GC cost. Use baseline/component results
together to choose what to profile next; no optimization is bundled here.

## Numeric status and failures

`status`: 0 success, 1 failure, 2 unsupported. `error_code`: 0 none, 1 invalid mode,
2 non-Windows or unusable owned-window desktop, 3 policy/grant failure,
4 production/component parity mismatch, 5 native deny-test failure, 6 unexpected error, 7 owned-window cleanup failure,
8 artifact write failure (numeric status remains on stdout).
Unsupported runs exit 2 and fail the CI step explicitly, not silently pass. Exceptions
are not dumped because their paths/details are outside the numeric output contract.
`mode`: 0 baseline, 1 instrumented. Failed runs may contain completed earlier scenarios;
never treat them as a full pass. No performance threshold or speculative speedup claim.
