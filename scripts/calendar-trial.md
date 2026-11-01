# Local Windows calendar trial

The desktop and calendar reader are experimental. Keep the repository, the game,
and an isolated test profile separate; do not commit profiles, credentials,
game files, or real snapshots. This trial does not change the game.

Build `modules/game-bridge/offseason-reader-cli/OffseasonReaderCli.csproj` with
the repository-pinned .NET SDK. Its output is a folder: keep the executable,
runtime configuration, managed assemblies, and dependency files together. The
reader is bound to the supported game binary fingerprint and fails closed for
other builds. A local .NET runtime matching the output target is also required.

Build the desktop from the chosen integration commit using the existing
`Companion desktop` Actions workflow, or the repository's documented desktop
packaging commands. Use its Windows portable EXE and keep it in a separate test
directory. The desktop bundle includes its Python backend; the calendar reader
and .NET runtime are provided separately for this trial.

Create an empty isolated profile directory containing `settings.json`:

```json
{"version":1,"backend":{"port":17837},"bridgePrivateRoot":"","backendEnvFile":""}
```

Choose an unused loopback port if 17837 is occupied. Run
`launch-calendar-trial.cmd` with four quoted arguments: the portable EXE, the
directory containing `dotnet.exe`, the reader EXE, and the isolated profile
directory. The launcher sets paths only for the launched process; it does not
install software or modify the system PATH. Configure model credentials in the
test UI, not in source control. A configured key may be represented by a mask;
the mask is not the key itself.

Example question: “北京国安接下来有哪些比赛？” The reader selects among
human-manager club candidates and uses the current in-game date. It does not
prove the active manager. Fixture results cover only loaded buckets within at
most 30 days in the same year; unknown venues and incomplete coverage remain
explicit. No response should be represented as a complete season schedule.
