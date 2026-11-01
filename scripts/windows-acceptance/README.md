# Normal-user Windows finite acceptance — preparation only

**Not authorized to execute yet.** Root must confirm the exact fresh candidate/session and the user's separate ACL and 35-attribute capture approval. Approval of seven-object tactics diagnostics does not authorize this operation. No credentials are included or copied.

## Required operator preparation

1. Stage this reviewed bundle and the verified portable. Portable source commit is `df6f95359eaaede7fcc2220b1508ff25d6eb290e`; EXE SHA256 is `0738bd59fb184418a84003aa00e64d9f1415927b303e7a544a85de9964236d63`. Do not infer app revision from Electron FileVersion.
2. Obtain approval naming exactly `<candidate>\windows-finite-rows-private` and its five fixed files: `session.json`, `module-status.json`, `finite-rows-state.json`, `finite-rows-request.json`, `finite-rows-evidence.jsonl`. The launcher retains Husky ownership and replaces only those objects' DACLs with protected Husky/SYSTEM/Administrators full-control entries. It does not change ancestors or any other existing files. New isolated `%LOCALAPPDATA%\FootballAssistantAcceptance\<unique-name>` is protected on creation; it holds settings, verified software and the backend's own new runtime token. Existing directories are not reused.
3. A **fresh, unconsumed native session** is mandatory. The current `pages-remaining-candidate` session is terminal and will be refused. Restart/new session or archival is a separate explicit operator action, not part of this launcher. Do not delete/reuse old request/evidence to bypass the refusal. Preserve the approved root scope if a new candidate is selected; obtain new scope approval otherwise.
4. In trusted preparation, construct a small JSON plan from the independently approved DLL/game hashes and actual freshly verified PID, entry TID, session UUID. Never derive registration from an evidence event. Confirm those values against source controls and the live producer. Compute the plan SHA256 and put it in the reviewed launch command. Plan fields (all required, no extras):

```json
{"schema_version":1,"app_commit":"df6f95359eaaede7fcc2220b1508ff25d6eb290e","candidate_dir":"D:\\FootballAssistant-Tests\\20261031-bridge-prep\\<APPROVED-CANDIDATE>","portable_exe":"C:\\<STAGED-PORTABLE>.exe","portable_sha256":"0738bd59fb184418a84003aa00e64d9f1415927b303e7a544a85de9964236d63","bridge_sha256":"<APPROVED-DLL-SHA256>","game_sha256":"820d6618acafac7dffc1ef3b489582eddb84b0343d4f34d55fff9fb70881e00a","pid":0,"entry_tid":0,"session_id":"<FRESH-SESSION-UUID>","user_data_name":"<NEW-UNIQUE-LOWERCASE-NAME>"}
```

Placeholders deliberately fail validation. The launcher cannot auto-trust a new session/hash from files. It requires normal, non-elevated `ALAWELL\Husky`; not the sandbox or another administrator account.

## User's minimal action after preparation and explicit approval

Open the intended player's attribute page and leave it stable for approximately 2 minutes. Under normal Husky sign-in, run the **one fully filled, reviewed PowerShell command** (actual verified Python and bundle paths supplied by preparation):

```powershell
& '<VERIFIED-PYTHON.exe>' -I '<BUNDLE>\run_acceptance.py' --plan '<PLAN.json>' --plan-sha256 '<PINNED-PLAN-SHA256>' --execute --approve-private-acl --approve-finite-capture --stable-profile-asserted
```

Omitting `--execute` performs read-only preflight only. Do not use Run as administrator. No impersonation, UAC bypass, persistent execution-policy change, credential entry or old settings import is required. The launcher refuses occupied port17827, old captures, wrong owner, symlinks, hash mismatch or missing approval; it never retries capture/rearms a terminal session.

## What runs and what proves acceptance

The launcher privately stages the hash-verified portable, writes credential-free settings, generates ONE `profile_all_rows` request (18 chunks, 35 attributes, 120-second expiry) and binds backend registration to that **same own request**. It launches the real-mode portable with isolated userData and a restricted inherited environment. The native host performs finite capture; the launcher does not navigate or restart the game.

Only authenticated loopback GET `/v1/status` and GET `/v1/reader/current-page-attributes` are queried. The runtime token stays in the same-user process; it is not printed or copied. Response bodies, attribute text/values, session IDs, PID, token, paths and model credentials are not emitted. Output includes only bounded progress/counts, genuine capture UTC range, stale-row count, unknown-player/non-atomic flags and natural-expiry clearing result. Failures emit a bounded code, not a traceback/raw response.

Success means the real Windows source reached the authenticated API as all 18 chunks/35 rows and naturally cleared at expiry. It does **not** prove a visible 35-row pet panel (diagnostic panels were removed), an AI answer, a stable player identity or an atomic snapshot. Pet process launch is reported separately; portable launcher-process liveness alone is not an Electron UI smoke test. No model requests are made. Normal model configuration/actual AI conversation is a separate later acceptance step, without importing old credentials.

The launcher leaves the pet/new userData and completed native request in place. It never kills the game, archives/deletes old captures or changes ownership. A failed/consumed attempt requires operator review, not rerunning the same command. Cloud mocks/static checks are not Windows kernel execution; review and real Windows fixture CI remain deployment gates.
