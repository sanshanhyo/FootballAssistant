# Alpha 0.0.1 candidate branch inventory

Snapshot: 2026-11-01 UTC. This is consolidation, not release approval.

## Consolidation
- Candidate: `release/alpha-0.0.1-rc`, based on `20117e31e7bf7cb7fa9f41c13524b930de64447b`.
- That baseline already contains Reader `6c27d17f` and UI `5b185282`; no repeated cherry-picks.
- Merge MIT preparation `fcee292c`, legacy reader index `03a41aa8`, and author documentation `885f9502`, retaining their histories.
- Resolve CONTRIBUTING add/add by preserving docs/update original verbatim; archive previous integration README and CONTRIBUTING separately. README and CONTRIBUTING remain byte-identical to docs/update.
- Resolve LICENSE add/add using explicitly authorized scoped MIT; third-party notices and exclusions remain.
- No existing branch deleted or rewritten, no existing PR/main merged, no release or production feed published.

## Branch disposition
| Branch | Disposition |
| --- | --- |
| main | Keep: stable/default baseline, unchanged. |
| release/alpha-0.0.1-rc | Keep: single candidate/review destination; not yet release-ready. |
| docs/update | Integrated history; retain until author verifies documentation and candidate lands. |
| integration/alpha-reader-ui | Integrated ancestor; freeze/retain until candidate lands. |
| feature/pet-light-motion | Integrated ancestor; retain while draft PR #1 remains open. Do not merge #1 separately into candidate. |
| fix/mit-license-preparation | Integrated; archive-eligible only after candidate acceptance. |
| docs/archive-legacy-reader | Integrated; archive-eligible only after candidate acceptance. |
| feat/companion-ui | Already ancestor; archive-eligible after acceptance. |
| feat/reader-semantics | Already ancestor; archive-eligible after acceptance. |
| test/windows-final-20261101 | Exact baseline retained for reproducible Windows trial. |
| test/windows-pet-reader-20261101 | Superseded trial. Its merge parents are ancestors of candidate and merge has no unique conflict-resolution patch; retain as historical evidence, no repeated merge needed. |

“Archive-eligible” is a recommendation, not deletion authorization.

## Exact source tips and CI snapshot
No exact-tip workflow means no exact-tip pass; historical failures are not erased by newer successful descendants.

| Branch | SHA | Runs |
| --- | --- | --- |
| `docs/archive-legacy-reader` | `03a41aa8902ab99e4c2f8a5b2e88e17e09d6efcd` | No run for exact tip (not a pass) |
| `docs/update` | `885f9502d89318b730af21476e1be8a91f1e2a8f` | No run for exact tip (not a pass) |
| `feat/companion-ui` | `13c1a6bf801821c4cff2c4586939035e6b8534c8` | [41073325931](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41073325931) Companion desktop: failure (push) |
| `feat/reader-semantics` | `18acc2eb4d6f0541c0d2935bf5e9e1c6b8618655` | [41073966790](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41073966790) Backend checks: failure (push)<br>[41073966754](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41073966754) Companion desktop: success (push) |
| `feature/pet-light-motion` | `5b185282023f63155b466b8e70e722a45dc3bb47` | [41358183325](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358183325) Companion desktop: in_progress (pull_request)<br>[41358183272](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358183272) Backend checks: success (pull_request)<br>[41358180029](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358180029) Backend checks: success (push)<br>[41358180078](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358180078) Companion desktop: success (push) |
| `fix/mit-license-preparation` | `fcee292c5d0dfba1625cfa1fe0d4fa6a1d8b9f68` | [41333001307](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41333001307) Companion desktop: success (push)<br>[41333001201](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41333001201) Backend checks: success (push) |
| `integration/alpha-reader-ui` | `6c27d17f66134a705af941d93bfa11b2af94e54a` | No run for exact tip (not a pass) |
| `main` | `f7d1055eaac31cef1af3559195dadd94b239089f` | [41033033314](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41033033314) Backend checks: failure (push)<br>[41033033334](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41033033334) Companion desktop: success (push) |
| `test/windows-final-20261101` | `20117e31e7bf7cb7fa9f41c13524b930de64447b` | [41358358808](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358358808) Companion desktop: in_progress (push)<br>[41358358864](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358358864) Bridge payload candidate: success (push)<br>[41358358814](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358358814) Windows bridge probe (no game): success (push)<br>[41358358839](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41358358839) Backend checks: success (push) |
| `test/windows-pet-reader-20261101` | `c5ff21658cd960ec17858558549b17509f19bc8a` | [41355468647](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41355468647) Companion desktop: success (push)<br>[41355468570](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41355468570) Bridge payload candidate: success (push)<br>[41355468629](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41355468629) Windows bridge probe (no game): success (push)<br>[41355468652](https://github.com/sanshanhyo/FootballAssistant/actions/runs/41355468652) Backend checks: success (push) |

## Publication blockers / author review
1. README original has GPLv3 badge but MIT footer; root LICENSE is MIT. Badge needs author-approved correction before release.
2. README completed page-reading and proactive-hint claims need reconciliation with current Windows-only memory-reader evidence; real model and actual Windows window acceptance remain outstanding. Do not infer them from fixtures or CI.
3. README release download wording precedes an actual production release. Production signed feed and assets are not published; Ed25519 metadata is not Authenticode signing. Portable updates remain manual.
4. Original CONTRIBUTING targets main, which remains unchanged until review/merge; candidate is the interim test destination.
5. Existing docs/roadmap.md is historical and unchanged; no independent VISION file was found. Historical archive documents are snapshots: relative links and platform claims must be read against their original integration commit, not as current release instructions.
6. Third-party redistribution/license review remains required; retaining notices and passing tests is not blanket licensing clearance.
7. Candidate CI and Windows real acceptance must be checked at the final remote SHA. Desktop package version remains 0.0.1-alpha.1 and Python project version 0.1.0; no unrequested version rewrite performed.

## Cloud validation
- Node syntax and test suite: 324 passed, 0 failed.
- Initial Python suite: 900 passed, 1 failed, 20 skipped, 17 subtests passed. SDK localhost fixture failed because cloud SOCKS proxy requires absent socksio; isolated offline rerun without proxy: 901 passed, 20 skipped, 17 subtests passed (Python 3.12.14). No code or dependency modification was needed.
- No game, saves, samples, secrets, real-model calls or user computer accessed.
- C# and Windows native/package acceptance not run in this Linux cloud environment; source and candidate CI are separate evidence.
