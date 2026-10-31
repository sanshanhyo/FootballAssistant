using System.Diagnostics;
using System.Runtime.InteropServices;

namespace FootballAssistant.GameBridge;

// Called only by BepInEx's main-thread callback. No field offsets, game state writes,
// MonoBehaviour injection, process attachment, hidden attribute queries or UI actions.
internal sealed partial class NativeUiReader : IDisposable
{
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint DomainGet();
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint AssembliesGet(nint domain, out nuint count);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint PointerGet(nint value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint ClassGet(nint image, [MarshalAs(UnmanagedType.LPUTF8Str)] string ns, [MarshalAs(UnmanagedType.LPUTF8Str)] string name);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint MethodGet(nint type, [MarshalAs(UnmanagedType.LPUTF8Str)] string name, int parameterCount);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate nint RuntimeInvoke(nint method, nint instance, nint arguments, out nint exception);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] private delegate int StringLength(nint value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] [return: MarshalAs(UnmanagedType.I1)] private delegate bool Assignable(nint parent, nint child);

    private readonly nint library;
    private readonly DomainGet domainGet;
    private readonly AssembliesGet assembliesGet;
    private readonly PointerGet assemblyImage, imageName, objectClass, classParent, unbox, stringChars;
    private readonly ClassGet classGet;
    private readonly MethodGet methodGet;
    private readonly RuntimeInvoke invoke;
    private readonly StringLength stringLength;
    private readonly Assignable assignable;
    private readonly Dictionary<(nint, string, int), nint> methods = new();
    private nint runtimeUtility, textElement;

    public NativeUiReader(string gameAssembly)
    {
        // Probe candidate: even an accidental future call site cannot bind/read Windows game APIs.
        if (OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows native UI reads are disabled in the scheduler probe candidate.");
        // At plugin load the game has already loaded this exact GameAssembly.
        // dlopen/LoadLibrary adds a reference to it; this is never used by an offline tool.
        library = NativeLibrary.Load(gameAssembly);
        domainGet = Bind<DomainGet>("il2cpp_domain_get");
        assembliesGet = Bind<AssembliesGet>("il2cpp_domain_get_assemblies");
        assemblyImage = Bind<PointerGet>("il2cpp_assembly_get_image");
        imageName = Bind<PointerGet>("il2cpp_image_get_name");
        objectClass = Bind<PointerGet>("il2cpp_object_get_class");
        classParent = Bind<PointerGet>("il2cpp_class_get_parent");
        unbox = Bind<PointerGet>("il2cpp_object_unbox");
        stringChars = Bind<PointerGet>("il2cpp_string_chars");
        classGet = Bind<ClassGet>("il2cpp_class_from_name");
        methodGet = Bind<MethodGet>("il2cpp_class_get_method_from_name");
        invoke = Bind<RuntimeInvoke>("il2cpp_runtime_invoke");
        stringLength = Bind<StringLength>("il2cpp_string_length");
        assignable = Bind<Assignable>("il2cpp_class_is_assignable_from");
    }

    private T Bind<T>(string name) where T : Delegate => Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library, name));

    private nint FindClass(string assembly, string ns, string name)
    {
        var assemblies = assembliesGet(domainGet(), out var count);
        if (assemblies == 0 || count > 1024) throw new InvalidOperationException("IL2CPP assembly list unavailable.");
        for (nuint i = 0; i < count; i++)
        {
            var image = assemblyImage(Marshal.ReadIntPtr(assemblies, checked((int)i * IntPtr.Size)));
            if (Marshal.PtrToStringUTF8(imageName(image)) == assembly)
            {
                var type = classGet(image, ns, name);
                if (type != 0) return type;
            }
        }
        throw new NotSupportedException("Required UI type unavailable.");
    }

    private nint Method(nint type, string name, int count = 0)
    {
        if (methods.TryGetValue((type, name, count), out var found)) return found;
        for (var current = type; current != 0; current = classParent(current))
        {
            found = methodGet(current, name, count);
            if (found == 0) continue;
            methods[(type, name, count)] = found;
            return found;
        }
        throw new NotSupportedException("Required read-only UI getter unavailable.");
    }

    private nint Call(nint type, nint instance, string method, nint arguments = default, int argumentCount = 0)
    {
        var methodInfo = Method(type, method, argumentCount);
        var result = invoke(methodInfo, instance, arguments, out var exception);
        if (exception != 0) throw new InvalidOperationException("IL2CPP getter returned an exception.");
        RecordMethodProof(methodInfo, instance == 0 ? "existing-runtime-static-ui" : "existing-ui-object");
        return result;
    }

    private nint Get(nint instance, string name) => Call(objectClass(instance), instance, name);
    private int Number(nint boxed) => boxed == 0 ? 0 : Marshal.ReadInt32(unbox(boxed));
    private bool Boolean(nint boxed) => boxed != 0 && Marshal.ReadByte(unbox(boxed)) != 0;
    private string Text(nint value)
    {
        if (value == 0) return "";
        var length = stringLength(value);
        if (length is < 0 or > 4_000_000) throw new InvalidOperationException("Invalid IL2CPP string length.");
        return Marshal.PtrToStringUni(stringChars(value), Math.Min(length, 4000)) ?? "";
    }

    private unsafe nint At(nint instance, int index)
    {
        nint* arguments = stackalloc nint[1];
        arguments[0] = (nint)(&index);
        return Call(objectClass(instance), instance, "get_Item", (nint)arguments, 1);
    }

    private UiTraversalEligibility ReadEligibility(nint element, UiPanelDiagnostics diagnostics)
    {
        var visibleFlag = Boolean(Get(element, "get_visible"));
        if (!visibleFlag) { diagnostics.visibility_false++; return new(false, null); }
        var rect = Get(element, "get_worldBound");
        if (rect == 0)
        {
            diagnostics.invalid_or_empty_bounds++;
            return new(true, false);
        }
        var values = new float[4];
        Marshal.Copy(unbox(rect), values, 0, values.Length);
        var boundsValid = values.All(float.IsFinite) && values[2] > 0 && values[3] > 0;
        if (!boundsValid) diagnostics.invalid_or_empty_bounds++;
        return new(true, boundsValid);
    }

    public IReadOnlyList<UiText> Capture(UiCaptureSelection? selection = null)
    {
        methodProofsThisFrame.Clear();
        fieldProofsThisFrame.Clear();
        var output = new UiCapture();
        var requestedFocus = selection?.FocusPath ?? Environment.GetEnvironmentVariable(UiFocusPath.EnvironmentVariable);
        UiFocusPath? focus = null;
        output.FocusRequested = requestedFocus is not null;
        if (requestedFocus is not null)
        {
            if (!UiFocusPath.TryParse(requestedFocus, out focus)) { output.StopReason = "invalid_focus_path"; return output; }
            output.FocusRootPath = focus!.Path; // Only canonical numeric paths enter diagnostics.
        }
        if (focus is not null && (selection?.WidgetDiagnostics ?? (Environment.GetEnvironmentVariable(UiWidgetInventory.EnvironmentVariable) == "1")))
            output.WidgetInventory = new UiWidgetInventory();
        if (domainGet() == 0) { output.StopReason = "domain_unavailable"; return output; }
        runtimeUtility = runtimeUtility == 0 ? FindClass("UnityEngine.UIElementsModule.dll", "UnityEngine.UIElements", "UIElementsRuntimeUtility") : runtimeUtility;
        textElement = textElement == 0 ? FindClass("UnityEngine.UIElementsModule.dll", "UnityEngine.UIElements", "TextElement") : textElement;
        var panels = Call(runtimeUtility, 0, "GetSortedPlayerPanels");
        if (panels == 0) { output.StopReason = "panels_unavailable"; return output; }
        output.PanelsAvailable = Number(Get(panels, "get_Count"));
        var count = Math.Clamp(output.PanelsAvailable, 0, 32);
        var budget = Stopwatch.StartNew();
        var visited = 0;
        void ObserveWidget(nint type, string path, string phase, bool supported, bool visibleFlag, bool? boundsValid, int? childCount)
        {
            var inventory = output.WidgetInventory;
            if (inventory is null) return;
            if (budget.Elapsed.TotalMilliseconds > 15) { inventory.BudgetSkippedNodes++; return; }
            inventory.Observe(type, path, phase, supported, visibleFlag, boundsValid, childCount,
                value => { var identity = Identity(value); return (identity.Namespace, identity.Name); });
        }
        string? Limit() => budget.Elapsed.TotalMilliseconds > 15 ? "time_budget" :
            visited >= 2500 ? "node_limit" : output.Count >= UiTraversalBounds.MaximumTexts ? "text_limit" : null;
        if (focus is not null && focus.PanelIndex >= count)
        {
            output.StopReason = "focus_panel_unavailable";
            output.ElapsedMs = Math.Round(budget.Elapsed.TotalMilliseconds, 3);
            return output;
        }
        var firstPanel = focus?.PanelIndex ?? 0;
        var endPanel = focus is null ? count : firstPanel + 1;
        for (var panelIndex = firstPanel; panelIndex < endPanel; panelIndex++)
        {
            var limit = Limit();
            if (limit is not null) { output.StopReason = limit; break; }
            var diagnostics = new UiPanelDiagnostics { panel_index = panelIndex };
            output.Panels.Add(diagnostics);
            var panelStart = budget.Elapsed.TotalMilliseconds;
            var panel = At(panels, panelIndex);
            var root = panel == 0 ? 0 : Get(panel, "get_visualTree");
            if (focus is not null)
            {
                string ancestorPath = "";
                if (!focus.TryResolve(root, Limit, element => {
                    var eligibility = ReadEligibility(element, diagnostics);
                    if (eligibility.CanReadText) diagnostics.visible_nodes++;
                    else if (eligibility.CanDescend) diagnostics.text_ineligible_bounds_nodes++;
                    var ancestorDepth = output.FocusDescentNodes - 1;
                    ancestorPath = $"panel{panelIndex}" + string.Concat(focus.ChildIndices.Take(ancestorDepth).Select(index => $"/{index}"));
                    if (!eligibility.CanReadText && output.WidgetInventory is not null)
                    {
                        if (Limit() is null)
                        {
                            var ancestorType = objectClass(element);
                            ObserveWidget(ancestorType, ancestorPath, "focus_descent", assignable(textElement, ancestorType), eligibility.Visible, eligibility.BoundsValid, null);
                        }
                        else output.WidgetInventory.BudgetSkippedNodes++;
                    }
                    return eligibility.CanDescend;
                },
                    element => {
                        var childCount = Number(Get(element, "get_childCount"));
                        output.WidgetInventory?.UpdateChildCount(ancestorPath, "focus_descent", childCount);
                        return childCount;
                    }, At,
                    () => { visited++; diagnostics.visited_nodes++; output.FocusDescentNodes++; },
                    out root, out var focusReason))
                {
                    diagnostics.stop_reason = output.StopReason = focusReason;
                    diagnostics.elapsed_ms = Math.Round(budget.Elapsed.TotalMilliseconds - panelStart, 3);
                    break;
                }
                output.FocusResolved = true;
            }
            if (root == 0) { diagnostics.stop_reason = "root_unavailable"; diagnostics.elapsed_ms = budget.Elapsed.TotalMilliseconds - panelStart; continue; }
            var stack = new Stack<(nint Element, string Path, int Depth)>();
            stack.Push((root, UiTraversalBounds.CaptureRootPath(panelIndex, focus), 0));
            while (stack.Count > 0)
            {
                limit = Limit();
                if (limit is not null) { diagnostics.stop_reason = output.StopReason = limit; break; }
                var (element, path, depth) = stack.Pop();
                visited++;
                diagnostics.visited_nodes++;
                if (element == 0) continue;
                var eligibility = ReadEligibility(element, diagnostics);
                if (!eligibility.CanDescend)
                {
                    if (output.WidgetInventory is not null)
                    {
                        if (Limit() is null)
                        {
                            var prunedType = objectClass(element);
                            ObserveWidget(prunedType, path, "focused_subtree", assignable(textElement, prunedType), eligibility.Visible, eligibility.BoundsValid, null);
                        }
                        else output.WidgetInventory.BudgetSkippedNodes++;
                    }
                    continue; // Hidden ancestors remain conservatively pruned.
                }
                if (eligibility.CanReadText) diagnostics.visible_nodes++;
                else diagnostics.text_ineligible_bounds_nodes++;
                limit = Limit();
                if (limit is not null) { diagnostics.stop_reason = output.StopReason = limit; break; }
                var type = objectClass(element);
                var supported = assignable(textElement, type);
                if (supported) diagnostics.text_element_nodes++;
                else diagnostics.other_widget_nodes++;
                if (supported && eligibility.CanReadText)
                {
                    limit = Limit();
                    if (limit is not null) { diagnostics.stop_reason = output.StopReason = limit; break; }
                    var text = Text(Get(element, "get_text")).Trim();
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        output.Add(new UiText(path, text[..Math.Min(text.Length, 1000)]));
                        diagnostics.emitted_texts++;
                    }
                    else diagnostics.empty_text_nodes++;
                }
                // Bounds exclude only this node's text, never infer child bounds.
                limit = Limit();
                if (limit is not null) { diagnostics.stop_reason = output.StopReason = limit; break; }
                var childCount = Number(Get(element, "get_childCount"));
                ObserveWidget(type, path, "focused_subtree", supported, eligibility.Visible, eligibility.BoundsValid, childCount);
                var children = Math.Clamp(childCount, 0, 512);
                diagnostics.child_limit_skipped += Math.Max(0, childCount - children);
                for (var childIndex = children - 1; childIndex >= 0; childIndex--)
                {
                    limit = Limit();
                    if (limit is not null || stack.Count >= 2500)
                    {
                        diagnostics.stop_reason = output.StopReason = limit ?? "stack_limit";
                        // These children have not been obtained or traversed.
                        diagnostics.pending_nodes += childIndex + 1;
                        break;
                    }
                    if (!UiTraversalBounds.TryChildPath(path, depth, childIndex, diagnostics, out var childPath)) continue;
                    stack.Push((At(element, childIndex), childPath, depth + 1));
                }
                if (diagnostics.stop_reason != "complete") break;
            }
            diagnostics.pending_nodes += stack.Count;
            diagnostics.elapsed_ms = Math.Round(budget.Elapsed.TotalMilliseconds - panelStart, 3);
            if (output.StopReason != "complete") break;
        }
        if (focus is null && output.StopReason == "complete" && output.PanelsAvailable > 32) output.StopReason = "panel_limit";
        output.ElapsedMs = Math.Round(budget.Elapsed.TotalMilliseconds, 3);
        return output;
    }

    public string? ReadApplicationVersion()
    {
        var application = FindClass("UnityEngine.CoreModule.dll", "UnityEngine", "Application");
        var value = Text(Call(application, 0, "get_version"));
        return string.IsNullOrWhiteSpace(value) ? null : value;
    }

    public void Dispose() => NativeLibrary.Free(library);
}
