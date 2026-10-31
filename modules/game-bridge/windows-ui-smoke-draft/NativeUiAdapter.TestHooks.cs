namespace FootballAssistant.GameBridge;

// Included ONLY in UiDraftTests.csproj. Never include this in a candidate/runtime project.
internal sealed partial class WindowsLoadedModuleLease
{
    internal static IWindowsUiSmokeBackend CreateUiTestBackend(string hash, Func<string, Type, Delegate> binder) =>
        new NativeUiBackend(hash, binder);
    internal static void PrepareUiTestBackend(IWindowsUiSmokeBackend backend, UiSmokeBudget budget) =>
        ((NativeUiBackend)backend).PrepareTypesAndMethods(budget);
}
