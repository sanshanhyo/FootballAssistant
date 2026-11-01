# Windows first UI scalar — independent experimental candidate

Ordinary production/probe stays zero-native on Windows and NativeUiReader retains its
Windows constructor refusal. This separate candidate has an explicit Doorstop entrypoint,
but has no effect without its fixed DLL-adjacent opt-in file and three separately authored
session-bound requests. No enabling config or request is shipped. No real UI data has yet
been read by this candidate; fake tests do not establish game success.

## Explicit staged runbook (root coordinates installation/restart)

1. With FM normally closed, run `Prepare-UiCandidate.ps1 -ExecutablePath <original fm.exe>
   -GameAssemblyPath <original GameAssembly.dll> -CandidateDirectory <private DLL folder>`.
   It only reads approved hashes/FileID and writes private `footballassistant.windows-ui.json`.
   It does not install anything, alter a game file, launch FM or create a request.
2. Point the separately approved Doorstop configuration at
   `FootballAssistant.WindowsUiCandidate.dll`, retaining the private CoreCLR runtime. Start
   normally via Steam. Wait for `windows-ui-private/session.json`, module-status ready,
   and complete unique visible positive-client `UnityWndClass` owner/PID/TID evidence.
3. After confirming a stable page in THIS new session, invoke `Request-UiStage.ps1
   -CandidateDirectory <private DLL folder> -Stage metadata -StableCurrentSessionPageConfirmed`.
   Check `ui-evidence.jsonl` for successful two-call metadata result. This is not player data.
4. Reconfirm the current stable page; explicitly request `-Stage ui_resolve`. It permits
   one metadata-only class/method warm-up, at most 2048 reserved native boundary units and
   250ms soft elapsed from resolution start. No panel getter, runtime invoke, UI objects,
   roots, observer or registry in this phase. Successful methods cache only in this held
   module lease and session. Inspect the terminal result before proceeding.
5. Reconfirm the stable page and explicitly request `-Stage ui_text`. Omitted `-PanelIndex`
   preserves panel 0. Only after a particular index is authorized, add `-PanelIndex N`
   (canonical integer 0..31) to request exactly that one panel. One capture is allowed:
   250ms soft elapsed, 384 reserved native boundary units, one panel, 32 nodes, depth16,
   8 children/node and at most one text of128 UTF-16 units. No automatic stage advance,
   retry, refresh or repeated collection. A failure/budget/empty outcome is terminal.

Each request lasts at most30 seconds and binds nonce, PID, session, bridge hash, approved
GameAssembly hash, exact class and current-page checkpoint. Full unique window ownership
is rechecked at native boundaries. The cache does not grant capture permission. The helper
reads `stage-state.json` and refuses out-of-order/completed/terminal stages; in-process
policy independently enforces this. Reading a partially written status fails closed: retry
only the helper/status read, not a consumed native stage.

Budgets are cooperative, not real-time preemption of a native call or first JIT. Results
include actual elapsed, stopped stage and **reserved** NativeOperations (not exact calls).
Cleanup is mandatory outside the sampling cap: up to64 root frees, before module release.
`no_eligible_text`, `bounded_no_text`, budget and `backend_failure` are distinct; none means
that the game contains no data. Only a nonempty returned text is an actual field result.

## Authorized one-shot recorded Mac name-path experiment

Only the global capture depth limit and maximum focus-edge count change from12 to16.
For the specifically authorized player-profile test, the source-recorded Mac selector
is `panel0/0/3/0/0/0/0/2/0/1/0/0/0/2/0`: panel0 plus14 child edges, so the relative
focus is `0/3/0/0/0/0/2/0/1/0/0/0/2/0`. This comes from
`modules/data-core/src/football_assistant_data/display_profile.py`'s name selector;
that rule is pinned to historical Mac build27.0.0+2486695, not verified Windows layout.
If the current path is absent/hidden, stop; do not substitute another path or retry.

The250ms soft cap,384 reserved units,node32,subtree first8 children,root64,one panel,
one text and128 UTF-16 units are unchanged. Ancestors still consume those shared limits;
depth is global, never reset at the focus target. No new type checks/native APIs are added.
The fake-native exact14-edge test asserts302 reserved units,49 roots,15 nodes and332
fresh guard calls after explicit warm-up. These are synthetic fixture counts, not measured
game timing or a guarantee about Windows inheritance/method lookup costs; CI must pass
the exact assertions before the real test. No extra allowance is granted if it does not fit.

### Earlier panel4 / depth12 capture experiment

That earlier authorized experiment changed only the candidate capture depth limit from
8 to 12 (root depth is 0; depth12 is eligible, depth13 is pruned). It selects exactly
panel index4 through the existing immutable one-shot request/grant, with no fallback
or iteration over other panels. For this test, invoke the helper with explicit `-Stage ui_text -PanelIndex 4`;
the backwards-compatible default panel index remains0, not an authorization to test it.
The 250ms soft elapsed cap, 384 reserved units, 32 nodes, first8 children per node,
64 temporary roots, 128 UTF-16 units and every fresh ownership/grant check are unchanged.
Resolve-only warm-up remains250ms/2048 units. Diagnostics and terminal one-shot behavior
remain enabled. No automatic retry is introduced; root coordinates the single authorized
test after review and CI. This does not promise text: operation/root/time caps can still
stop before a deeper node is reached, and panel order has no semantic screen guarantee.

### Earlier one-shot 250ms capture experiment

In that earlier explicitly authorized experiment, only the capture soft elapsed cap changed
from 100 to 250ms. The 384 reserved-unit limit, one panel, 32 nodes, depth8,
8 children/node, 64 temporary roots, 128 UTF-16 units and every fresh ownership/grant
check remain unchanged. Resolve-only warm-up remains 250ms/2048 units. Diagnostics
remain enabled. A consumed capture is still terminal; no automatic retry or additional
restart is authorized by this revision.

This may briefly stall the game main thread. The limit is cooperative, not preemptive:
an individual native call, JIT or mandatory cleanup can make wall time exceed 250ms.
The unchanged operation/root/traversal limits may stop the attempt before a text getter;
this experiment does not promise text or improved performance. Review its one result
before deciding on any further experiment.

### Earlier budget history

The first real staged attempt resolved metadata/classes successfully, then capture stopped
at `text_type`: 25.5497ms, 38 reserved operations, root resolved, no text getter success.
An earlier revision changed the capture soft elapsed cap from25 to100ms for first-use/JIT costs
and reserved native-boundary units from128 to384 for the already bounded depth8 path.
Before the later type-first optimization, cache-hit visible/bounds/type checks cost16 reserved units, child count7 and descent4:
about27 per non-text ancestor/edge, then about24 for a text leaf, plus initial panel and
cold method lookup. Thus128 was not enough for a depth8 diagnostic. The384 cap is not
a promise of32 nodes: the independent64-root cap can stop earlier. Root/node/depth/
children/panel/string limits stayed unchanged in that earlier revision. The
failed session remains terminal; deploy only through the coordinated normal restart and
new session/three requests. No automatic retry is introduced.

A returned text is **real UI component text**, not guaranteed currently screen-visible text
or a business/player field. The adapter checks `visible` along the visited ancestor path
and positive finite `worldBound` for the text node; it does not establish resolved display,
viewport intersection, ancestor clipping or occlusion.

## Why not invoke existing Capture wholesale?

`src/NativeUiReader.cs` constructor calls NativeLibrary.Load and binds 13 delegates; it does
not itself resolve classes. `Capture` then scans assemblies up to 1024 twice to find
UIElementsRuntimeUtility and TextElement, calls GetSortedPlayerPanels and list get_Count,
and only AFTER this begins its nominal 15ms stopwatch. The stock limits also allow 32 panels,
2500 nodes, 512 children/node and up to 240 text results, inappropriate for this smoke.

Every stock Call invokes RecordMethodProof. The first successful getter lazily binds 17
additional InspectionApi exports, including field/static-data APIs, and performs class/name/
token proof queries. Capture does not itself enumerate registries, but BridgeRuntime.Capture
calls registry/enumeration functions afterward. Therefore calling Capture then taking one
result does NOT limit work to one field and brings unnecessary inspection dependencies.

## Exact intended reuse: same getter path/semantics, not whole collector

Use the verified *existing* module lease, never NativeLibrary.Load another GameAssembly.
The final adapter requires these 16 actually used exports: the stock UI path's 13 plus
three temporary-root operations (the first two are already in metadata):

```
il2cpp_domain_get
il2cpp_domain_get_assemblies
il2cpp_assembly_get_image
il2cpp_image_get_name
il2cpp_object_get_class
il2cpp_class_get_parent
il2cpp_object_unbox
il2cpp_string_chars
il2cpp_class_from_name
il2cpp_class_get_method_from_name
il2cpp_runtime_invoke
il2cpp_string_length
il2cpp_class_is_assignable_from
il2cpp_gchandle_new
il2cpp_gchandle_get_target
il2cpp_gchandle_free
```

Exact managed targets/getters to verify from runtime metadata, no Mac offsets:

1. Image `UnityEngine.UIElementsModule.dll`, namespace `UnityEngine.UIElements`.
2. Types `UIElementsRuntimeUtility`, `VisualElement` and `TextElement`.
3. Static `UIElementsRuntimeUtility.GetSortedPlayerPanels()`; returned list `get_Count()`;
   only `get_Item(panelIndex)` for the authorized index on that list; panel `get_visualTree()`.
4. Element `get_visible()` and `get_worldBound()`; positive finite Rect required to emit
   that node's text. Hidden ancestors prune subtrees; invalid parent bounds do NOT prove
   children are hidden. Bool, Int32 and Rect boxed payload shapes need validation before
   unbox/read; if existing basic APIs cannot establish shapes, explicitly add only the
   required metadata functions rather than blindly assuming layouts.
5. `il2cpp_class_is_assignable_from(TextElement, actualClass)` before `get_text()`.
6. `get_childCount()` and `get_Item(index)` for bounded descendants only.
7. `il2cpp_string_length` + `il2cpp_string_chars`, at most 128 UTF-16 code units, avoid
   ending a surrogate pair mid-character. No unbounded PtrToStringUTF8 for image names:
   bound native name scanning and method-parent depth explicitly in the future adapter.

No ReadApplicationVersion, RecordMethodProof, widget inventory, field lookup, registry,
observer, packet, network publisher or broad runtime reflection in this adapter.

## Budget and outcomes

Both staged operations start their stopwatch BEFORE their work. Every native export/invoke/
memory read in the adapter calls BeforeNative (not once around a multi-call method).
It caps one panel, 32 nodes, depth 16, 8 children/node, one text of 128 code units; lazy DFS
obtains one child at a time rather than eagerly fetching all siblings. Capture
budget is 250ms soft elapsed / 384 reserved native boundary units, explicitly a conservative experiment,
not proof that cold resolution will fit. Results record elapsed, stopped stage, operation/
node count, root-resolution and text-getter success. `no_eligible_text`/`bounded_no_text`/
`time_budget` are NOT real fields and not evidence the game has no data. `backend_failure`
is distinct and records exception type; native access violations are not made safe by catch.

A single native getter cannot be interrupted by a soft budget. Cold JIT can exceed the
soft limit. The explicit resolve-only warm-up is separately limited to250ms/2048 boundary
units and never automatic. Do not silently expand either budget or retry.

## Enforced experimental integration boundary

Only after actual metadata success: acquire/validate the extra required exports on the same
held module lease; create one backend privately from that lease. Consume a distinct UI grant
bound to PID/session/bridge/game hash and the newly confirmed stable page. Immediately before
capture and at each native boundary, revalidate grant expiry, cancellation and the unique
current-session UnityWndClass owner. A factory needs to enforce module hash equality; the
backend interface is NOT a security capability and no production code should accept arbitrary
implementations. Complete/revoke the active UI grant on every return/exception. Failure or
empty result is terminal for that UI attempt. Do not reconstruct the session policy.

TryReadAuthorized now consumes/revalidates a separate UI-stage policy grant and revokes it
on every return/exception; tests prove no UI before metadata success or second UI attempt.
Tests additionally bind that private adapter to fake managed export delegates and owned fixture
memory using a test-only partial that must never enter a runtime project. No host references it. The real adapter is only constructible inside the held module lease.
The standalone ReadOne traversal core cannot authorize itself. The native adapter is compiled in tests but uses only fake exports/owned buffers there; tests make zero game calls.
Run: `dotnet run --project modules/game-bridge/windows-ui-smoke-draft/UiDraftTests.csproj`.


## Implemented native thin adapter (still unactivated)

`WindowsLoadedModuleLease.Ui.cs` adds a private nested adapter and RunUiOnce on the already
held module lease. The same lease lifetime lock covers export validation, delegate binding
and the entire one-shot UI call. Extra exports are checked against the same PE/RX mapping;
no library load is performed. Neither metadata host project nor ordinary production compiles
this partial. There is no script/config/UI request path to invoke it.

The adapter uses exactly the 16 exports above. It scans the assembly list ONCE for the UI,
CoreModule and mscorlib images (count <=1024), resolves exact runtime classes for Int32,
Boolean, String and Rect, and checks returned boxed/string runtime class before payload
reads. Parent method search caps depth16. Image names are bounded to128 ASCII bytes (one
bounded memory-read operation, no unbounded marshaler); indexed arguments are stack-local
Int32 values passed through runtime_invoke. Getter exceptions stop before any later getter.
No method proof recording or Inspector API constructor is present.

Rect payload uses the same four-float sequential typed ABI as the existing reader, not a
Mac field offset. Unity's official public source documents `[StructLayout(LayoutKind.Sequential)]`
and x/y/width/height float fields:
https://github.com/Unity-Technologies/UnityCsReference/blob/master/Runtime/Export/Geometry/Rect.cs
The actual Windows build/getter path still needs runtime evidence before claiming correctness.

All export calls, array/payload copies and bounded string scans consume the explicit budget
and revalidate the active grant/window before proceeding. Class/method resolution uses the
separate explicitly authorized 250ms/2048 warm-up. First JIT and native call duration can
exceed a soft deadline; actual elapsed and the stopping stage are recorded, never retried.

NativeUiAdapterFixture exercises the actual adapter against managed fake export delegates
and its own allocated buffers: exact allowlisted getter sequence, one text, boxed-type mismatch
rejection and getter-exception stop. Test-only factory is isolated in NativeUiAdapter.TestHooks.cs;
no future runtime project may include that file or NativeUiAdapterFixture.cs.


## Temporary-object lifetime and cleanup

CoreCLR closures/collections are NOT IL2CPP GC roots. Every non-null runtime_invoke result
(list, panel, visual element, boxed primitive/Rect, string) gets a strong non-pinned root
immediately on return. Invoke/new/get_target budget slots and window checks are reserved
BEFORE invoke; between the returned raw pointer and gchandle_new there is no window scan,
CoreCLR closure allocation, diagnostic formatting or budget exception. The returned handle
is immediately retained in a preallocated64-entry array, then get_target must equal the
original pointer. No unrooted boxed/string return is carried across later gate work.

Declarations use pointer-sized nuint for modern GC handles and explicitly I1 for C++ bool
pinned=false, never default4-byte BOOL marshalling or legacyuint truncation. The Windows
build's pointer-width return/input and byte pinned argument were separately confirmed by
private, read-only static disassembly through the allocator return; no game bytes are
included here. Fake high32-handle tests alone do not prove that ABI. Upstream Il2CppInterop also declares pointer-sized handles and I1 pinned:
https://github.com/BepInEx/Il2CppInterop/blob/master/Il2CppInterop.Runtime/IL2CPP.cs
Unity6.3 documents its Boehm non-compacting collector (no object relocation); strong roots
retain these objects while pointer values are stored in the bounded traversal:
https://docs.unity.cn/6000.3/Documentation/Manual/performance-incremental-garbage-collection.html

RunUiOnce holds the module lease lifetime lock and uses deterministic adapter disposal on
success, empty result, exception, cancellation and budget expiry. Every retained root gets
one free attempt before the lease lock is released. Cleanup ignores the sampling budget and
cancel/window gate: those must not strand roots. At most64 cleanup calls are possible; they
are separate from reserved sampling-operation accounting. If one managed cleanup call fails,
remaining frees are still attempted and cleanup failure is surfaced, never reported as a
clean field success. No finalizer/background-game-call cleanup is used.

Actual adapter fixtures now require a live fake root before object_class, unbox, string
access or invoking an instance getter. High32-bit fake handles roundtrip and all are freed
on success, boxed-type error and exhausted-budget exit. This simulates lifetime rules but
NOT a real IL2CPP GC stress run. Independent candidate remains undeployed pending staged review and explicit requests.


## Bounded numeric coverage diagnostics

`Coverage` supplements timing without additional exports, getters, object-class reads or
fresh guard checks. Storage for 32 node slots is allocated before obtaining runtime objects.
`PanelCount` is copied only after the existing count getter/unbox/read passes its 0..1024
validation. `-1` means unknown/not read/invalid, **not** an empty list; `0` means an actual
validated empty list. `RequestedPanelIndex` is the immutable authorized request index (default 0).
`SelectedPanelIndex` stays `-1` until the validated list contains that index, then records
that planned index, not proof that its item/root was successfully obtained.
Neither multiple panels nor diagnostic incompleteness authorizes a fallback/retry.

`NodesRecorded` marks the populated prefix of the fixed 32-slot `Nodes` array. Unused
slots have `Depth = -1`; populated depths are 0..16. Numeric states are:

- `Visibility` and `TextType`: 0 not started, 1 incomplete, 2 false, 3 true.
- `ChildCountState`: 0 not started, 1 incomplete, 2 completed.
- `ChildCountBucket`: -1 unknown, 0..8 exact, 9 means greater than 8.
- `DepthPruned` and `ChildrenTruncated`: 0/1 flags from the already-read child count.

A budget/exception during a check leaves it incomplete; this is not a negative type or
visibility result. No text, class names, paths, native pointers or object identities are
included. All limits and terminal one-shot behavior stay unchanged. Timing still includes
diagnostic work up to its existing endpoint; no overhead is subtracted from the budget.

Offline fixtures cover a derived-text class with asymmetric assignability, text solely in
a second panel, reachable depth9/depth12/depth16 text, depth17 and child-index8 omissions, validated-zero versus unknown panel
counts, partial checks, and unchanged reservation/fresh-guard counts. CI additionally runs
`test_assignability_mutation.py` after normal tests: it swaps the arguments in a temporary
source copy and requires failure at the derived-text assertion, not an unrelated build
error. This is a fake-export test, not evidence about the current game's panel contents.


## Explicit single-panel selection

The request schema accepts an optional `panel_index`, a canonical JSON integer 0..31.
Omission defaults to 0; fractions, exponent notation, strings, negatives, out-of-range
values and duplicate fields are rejected. Nonzero selection is invalid for metadata or
resolve requests. The helper permits explicit `-PanelIndex` only with `-Stage ui_text`,
and emits the field only when that argument was supplied. No environment/config panel
override is consulted.

The immutable request index is copied into `SmokeGrant`; grant identity/equality and
ongoing revalidation bind it. Capture uses the consumed grant, not a later request-file
poll. Replacing the request or replaying its nonce cannot redirect or repeat capture.
The adapter reads the panel count once, validates it, then checks index < count before
fetching exactly one item. A missing requested index produces `panel_index_unavailable`
(or `root_unavailable` for an empty list), consumes the only capture, and never falls
back to another index. All budgets, native gates, GC handling and traversal limits stay
unchanged. This feature does not authorize a run or any additional session/restart.

Default requests remain compatible with the earlier schema-1 reader because the helper
omits the new field. Explicit selection requires the updated candidate: an old strict
reader rejects the added field rather than silently treating it as panel 0. Legacy
`resolve_first_panel` / `first_panel_root` timing labels are retained for existing
consumers; use Coverage.RequestedPanelIndex / SelectedPanelIndex to identify selection.

Panel indices refer to the runtime's current sorted list, not stable semantic names.
Rendering/creation order does not identify the main menu, active page or meaningful
business content, and may change between sessions or requests. Selecting an index does
not prove that panel is currently on screen, foreground, or relevant. No automatic
multi-panel search, rotation, index increment, fallback or repeat is implemented.



## Explicit focused-subtree infrastructure

This capability does **not** authorize a new game read, guessed path, automatic retry,
or an expanded scan. Obtain evidence and explicit authorization for the exact panel/path
before a real test. The single authorized recorded name-path experiment above does not
authorize any other path, fallback or repeated capture.

Optional request `focus_path` is an immutable canonical string of child indices relative
to the separately bound `panel_index`: empty means the original panel-root traversal;
otherwise at most16 slash-separated ASCII decimal indices0..511, no leading zeroes,
signs, spaces, empty segments or panel token. Nonempty focus is ui_text-only.
The helper accepts `-FocusPath` only for ui_text (even an explicit empty argument);
omission writes no new field. Earlier strict readers reject explicit new fields rather
than silently ignoring focus. Request schema stays1; output Coverage schema becomes2.

Each focus ancestor uses the existing protected backend: visible, actual child count,
then exactly one selected child. No loop up to that index, sibling prefetch, alternate
panel or fallback is performed. An explicitly selected child8..511 can be reached;
this is distinct from the unchanged first8-child enumeration within the selected subtree.
Actual child count must contain the index; negative counts still fail closed. There is
no new arbitrary upper child-count limit or relaxation of a pre-existing one.

Ancestors consume the same32 nodes, 250ms soft time, 384 reserved units and64 roots.
Depth remains global from the panel root: a16-edge focus starts its target at depth16,
so no descendant at depth17 is fetched. Ancestor text is intentionally not read: focus
selects the subtree, not the ancestors' text. Hidden ancestors stop; there is no fallback.
The target uses the unchanged text type/bounds/getter rules. Empty focus preserves the
original native call/guard sequence and traversal order.

Coverage remains32 preallocated numeric slots. New `ParentSlot` and `ChildIndex` describe
the edge used to reach each visited node; root/unused slots use-1/-1. Parents precede
children, even when DFS returns to siblings. `FocusAncestor=1` identifies explicit
descent ancestors, whose TextType stays0 (not checked). Their child-count bucket still
describes the existing read, but ChildrenTruncated stays0 because no sibling enumeration
was attempted. Standard subtree nodes retain the original width/depth pruning flags.
`RequestedFocusDepth` is0 for empty,1..16 for valid focus,-1 for invalid direct-core
input. `FocusResolved=1` means the nonempty path reached a nonnull target, not that the
target was visible or text; empty/unresolved focus reports0. `RootResolved` still means
the panel root was obtained. Partial checks remain incomplete; no text, names, addresses
or raw request paths are included in coverage. No native call is added for these fields.

Malformed focus is rejected by parser/policy before any grant is consumed;
focus_path_invalid is the direct-core validation result. Runtime outcomes after a valid
grant is consumed include focus_ancestor_hidden, focus_child_unavailable and
focus_root_unavailable; budget/backend failures remain possible. Those runtime outcomes
are terminal and never restore the capture attempt.
Tests cover strict parsing, immutable grant/replay/replacement, child511/count512,
hidden/out-of-range ancestors, globaldepth16, node32, partial states, default call counts,
numeric DFS edges and native-fixture cleanup on both success and failure.

