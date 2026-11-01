using System.Globalization;
using System.Text;
using System.Text.Json;

namespace FootballAssistant.GameBridge;

// Strict schema2 decoder only. No filesystem, approved-config loading, scheduling,
// host registration, game calls or implicit activation is provided by this codec.
internal static class BatchRequestCodec
{
    internal const int MaximumUtf8Bytes = 32768;
    private static readonly HashSet<string> Properties = new(StringComparer.Ordinal)
    {
        "schema_version", "nonce", "batch_id", "sequence", "page_epoch", "pid", "session_id",
        "bridge_sha256", "game_sha256", "window_class", "panel_index", "subtree_path", "approval_sha256",
        "cursor_sha256", "created_at", "expires_at", "cursor"
    };

    internal static BatchRequest Parse(string json)
    {
        ArgumentNullException.ThrowIfNull(json);
        if (json.Length > MaximumUtf8Bytes || new UTF8Encoding(false, true).GetByteCount(json) > MaximumUtf8Bytes)
            throw new InvalidOperationException("Batch request exceeds UTF8 bound.");
        using var document = JsonDocument.Parse(json, new JsonDocumentOptions
        { AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow, MaxDepth = 4 });
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object) throw new InvalidOperationException("Batch request must be an object.");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in root.EnumerateObject())
            if (!Properties.Contains(property.Name) || !seen.Add(property.Name))
                throw new InvalidOperationException("Unknown or duplicate batch request property.");
        if (seen.Count != Properties.Count) throw new InvalidOperationException("Missing batch request property.");

        string Text(string name, int maximum, bool empty = false)
        {
            var value = root.GetProperty(name);
            if (value.ValueKind != JsonValueKind.String) throw new InvalidOperationException("Batch request string required.");
            var text = value.GetString()!;
            if ((!empty && text.Length == 0) || text.Length > maximum)
                throw new InvalidOperationException("Batch request string outside bound.");
            return text;
        }
        int Number(string name, int minimum, int maximum)
        {
            var value = root.GetProperty(name);
            if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out var number) ||
                value.GetRawText().Any(c => c is < '0' or > '9') || number < minimum || number > maximum)
                throw new InvalidOperationException("Canonical bounded batch integer required.");
            return number;
        }
        Guid Id(string name)
        {
            var text = Text(name, 36);
            if (!Guid.TryParseExact(text, "D", out var value) || value == Guid.Empty ||
                value.ToString("D", CultureInfo.InvariantCulture) != text)
                throw new InvalidOperationException("Canonical nonempty batch UUID required.");
            return value;
        }
        DateTimeOffset Time(string name)
        {
            var text = Text(name, 64);
            var explicitOffset = text.EndsWith('Z') || (text.Length >= 6 && (text[^6] is '+' or '-') && text[^3] == ':');
            if (!explicitOffset || !root.GetProperty(name).TryGetDateTimeOffset(out var value))
                throw new InvalidOperationException("ISO8601 batch timestamp required.");
            return value;
        }
        string Digest(string name)
        {
            var value = Text(name, 64);
            if (!BatchPolicy.ValidDigest(value)) throw new InvalidOperationException("Canonical batch hash required.");
            return value;
        }
        var subtree = Text("subtree_path", 191, empty: true);
        if (!BatchPolicy.ValidPath(subtree)) throw new InvalidOperationException("Canonical batch subtree required.");
        return new(Number("schema_version", BatchPolicy.SchemaVersion, BatchPolicy.SchemaVersion), Id("nonce"), Id("batch_id"),
            Number("sequence", 1, 4), Id("page_epoch"), Number("pid", 1, int.MaxValue), Text("session_id", 128),
            Digest("bridge_sha256"), Digest("game_sha256"), Text("window_class", 126), Number("panel_index", 0, 31),
            subtree, Digest("approval_sha256"), Digest("cursor_sha256"), Time("created_at"), Time("expires_at"),
            Text("cursor", 16384, empty: true));
    }
}
