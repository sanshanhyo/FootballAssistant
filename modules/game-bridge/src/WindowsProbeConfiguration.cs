using System.Text.Json;

namespace FootballAssistant.GameBridge;

// One fixed adjacent opt-in file, not a generic search path or game configuration reader.
internal static class WindowsProbeConfiguration
{
    internal const string FileName = "footballassistant.windows-probe.json";
    internal const string PrivateDirectoryName = "windows-probe-private";
    private const int MaximumConfigBytes = 1024;

    internal static string ResolvePrivateRoot(string? explicitRoot, string assemblyPath)
    {
        if (!string.IsNullOrWhiteSpace(explicitRoot))
        {
            ValidateAbsoluteNonReparsePath(explicitRoot);
            return Path.GetFullPath(explicitRoot);
        }
        if (string.IsNullOrWhiteSpace(assemblyPath) || !Path.IsPathFullyQualified(assemblyPath))
            throw new InvalidOperationException("Windows probe requires a located bridge DLL or explicit private root.");
        ValidateAbsoluteNonReparsePath(assemblyPath);
        var directory = Path.GetDirectoryName(assemblyPath)!;
        var configuration = Path.Combine(directory, FileName);
        ValidateAbsoluteNonReparsePath(configuration);
        // Missing file fails closed. No fallback to CWD, game directory, registry or Steam options.
        using (var stream = new FileStream(configuration, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            if (stream.Length is <= 0 or > MaximumConfigBytes)
                throw new InvalidOperationException("Windows probe configuration size is invalid.");
            var bytes = new byte[(int)stream.Length];
            var offset = 0;
            while (offset < bytes.Length)
            {
                var read = stream.Read(bytes, offset, bytes.Length - offset);
                if (read == 0) throw new InvalidOperationException("Windows probe configuration was truncated.");
                offset += read;
            }
            if (stream.ReadByte() != -1) throw new InvalidOperationException("Windows probe configuration changed.");
            using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 2 });
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
                throw new InvalidOperationException("Windows probe configuration must be an object.");
            var properties = root.EnumerateObject().ToArray();
            if (properties.Length != 2 || properties.Select(p => p.Name).Distinct(StringComparer.Ordinal).Count() != 2 ||
                !root.TryGetProperty("schema_version", out var version) || version.ValueKind != JsonValueKind.Number ||
                !version.TryGetInt32(out var number) || number != 1 ||
                !root.TryGetProperty("mode", out var mode) || mode.ValueKind != JsonValueKind.String || mode.GetString() != "probe_only")
                throw new InvalidOperationException("Only schema_version=1 and mode=probe_only are supported.");
        }
        ValidateAbsoluteNonReparsePath(configuration);
        var privateRoot = Path.Combine(directory, PrivateDirectoryName);
        ValidateAbsoluteNonReparsePath(privateRoot);
        return privateRoot;
    }

    // Best-effort checks in an owner-controlled private directory, NOT a defense against
    // an attacker concurrently replacing path components. No ACL/security claims are made.
    internal static void ValidateAbsoluteNonReparsePath(string path)
    {
        if (!Path.IsPathFullyQualified(path)) throw new InvalidOperationException("Absolute private path required.");
        var current = Path.GetFullPath(path);
        while (!string.IsNullOrEmpty(current))
        {
            try
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Windows probe refuses symbolic-link/reparse paths.");
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
            current = Path.GetDirectoryName(current);
        }
    }
}
