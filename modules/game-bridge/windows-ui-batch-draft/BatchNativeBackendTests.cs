using System.Linq.Expressions;
using System.Runtime.InteropServices;
using FootballAssistant.GameBridge;

// Synthetic owned buffers/delegates only. Not a game runtime or native ABI acceptance test.
internal static class BatchNativeBackendTests
{
    private static void Check(bool value, string message)
    { if (!value) throw new Exception("Batch backend: " + message); }
    private static UiSmokeBudget Budget(Action? guard = null) => new(() => 0, guard ?? (() => { }), 750, 10000);
    private static string Hash => new('b', 64);

    internal static void Run()
    {
        foreach (var depth in new[] { 21, 32 })
        {
            using var fixture = new NativeUiAdapterFixture { TextDepth = depth, FocusEdges = Enumerable.Repeat(0, depth).ToArray() };
            var trace = new ExportTrace(fixture);
            using var backend = new BatchNativeBackend(Hash, trace.Bind);
            var budget = Budget(() => trace.Events.Add("guard"));
            backend.Prepare(budget);
            var prepareCost = budget.Operations;
            BatchObject? current = backend.OpenPanel(0, budget);
            Check(current is not null, "synthetic panel exists");
            try
            {
                for (var d = 0; d < depth; d++)
                {
                    Check(backend.Visible(current!, budget), "ancestor visible");
                    Check(backend.ChildCount(current!, budget) == 1, "ancestor count");
                    var child = backend.Child(current!, 0, budget);
                    current!.Dispose(); // Only AFTER the returned child has its own strong root.
                    current = child;
                    Check(backend.LiveRoots == 1 && fixture.LiveRoots == 1, "only current node retained after direct descent");
                }
                Check(backend.Visible(current!, budget) && backend.IsTextElement(current!, budget) &&
                    backend.Bounds(current!, budget).PositiveFinite && backend.ReadText(current!, 128, budget) == "fixture-native-path",
                    "deep synthetic text returns through protected typed adapter");
                Check(prepareCost == 27 && budget.Operations == 27 + 21 + depth * 18 + 3 + 26,
                    "source-derived native reservation cost includes prepare, ancestors and text");
                Check(backend.TotalAllocated == 4 + depth * 3 + 3 && backend.PeakLiveRoots == 3 && backend.LiveRoots == 1,
                    "scoped roots separate cumulative creation from peak live capacity");
                Console.WriteLine($"Batch scoped depth{depth}: operations={budget.Operations}, allocated={backend.TotalAllocated}, peak_live={backend.PeakLiveRoots}; fake exports only.");
            }
            finally { current?.Dispose(); }
            backend.Dispose();
            Check(backend.LiveRoots == 0 && fixture.LiveRoots == 0 && backend.TotalAllocated == backend.TotalFreed,
                "deep request fully cleaned");
            for (var i = 0; i < trace.Events.Count; i++)
                if (trace.Events[i] == "il2cpp_runtime_invoke")
                    Check(trace.Events[i + 1] == "il2cpp_gchandle_new" && trace.Events[i + 2] == "il2cpp_gchandle_get_target",
                        "no extra export or fresh guard between invoke and root acquisition");
        }

        using (var fixture = new NativeUiAdapterFixture())
        {
            var trace = new ExportTrace(fixture) { StringLengthOverride = 129 };
            using var backend = new BatchNativeBackend(Hash, trace.Bind);
            var budget = Budget(); backend.Prepare(budget);
            using var root = backend.OpenPanel(0, budget)!;
            using var child = backend.Child(root, 0, budget)!;
            var rejected = false;
            try { backend.ReadAnchorText(child, budget); } catch (InvalidOperationException) { rejected = true; }
            Check(rejected && !trace.Events.Contains("il2cpp_string_chars") && backend.LiveRoots == 2,
                "long anchor fails before text copy; complete digest cannot be a128-character prefix");
            trace.StringLengthOverride = null;
            Check(backend.ReadAnchorText(child, budget) == "fixture-native-path" && backend.LiveRoots == 2,
                "bounded complete anchor succeeds and releases string root");
        }

        foreach (var sample in new[] { "\ud800", "\udc00", "\ud800A", "\ud83d\ude00" })
        {
            var ownedChars = Marshal.StringToHGlobalUni(sample);
            try
            {
                using var fixture = new NativeUiAdapterFixture();
                var trace = new ExportTrace(fixture) { StringLengthOverride = sample.Length, StringCharsOverride = ownedChars };
                using var backend = new BatchNativeBackend(Hash, trace.Bind);
                var budget = Budget(); backend.Prepare(budget);
                using var root = backend.OpenPanel(0, budget)!;
                using var child = backend.Child(root, 0, budget)!;
                var rejected = false;
                string? actual = null;
                try { actual = backend.ReadAnchorText(child, budget); } catch (InvalidOperationException) { rejected = true; }
                Check((sample == "\ud83d\ude00" ? !rejected && actual == sample : rejected) && backend.LiveRoots == 2,
                    "strict anchor accepts complete surrogate pairs, rejects malformed UTF-16, always releases string root");
            }
            finally { Marshal.FreeHGlobal(ownedChars); }
        }

        foreach (var count in new[] { 0, -1, 1025 })
        {
            using var fixture = new NativeUiAdapterFixture { PanelCount = count };
            using var backend = new BatchNativeBackend(Hash, fixture.Bind);
            var budget = Budget(); backend.Prepare(budget);
            var rejected = false;
            try { Check(backend.OpenPanel(0, budget) is null, "zero panels return no root"); }
            catch (InvalidOperationException) { rejected = true; }
            Check((count == 0 ? !rejected : rejected) && backend.LiveRoots == 0 && fixture.LiveRoots == 0 &&
                fixture.PanelIndices.Count == 0, "empty/invalid panel counts clean temporary boxes/list before returning");
        }
        using (var firstFixture = new NativeUiAdapterFixture())
        using (var secondFixture = new NativeUiAdapterFixture())
        using (var first = new BatchNativeBackend(Hash, firstFixture.Bind))
        using (var second = new BatchNativeBackend(Hash, secondFixture.Bind))
        {
            first.Prepare(Budget()); second.Prepare(Budget());
            using var root = first.OpenPanel(0, Budget())!;
            var rejected = false;
            try { second.Visible(root, Budget()); } catch (ObjectDisposedException) { rejected = true; }
            Check(rejected && secondFixture.Invocations.Count == 0, "foreign request object rejected before native getter");
        }

        using (var fixture = new NativeUiAdapterFixture())
        using (var backend = new BatchNativeBackend(Hash, fixture.Bind))
        {
            var budget = Budget(); backend.Prepare(budget);
            var root = backend.OpenPanel(0, budget)!;
            var stale = backend.Child(root, 0, budget)!;
            stale.Dispose();
            using var replacement = backend.Child(root, 0, budget)!;
            var refused = false;
            try { backend.Visible(stale, budget); } catch (ObjectDisposedException) { refused = true; }
            Check(refused && backend.Visible(replacement, budget), "stale token never aliases a reused slot");
            stale.Dispose(); // Idempotent old disposal must not release replacement.
            Check(backend.LiveRoots == 2, "old token cannot free replacement");
            fixture.WrongBoxType = true;
            refused = false;
            try { backend.ChildCount(root, budget); } catch (InvalidOperationException) { refused = true; }
            Check(refused && backend.LiveRoots == 2, "failed primitive type validation frees its box");
            fixture.WrongBoxType = false;
            fixture.GetterThrows = true;
            refused = false;
            try { backend.Visible(root, budget); } catch (InvalidOperationException) { refused = true; }
            Check(refused && backend.LiveRoots == 2, "exceptional invoke leaves no slot/token reservation behind");
            fixture.GetterThrows = false;
            root.Dispose();
        }

        using (var fixture = new NativeUiAdapterFixture())
        using (var backend = new BatchNativeBackend(Hash, fixture.Bind))
        {
            var budget = Budget(); backend.Prepare(budget);
            using var root = backend.OpenPanel(0, budget)!;
            var held = new List<BatchObject>();
            try
            {
                for (var i = 0; i < 63; i++) held.Add(backend.Child(root, 0, budget)!);
                var invokes = fixture.Invocations.Count;
                var stopped = false;
                try { backend.Child(root, 0, budget); } catch (UiSmokeStopped e) { stopped = e.Message == "gc_live_root_budget"; }
                Check(stopped && backend.PeakLiveRoots == 64 && fixture.Invocations.Count == invokes,
                    "live64 cap stops before another invoke");
            }
            finally { foreach (var token in held) token.Dispose(); }
        }
        using (var fixture = new NativeUiAdapterFixture())
        using (var backend = new BatchNativeBackend(Hash, fixture.Bind))
        {
            var budget = Budget(); backend.Prepare(budget);
            using var root = backend.OpenPanel(0, budget)!;
            while (backend.TotalAllocated < 512) backend.Visible(root, budget);
            var invokes = fixture.Invocations.Count;
            var stopped = false;
            try { backend.Visible(root, budget); } catch (UiSmokeStopped e) { stopped = e.Message == "gc_total_root_budget"; }
            Check(stopped && backend.TotalAllocated == 512 && backend.LiveRoots == 1 && fixture.Invocations.Count == invokes,
                "total512 cap independently limits reused slots before invoke");
        }

        // Every fresh guard in a synthetic panel/child/text operation can fail. All acquired
        // roots must still be disposed; native exports and further data reads stop normally.
        var successfulGuardCount = 0;
        using (var fixture = new NativeUiAdapterFixture())
        using (var backend = new BatchNativeBackend(Hash, fixture.Bind))
        {
            backend.Prepare(Budget());
            using var root = backend.OpenPanel(0, Budget(() => successfulGuardCount++));
            using var child = backend.Child(root!, 0, Budget(() => successfulGuardCount++));
            backend.Visible(child!, Budget(() => successfulGuardCount++));
            backend.Bounds(child!, Budget(() => successfulGuardCount++));
            backend.ReadText(child!, 128, Budget(() => successfulGuardCount++));
        }
        for (var failAt = 1; failAt <= successfulGuardCount; failAt++)
        {
            using var fixture = new NativeUiAdapterFixture();
            var backend = new BatchNativeBackend(Hash, fixture.Bind);
            backend.Prepare(Budget());
            var checks = 0;
            var budget = Budget(() => { if (++checks == failAt) throw new UiSmokeStopped("fixture_guard_failure"); });
            var stopped = false;
            try
            {
                using var root = backend.OpenPanel(0, budget);
                using var child = backend.Child(root!, 0, budget);
                backend.Visible(child!, budget); backend.Bounds(child!, budget); backend.ReadText(child!, 128, budget);
            }
            catch (UiSmokeStopped e) { stopped = e.Message == "fixture_guard_failure"; }
            finally { backend.Dispose(); }
            Check(stopped && fixture.LiveRoots == 0 && backend.TotalAllocated == backend.TotalFreed,
                "every guard interruption cleans all acquired roots");
        }

        using (var fixture = new NativeUiAdapterFixture())
        {
            var trace = new ExportTrace(fixture) { FailExportOnce = "il2cpp_gchandle_get_target" };
            using var backend = new BatchNativeBackend(Hash, trace.Bind);
            backend.Prepare(Budget());
            var stopped = false;
            try { backend.OpenPanel(0, Budget()); } catch (InvalidOperationException) { stopped = true; }
            Check(stopped && backend.TotalAllocated == 1 && backend.TotalFreed == 1 && fixture.LiveRoots == 0,
                "target-validation export failure frees the already-created root");
        }

        using (var fixture = new NativeUiAdapterFixture())
        {
            var trace = new ExportTrace(fixture) { FailFirstFree = true };
            var backend = new BatchNativeBackend(Hash, trace.Bind);
            backend.Prepare(Budget());
            var stopped = false;
            try { backend.OpenPanel(0, Budget()); } catch (InvalidOperationException) { stopped = true; }
            try { backend.Dispose(); } catch (InvalidOperationException) { }
            Check(stopped && backend.CleanupFailures == 1 && backend.LiveRoots == 0 &&
                trace.FreeAttempts == backend.TotalAllocated, "free failure marks request failed and still attempts every other root once");
            // Fixture free failed before doing native work; the one remaining root has unknown
            // native outcome to production. Never assert complete native cleanup in that case.
        }
        Console.WriteLine("PASS batch scoped backend synthetic tests; no game/native host activated.");
    }

    private sealed class ExportTrace
    {
        private readonly NativeUiAdapterFixture fixture;
        internal readonly List<string> Events = new();
        internal bool FailFirstFree;
        internal string? FailExportOnce;
        internal int? StringLengthOverride;
        internal nint? StringCharsOverride;
        internal int FreeAttempts;
        internal ExportTrace(NativeUiAdapterFixture fixture) { this.fixture = fixture; }
        public void Before(string export)
        {
            Events.Add(export);
            if (FailExportOnce == export)
            {
                FailExportOnce = null;
                throw new InvalidOperationException("Synthetic export failure.");
            }
            if (export == "il2cpp_gchandle_free" && ++FreeAttempts == 1 && FailFirstFree)
                throw new InvalidOperationException("Synthetic cleanup failure.");
        }
        public int LengthOrOriginal(int original) => StringLengthOverride ?? original;
        public nint CharsOrOriginal(nint original) => StringCharsOverride ?? original;
        internal Delegate Bind(string export, Type delegateType)
        {
            var original = fixture.Bind(export, delegateType);
            var signature = delegateType.GetMethod("Invoke")!;
            var parameters = signature.GetParameters().Select(p => Expression.Parameter(p.ParameterType, p.Name)).ToArray();
            var before = Expression.Call(Expression.Constant(this), typeof(ExportTrace).GetMethod(nameof(Before))!, Expression.Constant(export));
            Expression invoke = Expression.Invoke(Expression.Constant(original, delegateType), parameters);
            if (export == "il2cpp_string_length")
                invoke = Expression.Call(Expression.Constant(this), typeof(ExportTrace).GetMethod(nameof(LengthOrOriginal))!, invoke);
            else if (export == "il2cpp_string_chars")
                invoke = Expression.Call(Expression.Constant(this), typeof(ExportTrace).GetMethod(nameof(CharsOrOriginal))!, invoke);
            return Expression.Lambda(delegateType, Expression.Block(before, invoke), parameters).Compile();
        }
    }
}
