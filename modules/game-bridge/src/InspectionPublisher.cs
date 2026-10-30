using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;

namespace FootballAssistant.GameBridge;

internal sealed record InspectionFrame(object source, object probes_payload, RuntimeReadProof[] read_proofs, RegistryDiagnostic[] registry_diagnostics, RegistryEnumerationSnapshot[] registry_enumerations, string gc_handle_gate);

internal sealed class InspectionPublisher : IDisposable
{
    private readonly Channel<InspectionFrame> frames = Channel.CreateBounded<InspectionFrame>(new BoundedChannelOptions(1)
    { SingleReader = true, SingleWriter = true, FullMode = BoundedChannelFullMode.DropOldest });
    private readonly Dictionary<string, (string Id, string? Stamp, int? Version, int? Expected)> epochs = new();
    private readonly HttpClient http = new(new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = false }) { Timeout = TimeSpan.FromMilliseconds(1500) };
    private readonly CancellationTokenSource stop = new();
    private readonly string privateRoot, runtimeFile, sessionId;
    private readonly Action<string> report;
    private readonly Task writer;
    private int disposed;
    private string? lastRegistrySnapshot;

    public InspectionPublisher(string privateRoot, string runtimeFile, string sessionId, Action<string> report)
    {
        this.privateRoot = privateRoot;
        this.runtimeFile = runtimeFile;
        this.sessionId = sessionId;
        this.report = report;
        Directory.CreateDirectory(Path.Combine(privateRoot, "diagnostics"));
        writer = Task.Run(WriteLoop);
    }

    public void Offer(RuntimeReadProof[] proofs, RegistryDiagnostic[] registries, RegistryEnumerationSnapshot[]? enumerations = null, string gcHandleGate = "not_probed")
    {
        if (Volatile.Read(ref disposed) != 0) return;
        enumerations ??= Array.Empty<RegistryEnumerationSnapshot>();
        var probes = new List<object>();
        foreach (var registry in registries)
        {
            if (!epochs.TryGetValue(registry.registry, out var epoch) || epoch.Stamp != registry.context_stamp ||
                epoch.Version != registry.dictionary_version || epoch.Expected != registry.id_count)
            {
                epoch = (Guid.NewGuid().ToString(), registry.context_stamp, registry.dictionary_version, registry.id_count);
                epochs[registry.registry] = epoch;
            }
            var enumeration = enumerations.FirstOrDefault(e => e.registry_id == registry.registry && e.dictionary_version == registry.dictionary_version && e.expected_count == registry.id_count);
            probes.Add(CountsOnlyProbe(registry, enumeration?.enumeration_id ?? epoch.Id, sessionId, enumeration?.entries.Length ?? 0));
        }
        var now = DateTimeOffset.UtcNow.ToString("O");
        var header = new
        {
            adapter_id = "footballassistant.runtime-inspector",
            session_id = sessionId,
            game_build = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_GAME_BUILD"),
            bundle_version = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_BUNDLE_VERSION"),
            metadata_sha256 = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_METADATA_SHA256"),
            game_assembly_sha256 = Environment.GetEnvironmentVariable("FOOTBALL_ASSISTANT_ASSEMBLY_SHA256"),
            captured_at = now,
            synthetic = false
        };
        var body = new
        {
            header.adapter_id, header.session_id, header.game_build, header.bundle_version,
            header.metadata_sha256, header.game_assembly_sha256, header.captured_at, header.synthetic,
            probes
        };
        frames.Writer.TryWrite(new InspectionFrame(header, body, proofs, registries, enumerations, gcHandleGate));
    }

    internal static object CountsOnlyProbe(RegistryDiagnostic registry, string enumerationId, string sessionId, int locallyCopiedEntries = 0) => new
    {
        probe_id = "registry:" + registry.registry,
        kind = "runtime_registry",
        status = registry.status,
        context_ref = "session/" + sessionId + "/registry/" + registry.registry,
        reason = registry.reason,
        values = new { id_count = registry.id_count, name_hash_count = registry.name_hash_count },
        enumeration = new
        {
            enumeration_id = enumerationId,
            expected_entries = registry.id_count,
            observed_unique_entries = locallyCopiedEntries,
            complete = false,
            dictionary_version = registry.dictionary_version
        },
        entries = Array.Empty<object>()
    };

    private async Task WriteLoop()
    {
        await foreach (var frame in frames.Reader.ReadAllAsync())
        {
            try
            {
                var target = Path.Combine(privateRoot, "diagnostics", "runtime-inspection.json");
                var temporary = target + ".tmp";
                var summary = new
                {
                    frame.source, frame.probes_payload, frame.read_proofs, frame.registry_diagnostics, frame.gc_handle_gate,
                    registry_enumerations = frame.registry_enumerations.Select(r => new { r.registry_id, r.enumeration_id, r.dictionary_version, r.expected_count, r.complete, r.scanned_slots, r.status, r.reason, locally_copied_entries = r.entries.Length })
                };
                await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(summary));
                File.Move(temporary, target, true);
                var signature = string.Join("|", frame.registry_enumerations.Select(r => $"{r.enumeration_id}:{r.scanned_slots}:{r.entries.Length}:{r.complete}:{r.status}"));
                if (signature != lastRegistrySnapshot)
                {
                    var registryTarget = Path.Combine(privateRoot, "diagnostics", "registry-enumerations.json");
                    await File.WriteAllTextAsync(registryTarget + ".tmp", JsonSerializer.Serialize(new { frame.source, frame.registry_enumerations }));
                    File.Move(registryTarget + ".tmp", registryTarget, true);
                    var archive = Path.Combine(privateRoot, "diagnostics", "registry-completed");
                    foreach (var completed in frame.registry_enumerations.Where(r => r.complete))
                    {
                        Directory.CreateDirectory(archive);
                        var archivePath = Path.Combine(archive, completed.enumeration_id + ".json");
                        if (!File.Exists(archivePath))
                            await File.WriteAllTextAsync(archivePath, JsonSerializer.Serialize(new { frame.source, registry_enumerations = new[] { completed } }));
                    }
                    lastRegistrySnapshot = signature;
                }
                if (stop.IsCancellationRequested) continue;
                var body = JsonSerializer.SerializeToUtf8Bytes(frame.probes_payload);
                if (body.Length > 100_000) { report("Registry probe diagnostic exceeded byte budget; not posted."); continue; }
                var connection = ConnectionSettings.Read(runtimeFile);
                using var request = new HttpRequestMessage(HttpMethod.Post, new Uri(connection.BaseUrl, "/v1/interfaces/probes"));
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", connection.Token);
                request.Content = new ByteArrayContent(body);
                request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
                using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop.Token);
                if (!response.IsSuccessStatusCode) report($"Registry probe delivery refused (HTTP {(int)response.StatusCode}).");
            }
            catch (Exception error) { report("Registry diagnostic writer/delivery unavailable (" + error.GetType().Name + ")."); }
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref disposed, 1) != 0) return;
        frames.Writer.TryComplete();
        stop.Cancel();
        http.Dispose();
        // Last queued full snapshot can still be persisted; never wait on the game thread.
    }
}
