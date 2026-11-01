using System.Reflection;

// Reflection only: never calls Start, opens a game process or loads native game code.
var assembly = typeof(Doorstop.Entrypoint).Assembly;
if (assembly.GetName().Name != "FootballAssistant.GameBridge") throw new Exception("Unexpected entry assembly");
var references = assembly.GetReferencedAssemblies();
if (references.Any(reference => reference.Name!.StartsWith("BepInEx") || reference.Name.StartsWith("Il2CppInterop"))) throw new Exception("Direct host still depends on optional compatibility core");
if (assembly.GetType("FootballAssistant.GameBridge.Plugin") != null) throw new Exception("Optional BepInEx Plugin was not excluded");
if (typeof(Doorstop.Entrypoint).GetMethod("Start", BindingFlags.Public | BindingFlags.Static) == null) throw new Exception("Doorstop Start entry missing");
if (typeof(Doorstop.Entrypoint).GetMethod("Stop", BindingFlags.Public | BindingFlags.Static) == null) throw new Exception("Doorstop Stop entry missing");
Console.WriteLine("Direct host metadata valid; optional BepInEx dependencies absent; game/native entry not invoked.");
