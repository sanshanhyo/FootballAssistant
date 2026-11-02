# One-time merged-branch cleanup audit

Authorized scope: the nine fixed branch/SHA pairs below, only if still exact main ancestors, with no open PR use and no unfinished CI. No main modification, PR closure, Release, global permission change, or deletion beyond this list. Author documentation branches and active product branches are excluded.

Recovery anchor: main commit `758463f5bd7bf63dce51539110d14523c837ba44`, also the parent of this audit commit. All listed tips were verified as its ancestors. Recreate a deleted branch at its original SHA if needed; this cleanup does not create restoration refs.

The workflow logs and job summary record actual outcomes. This file is the plan and restoration inventory, not a claim that deletion succeeded. API errors halt further deletes. A changed ref, active PR or unfinished Actions run is skipped. Exact-SHA git leases prevent deleting a newly advanced tip.

| Branch | Original SHA |
|---|---|
| docs/archive-legacy-reader | 03a41aa8902ab99e4c2f8a5b2e88e17e09d6efcd |
| feat/companion-ui | 13c1a6bf801821c4cff2c4586939035e6b8534c8 |
| feat/reader-semantics | 18acc2eb4d6f0541c0d2935bf5e9e1c6b8618655 |
| feature/pet-light-motion | 5b185282023f63155b466b8e70e722a45dc3bb47 |
| fix/mit-license-preparation | fcee292c5d0dfba1625cfa1fe0d4fa6a1d8b9f68 |
| integration/alpha-reader-ui | 6c27d17f66134a705af941d93bfa11b2af94e54a |
| release/alpha-0.0.1-rc | d4594120b972ac7e7a22d07ced474f870838b39e |
| fix/windows-reader-onboarding | 075d48604fb412e7fcc61c091ccb7c23830ea1c6 |
| test/windows-final-20261101 | 20117e31e7bf7cb7fa9f41c13524b930de64447b |

Retain this maintenance branch for audit. It is not intended for merge into main.
