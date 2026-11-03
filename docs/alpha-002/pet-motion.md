# Alpha 0.0.2: bounded companionship motion

This branch extends the existing whole-image Web Animations controller; it does not create face art, model requests, dialogue or new character-package conventions.

- Happy and thinking retain their existing small reactions; sad adds a short downward tilt.
- A confirmed `idle` state starts one subtle 1 px, 1.8 s breathing pulse after 45 seconds. Completion schedules the next wait; animations never overlap. Unknown initial state does not start companionship.
- Existing motion-enabled preference, OS reduced-motion, visibility and dispose all suppress animation and clear pending timers immediately. Re-enabling waits another full interval instead of replaying old motion.
- New reactions, reset and disposal cancel older animations. Stale completions cannot restart timers or overwrite a newer state.
- `pulseIdle()` is also available for explicit bounded invocation; `timers` injection is a testing seam, not a saved preference.

Verification: `cd apps/companion && npm run check` (328 tests pass on cloud Linux). No FM access, model/API requests or native Electron visual QA were performed. The separate feat3 event adapter may output `sad`; actual trusted game-result wiring remains outside this motion branch.
