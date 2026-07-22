using System;
using System.Collections.Generic;
using System.Globalization;

namespace SimPilot.GameBridge;

public static class BridgeContract
{
    public const int ProtocolVersion = 2;
    public const string AdapterVersion = "rail-route-set-route-v1";
    public const string GameId = "rail-route";
    public const string SupportedGameVersion = "2.3.24";
    public const int MaximumMessageBytes = 1_048_576;
    public const int DefaultPort = 18461;
}

public enum MessageType { ClientHello, BridgeHello, AuthenticationFailure, Heartbeat, CapabilityManifest, FullSnapshotRequest, FullSnapshotResponse, ResynchronizationRequest, SetRouteRequest, SetRouteResponse, ProtocolError }
public enum CoverageStatus { ObservedComplete, ObservedPartial, Unsupported, Unavailable, Failed }

public sealed class Identity
{
    public string Status { get; set; } = "unavailable";
    public string? Value { get; set; }
    public string? Label { get; set; }
    public string? Detail { get; set; }
    public static Identity Unavailable(string detail) => new() { Detail = detail };
    public static Identity Observed(string value, string? label, string detail) => new() { Status = "observed", Value = value, Label = label, Detail = detail };
}

public sealed class Envelope
{
    public int ProtocolVersion { get; set; }
    public string AdapterVersion { get; set; } = string.Empty;
    public string GameId { get; set; } = string.Empty;
    public string GameVersion { get; set; } = string.Empty;
    public string Platform { get; set; } = string.Empty;
    public string Architecture { get; set; } = string.Empty;
    public string BridgeInstanceId { get; set; } = string.Empty;
    public string GameSessionId { get; set; } = string.Empty;
    public Identity MapIdentity { get; set; } = Identity.Unavailable("not negotiated");
    public Identity SaveIdentity { get; set; } = Identity.Unavailable("not negotiated");
    public string MessageId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public long BridgeSequence { get; set; }
    public MessageType MessageType { get; set; }
    public DateTimeOffset Timestamp { get; set; }
    public JsonValue Payload { get; set; } = JsonValue.Object(new Dictionary<string, JsonValue>());
}

public sealed class RuntimeSnapshot
{
    public string GameVersion { get; set; } = BridgeContract.SupportedGameVersion;
    public string Platform { get; set; } = "macos";
    public string Architecture { get; set; } = "x86_64";
    public string GameSessionId { get; set; } = string.Empty;
    public Identity MapIdentity { get; set; } = Identity.Unavailable("map identity is unavailable");
    public Identity SaveIdentity { get; set; } = Identity.Unavailable("save identity is unavailable");
    public bool? Paused { get; set; }
    public string? CurrentTime { get; set; }
    public string? SimulationSpeed { get; set; }
    public string? GameMode { get; set; }
    public bool GameStateAvailable { get; set; }
    public string GameStateDetail { get; set; } = "game state is unavailable";
    public IReadOnlyList<ObservationSurfaceState> SemanticSurfaces { get; set; } = Array.Empty<ObservationSurfaceState>();
    public string[] Warnings { get; set; } = Array.Empty<string>();
    public string[] Limitations { get; set; } = Array.Empty<string>();
}

public interface IReadOnlyGameStateProvider { RuntimeSnapshot Capture(); }

public static class ProtocolCodec
{
    private static readonly string[] EnvelopeKeys = { "adapter_version", "architecture", "bridge_instance_id", "bridge_sequence", "correlation_id", "game_id", "game_session_id", "game_version", "map_identity", "message_id", "message_type", "payload", "platform", "protocol_version", "save_identity", "timestamp" };

    public static Envelope ParseEnvelope(string json)
    {
        var root = StrictJson.Parse(json).AsObject();
        Exact(root, EnvelopeKeys, "envelope");
        var protocol = Integer(root, "protocol_version", BridgeContract.ProtocolVersion, BridgeContract.ProtocolVersion);
        var timestampText = String(root, "timestamp");
        if (!DateTimeOffset.TryParse(timestampText, CultureInfo.InvariantCulture, DateTimeStyles.None, out var timestamp) || timestamp.Offset != TimeSpan.Zero) throw new FormatException("timestamp must be RFC3339 UTC");
        var result = new Envelope
        {
            ProtocolVersion = protocol,
            AdapterVersion = Text(root, "adapter_version"),
            GameId = Text(root, "game_id"),
            GameVersion = Text(root, "game_version"),
            Platform = Text(root, "platform"),
            Architecture = Text(root, "architecture"),
            BridgeInstanceId = Text(root, "bridge_instance_id"),
            GameSessionId = Text(root, "game_session_id"),
            MapIdentity = ParseIdentity(root["map_identity"]),
            SaveIdentity = ParseIdentity(root["save_identity"]),
            MessageId = Text(root, "message_id"),
            CorrelationId = OptionalText(root, "correlation_id"),
            BridgeSequence = Integer64(root, "bridge_sequence", 1, long.MaxValue),
            MessageType = ParseMessageType(String(root, "message_type")),
            Timestamp = timestamp,
            Payload = root["payload"],
        };
        ValidateEnvelope(result);
        ValidatePayload(result.MessageType, result.Payload.AsObject());
        return result;
    }

    public static string SerializeEnvelope(Envelope value)
    {
        ValidateEnvelope(value); ValidatePayload(value.MessageType, value.Payload.AsObject());
        return StrictJson.Serialize(JsonValue.Object(new Dictionary<string, JsonValue>
        {
            ["protocol_version"] = JsonValue.Integer(value.ProtocolVersion),
            ["adapter_version"] = JsonValue.String(value.AdapterVersion),
            ["game_id"] = JsonValue.String(value.GameId),
            ["game_version"] = JsonValue.String(value.GameVersion),
            ["platform"] = JsonValue.String(value.Platform),
            ["architecture"] = JsonValue.String(value.Architecture),
            ["bridge_instance_id"] = JsonValue.String(value.BridgeInstanceId),
            ["game_session_id"] = JsonValue.String(value.GameSessionId),
            ["map_identity"] = IdentityJson(value.MapIdentity),
            ["save_identity"] = IdentityJson(value.SaveIdentity),
            ["message_id"] = JsonValue.String(value.MessageId),
            ["correlation_id"] = Nullable(value.CorrelationId),
            ["bridge_sequence"] = JsonValue.Integer(value.BridgeSequence),
            ["message_type"] = JsonValue.String(MessageTypeName(value.MessageType)),
            ["timestamp"] = JsonValue.String(Time(value.Timestamp)),
            ["payload"] = value.Payload,
        }));
    }

    public static string AuthenticationToken(Envelope hello) => hello.MessageType == MessageType.ClientHello ? String(hello.Payload.AsObject(), "authentication_token") : throw new FormatException("client_hello required");

    private static void ValidateEnvelope(Envelope value)
    {
        if (value.ProtocolVersion != BridgeContract.ProtocolVersion || value.AdapterVersion != BridgeContract.AdapterVersion || value.GameId != BridgeContract.GameId || value.GameVersion != BridgeContract.SupportedGameVersion) throw new FormatException("incompatible bridge envelope");
        if (value.Platform != "macos" && value.Platform != "windows" && value.Platform != "linux") throw new FormatException("unsupported platform");
        if (value.Architecture != "x86_64" && value.Architecture != "arm64") throw new FormatException("unsupported architecture");
        if (string.IsNullOrWhiteSpace(value.BridgeInstanceId) || string.IsNullOrWhiteSpace(value.GameSessionId) || string.IsNullOrWhiteSpace(value.MessageId) || value.BridgeSequence < 1) throw new FormatException("envelope identity and sequence are required");
        ValidateIdentity(value.MapIdentity); ValidateIdentity(value.SaveIdentity);
        if (value.Timestamp.Offset != TimeSpan.Zero || value.Payload.Kind != JsonKind.Object) throw new FormatException("invalid timestamp or payload");
        if ((value.MessageType == MessageType.BridgeHello || value.MessageType == MessageType.AuthenticationFailure || value.MessageType == MessageType.FullSnapshotResponse || value.MessageType == MessageType.SetRouteResponse || value.MessageType == MessageType.ProtocolError) && value.CorrelationId == null) throw new FormatException("response requires correlation_id");
    }

    private static void ValidatePayload(MessageType type, IReadOnlyDictionary<string, JsonValue> payload)
    {
        switch (type)
        {
            case MessageType.ClientHello:
                Exact(payload, new[] { "authentication_token", "client_instance_id", "expected_adapter_version", "expected_game_id", "expected_game_version", "requested_protocol_version" }, "client_hello payload");
                if (Text(payload, "authentication_token").Length < 32 || Text(payload, "expected_adapter_version") != BridgeContract.AdapterVersion || Text(payload, "expected_game_id") != BridgeContract.GameId || Text(payload, "expected_game_version") != BridgeContract.SupportedGameVersion || Integer(payload, "requested_protocol_version", BridgeContract.ProtocolVersion, BridgeContract.ProtocolVersion) != BridgeContract.ProtocolVersion) throw new FormatException("incompatible client hello");
                Text(payload, "client_instance_id"); return;
            case MessageType.BridgeHello:
                Exact(payload, new[] { "authenticated", "heartbeat_interval_seconds", "maximum_message_bytes", "negotiated_protocol_version" }, "bridge_hello payload");
                if (!payload["authenticated"].AsBoolean() || payload["heartbeat_interval_seconds"].AsNumber() <= 0 || Integer(payload, "maximum_message_bytes", 1024, 16_777_216) < 1024 || Integer(payload, "negotiated_protocol_version", BridgeContract.ProtocolVersion, BridgeContract.ProtocolVersion) != BridgeContract.ProtocolVersion) throw new FormatException("invalid bridge hello"); return;
            case MessageType.AuthenticationFailure:
                Exact(payload, new[] { "reason" }, "authentication_failure payload"); if (String(payload, "reason") != "authentication_failed") throw new FormatException("invalid authentication failure"); return;
            case MessageType.Heartbeat:
                Exact(payload, new[] { "detail", "healthy" }, "heartbeat payload"); payload["healthy"].AsBoolean(); OptionalText(payload, "detail"); return;
            case MessageType.CapabilityManifest:
                Exact(payload, new[] { "delta_snapshots", "full_snapshots", "gameplay_actions", "observation_surfaces", "resynchronization", "schema_version" }, "capability manifest");
                if (Integer(payload, "schema_version", 1, 1) != 1 || !payload["full_snapshots"].AsBoolean() || payload["delta_snapshots"].AsBoolean() || !payload["resynchronization"].AsBoolean()) throw new FormatException("invalid capability manifest");
                SortedStrings(payload["observation_surfaces"], "observation_surfaces");
                SortedStrings(payload["gameplay_actions"], "gameplay_actions");
                var actions = payload["gameplay_actions"].AsArray();
                if (actions.Count != 1 || actions[0].AsString() != "set_route") throw new FormatException("only set_route may be advertised"); return;
            case MessageType.FullSnapshotRequest:
                Exact(payload, new[] { "expected_bridge_instance_id", "expected_game_session_id" }, "snapshot request"); Text(payload, "expected_bridge_instance_id"); Text(payload, "expected_game_session_id"); return;
            case MessageType.FullSnapshotResponse:
                Exact(payload, new[] { "snapshot" }, "snapshot response"); ValidateSnapshot(payload["snapshot"].AsObject()); return;
            case MessageType.ResynchronizationRequest:
                Exact(payload, new[] { "last_bridge_instance_id", "last_bridge_sequence", "last_game_session_id", "reason" }, "resynchronization request");
                OptionalText(payload, "last_bridge_instance_id"); OptionalText(payload, "last_game_session_id"); if (payload["last_bridge_sequence"].Kind != JsonKind.Null) Integer64(payload, "last_bridge_sequence", 1, long.MaxValue); Text(payload, "reason"); return;
            case MessageType.SetRouteRequest:
                Exact(payload, new[] { "destination_signal", "expected_bridge_instance_id", "expected_game_session_id", "expected_snapshot_sequence", "origin_signal", "schema_version" }, "set_route request");
                Integer(payload, "schema_version", 1, 1); Text(payload, "origin_signal"); Text(payload, "destination_signal"); Text(payload, "expected_bridge_instance_id"); Text(payload, "expected_game_session_id"); Integer64(payload, "expected_snapshot_sequence", 1, long.MaxValue); return;
            case MessageType.SetRouteResponse:
                Exact(payload, new[] { "destination_connection", "destination_signal", "detail", "executed", "origin_signal", "outcome", "reason_code", "schema_version" }, "set_route response");
                Integer(payload, "schema_version", 1, 1); Text(payload, "origin_signal"); Text(payload, "destination_signal"); OptionalText(payload, "destination_connection"); payload["executed"].AsBoolean();
                var outcome = String(payload, "outcome"); if (outcome != "succeeded" && outcome != "rejected") throw new FormatException("invalid set_route outcome"); Text(payload, "reason_code"); Text(payload, "detail"); return;
            case MessageType.ProtocolError:
                Exact(payload, new[] { "code", "message", "retryable" }, "protocol error"); ParseErrorCode(String(payload, "code")); Text(payload, "message"); payload["retryable"].AsBoolean(); return;
            default: throw new FormatException("unknown message type");
        }
    }

    private static void ValidateSnapshot(IReadOnlyDictionary<string, JsonValue> value)
    {
        Exact(value, new[] { "adapter_version", "architecture", "bridge_instance_id", "bridge_sequence", "capture_completed_marker", "capture_started_marker", "capture_timestamp", "game_id", "game_session_id", "game_state", "game_version", "limitations", "map_identity", "platform", "save_identity", "schema_version", "surfaces", "warnings" }, "snapshot");
        Integer(value, "schema_version", 1, 1); Text(value, "capture_timestamp"); Text(value, "capture_started_marker"); Text(value, "capture_completed_marker"); Integer64(value, "bridge_sequence", 1, long.MaxValue);
        Text(value, "bridge_instance_id"); Text(value, "game_session_id"); Text(value, "game_id"); Text(value, "game_version"); Text(value, "adapter_version"); Text(value, "platform"); Text(value, "architecture");
        ParseIdentity(value["map_identity"]); ParseIdentity(value["save_identity"]); value["game_state"].AsObject(); StringArray(value["warnings"]); StringArray(value["limitations"]);
        string? prior = null;
        foreach (var item in value["surfaces"].AsArray())
        {
            var surface = item.AsObject(); Exact(surface, new[] { "coverage", "entities" }, "observation surface");
            var coverage = surface["coverage"].AsObject(); Exact(coverage, new[] { "detail", "fields", "status", "surface" }, "coverage");
            var name = Text(coverage, "surface"); if (prior != null && string.CompareOrdinal(prior, name) >= 0) throw new FormatException("surfaces must be sorted and unique"); prior = name;
            ParseCoverage(String(coverage, "status")); SortedStrings(coverage["fields"], "coverage fields"); OptionalText(coverage, "detail");
            var entities = surface["entities"].AsArray();
            if ((String(coverage, "status") == "unsupported" || String(coverage, "status") == "unavailable" || String(coverage, "status") == "failed") && entities.Count != 0) throw new FormatException("unobserved surface contains entities");
            string? priorEntity = null;
            foreach (var entityValue in entities)
            {
                var entity = entityValue.AsObject();
                Exact(entity, new[] { "entity_id", "entity_type", "values" }, "observed entity");
                var key = Text(entity, "entity_type") + "\0" + Text(entity, "entity_id");
                if (priorEntity != null && string.CompareOrdinal(priorEntity, key) >= 0) throw new FormatException("entities must be sorted and unique");
                priorEntity = key;
                entity["values"].AsObject();
            }
        }
    }

    public static JsonValue BridgeHelloPayload() => JsonValue.Object(new Dictionary<string, JsonValue> { ["authenticated"] = JsonValue.Boolean(true), ["negotiated_protocol_version"] = JsonValue.Integer(BridgeContract.ProtocolVersion), ["maximum_message_bytes"] = JsonValue.Integer(BridgeContract.MaximumMessageBytes), ["heartbeat_interval_seconds"] = JsonValue.Number(2.0) });
    public static JsonValue AuthenticationFailurePayload() => JsonValue.Object(new Dictionary<string, JsonValue> { ["reason"] = JsonValue.String("authentication_failed") });
    public static JsonValue HeartbeatPayload() => JsonValue.Object(new Dictionary<string, JsonValue> { ["healthy"] = JsonValue.Boolean(true), ["detail"] = JsonValue.Null() });
    public static JsonValue CapabilityPayload() => JsonValue.Object(new Dictionary<string, JsonValue> { ["schema_version"] = JsonValue.Integer(1), ["observation_surfaces"] = JsonValue.Array(JsonValue.String("game_state"), JsonValue.String("incoming_traffic"), JsonValue.String("platforms"), JsonValue.String("routes"), JsonValue.String("signals"), JsonValue.String("stations"), JsonValue.String("switches"), JsonValue.String("track_occupancy"), JsonValue.String("trains")), ["gameplay_actions"] = JsonValue.Array(JsonValue.String("set_route")), ["full_snapshots"] = JsonValue.Boolean(true), ["delta_snapshots"] = JsonValue.Boolean(false), ["resynchronization"] = JsonValue.Boolean(true) });

    public static JsonValue SetRouteResponsePayload(SetRouteActionResult result) => JsonValue.Object(new Dictionary<string, JsonValue>
    {
        ["schema_version"] = JsonValue.Integer(1),
        ["origin_signal"] = JsonValue.String(result.OriginSignal),
        ["destination_signal"] = JsonValue.String(result.DestinationSignal),
        ["destination_connection"] = Nullable(result.DestinationConnection),
        ["outcome"] = JsonValue.String(result.Outcome),
        ["executed"] = JsonValue.Boolean(result.Executed),
        ["reason_code"] = JsonValue.String(result.ReasonCode),
        ["detail"] = JsonValue.String(result.Detail),
    });

    public static JsonValue SnapshotResponsePayload(RuntimeSnapshot state, string bridgeId, long bridgeSequence, DateTimeOffset captured) => JsonValue.Object(new Dictionary<string, JsonValue>
    {
        ["snapshot"] = JsonValue.Object(new Dictionary<string, JsonValue>
        {
            ["schema_version"] = JsonValue.Integer(1),
            ["capture_timestamp"] = JsonValue.String(Time(captured)),
            ["capture_started_marker"] = JsonValue.String("single-main-thread-sample"),
            ["capture_completed_marker"] = JsonValue.String("single-main-thread-sample"),
            ["bridge_sequence"] = JsonValue.Integer(bridgeSequence),
            ["bridge_instance_id"] = JsonValue.String(bridgeId),
            ["game_session_id"] = JsonValue.String(state.GameSessionId),
            ["game_id"] = JsonValue.String(BridgeContract.GameId),
            ["game_version"] = JsonValue.String(state.GameVersion),
            ["adapter_version"] = JsonValue.String(BridgeContract.AdapterVersion),
            ["platform"] = JsonValue.String(state.Platform),
            ["architecture"] = JsonValue.String(state.Architecture),
            ["map_identity"] = IdentityJson(state.MapIdentity),
            ["save_identity"] = IdentityJson(state.SaveIdentity),
            ["game_state"] = JsonValue.Object(new Dictionary<string, JsonValue> { ["paused"] = state.Paused.HasValue ? JsonValue.Boolean(state.Paused.Value) : JsonValue.Null(), ["current_time"] = Nullable(state.CurrentTime), ["simulation_speed"] = Nullable(state.SimulationSpeed), ["game_mode"] = Nullable(state.GameMode) }),
            ["surfaces"] = Surfaces(state),
            ["warnings"] = Strings(state.Warnings),
            ["limitations"] = Strings(state.Limitations),
        }),
    });

    private static JsonValue Surfaces(RuntimeSnapshot state)
    {
        var byName = new Dictionary<string, ObservationSurfaceState>(StringComparer.Ordinal);
        foreach (var surface in state.SemanticSurfaces) byName.Add(surface.Surface, surface);
        var result = new List<JsonValue>
        {
            Surface(new ObservationSurfaceState { Surface = "game_state", Status = GameStateCoverage(state), Fields = GameStateFields(state), Detail = state.GameStateDetail }),
        };
        foreach (var name in new[] { "incoming_traffic", "platforms", "routes", "signals", "stations", "switches", "track_occupancy", "trains" })
            result.Add(Surface(byName.TryGetValue(name, out var surface) ? surface : ObservationSurfaceState.Unsupported(name)));
        return JsonValue.Array(result.ToArray());
    }

    private static JsonValue Surface(ObservationSurfaceState surface)
    {
        var fieldValues = new JsonValue[surface.Fields.Length]; for (var i = 0; i < surface.Fields.Length; i++) fieldValues[i] = JsonValue.String(surface.Fields[i]);
        var entities = new JsonValue[surface.Entities.Count];
        for (var i = 0; i < surface.Entities.Count; i++)
        {
            var entity = surface.Entities[i];
            entities[i] = JsonValue.Object(new Dictionary<string, JsonValue>
            {
                ["entity_type"] = JsonValue.String(entity.EntityType),
                ["entity_id"] = JsonValue.String(entity.EntityId),
                ["values"] = EntityValues(entity.Values),
            });
        }
        return JsonValue.Object(new Dictionary<string, JsonValue> { ["coverage"] = JsonValue.Object(new Dictionary<string, JsonValue> { ["surface"] = JsonValue.String(surface.Surface), ["status"] = JsonValue.String(CoverageName(surface.Status)), ["fields"] = JsonValue.Array(fieldValues), ["detail"] = JsonValue.String(surface.Detail) }), ["entities"] = JsonValue.Array(entities) });
    }

    private static JsonValue Strings(string[] values) { var items = new JsonValue[values.Length]; for (var i = 0; i < values.Length; i++) items[i] = JsonValue.String(values[i]); return JsonValue.Array(items); }
    private static JsonValue EntityValues(IReadOnlyDictionary<string, JsonValue> values) { var copy = new Dictionary<string, JsonValue>(StringComparer.Ordinal); foreach (var item in values) copy.Add(item.Key, item.Value); return JsonValue.Object(copy); }

    private static string[] GameStateFields(RuntimeSnapshot state)
    {
        if (!state.GameStateAvailable) return Array.Empty<string>();
        var fields = new List<string>();
        if (state.CurrentTime != null) fields.Add("current_time");
        if (state.GameMode != null) fields.Add("game_mode");
        if (state.Paused.HasValue) fields.Add("paused");
        if (state.SimulationSpeed != null) fields.Add("simulation_speed");
        return fields.ToArray();
    }

    private static CoverageStatus GameStateCoverage(RuntimeSnapshot state)
    {
        var count = GameStateFields(state).Length;
        if (!state.GameStateAvailable || count == 0) return CoverageStatus.Unavailable;
        return count == 4 ? CoverageStatus.ObservedComplete : CoverageStatus.ObservedPartial;
    }

    private static Identity ParseIdentity(JsonValue value) { var item = value.AsObject(); Exact(item, new[] { "detail", "label", "status", "value" }, "identity"); var result = new Identity { Status = String(item, "status"), Value = OptionalText(item, "value"), Label = OptionalText(item, "label"), Detail = OptionalText(item, "detail") }; ValidateIdentity(result); return result; }
    private static void ValidateIdentity(Identity value) { if (value.Status != "observed" && value.Status != "unavailable") throw new FormatException("invalid identity status"); if (value.Status == "observed" && string.IsNullOrWhiteSpace(value.Value)) throw new FormatException("observed identity requires value"); if (value.Status == "unavailable" && value.Value != null) throw new FormatException("unavailable identity cannot have value"); }
    private static JsonValue IdentityJson(Identity value) { ValidateIdentity(value); return JsonValue.Object(new Dictionary<string, JsonValue> { ["status"] = JsonValue.String(value.Status), ["value"] = Nullable(value.Value), ["label"] = Nullable(value.Label), ["detail"] = Nullable(value.Detail) }); }
    private static JsonValue Nullable(string? value) => value == null ? JsonValue.Null() : JsonValue.String(value);
    private static void Exact(IReadOnlyDictionary<string, JsonValue> values, IEnumerable<string> expected, string context) { var remaining = new HashSet<string>(expected, StringComparer.Ordinal); foreach (var key in values.Keys) if (!remaining.Remove(key)) throw new FormatException($"unknown key in {context}: {key}"); if (remaining.Count != 0) throw new FormatException($"missing key in {context}: {string.Join(",", remaining)}"); }
    private static string String(IReadOnlyDictionary<string, JsonValue> values, string key) => values[key].AsString();
    private static string Text(IReadOnlyDictionary<string, JsonValue> values, string key) { var result = String(values, key); if (string.IsNullOrWhiteSpace(result)) throw new FormatException($"{key} must not be empty"); return result; }
    private static string? OptionalText(IReadOnlyDictionary<string, JsonValue> values, string key) => values[key].Kind == JsonKind.Null ? null : Text(values, key);
    private static int Integer(IReadOnlyDictionary<string, JsonValue> values, string key, int minimum, int maximum) => checked((int)Integer64(values, key, minimum, maximum));
    private static long Integer64(IReadOnlyDictionary<string, JsonValue> values, string key, long minimum, long maximum) { var result = values[key].AsInteger(); if (result < minimum || result > maximum) throw new FormatException($"{key} out of range"); return result; }
    private static void StringArray(JsonValue value) { foreach (var item in value.AsArray()) item.AsString(); }
    private static void SortedStrings(JsonValue value, string context) { string? prior = null; foreach (var item in value.AsArray()) { var current = item.AsString(); if (prior != null && string.CompareOrdinal(prior, current) >= 0) throw new FormatException($"{context} must be sorted and unique"); prior = current; } }
    private static string Time(DateTimeOffset value)
    {
        var utc = value.UtcDateTime;
        var prefix = utc.ToString("yyyy-MM-dd'T'HH:mm:ss", CultureInfo.InvariantCulture);
        var fractionalTicks = utc.Ticks % TimeSpan.TicksPerSecond;
        if (fractionalTicks == 0) return prefix + "Z";
        return prefix + "." + fractionalTicks.ToString("D7", CultureInfo.InvariantCulture).TrimEnd('0') + "Z";
    }
    public static string MessageTypeName(MessageType value) => value switch { MessageType.ClientHello => "client_hello", MessageType.BridgeHello => "bridge_hello", MessageType.AuthenticationFailure => "authentication_failure", MessageType.Heartbeat => "heartbeat", MessageType.CapabilityManifest => "capability_manifest", MessageType.FullSnapshotRequest => "full_snapshot_request", MessageType.FullSnapshotResponse => "full_snapshot_response", MessageType.ResynchronizationRequest => "resynchronization_request", MessageType.SetRouteRequest => "set_route_request", MessageType.SetRouteResponse => "set_route_response", MessageType.ProtocolError => "protocol_error", _ => throw new FormatException("unknown message type") };
    private static MessageType ParseMessageType(string value) => value switch { "client_hello" => MessageType.ClientHello, "bridge_hello" => MessageType.BridgeHello, "authentication_failure" => MessageType.AuthenticationFailure, "heartbeat" => MessageType.Heartbeat, "capability_manifest" => MessageType.CapabilityManifest, "full_snapshot_request" => MessageType.FullSnapshotRequest, "full_snapshot_response" => MessageType.FullSnapshotResponse, "resynchronization_request" => MessageType.ResynchronizationRequest, "set_route_request" => MessageType.SetRouteRequest, "set_route_response" => MessageType.SetRouteResponse, "protocol_error" => MessageType.ProtocolError, _ => throw new FormatException("unknown message_type") };
    private static string CoverageName(CoverageStatus value) => value switch { CoverageStatus.ObservedComplete => "observed_complete", CoverageStatus.ObservedPartial => "observed_partial", CoverageStatus.Unsupported => "unsupported", CoverageStatus.Unavailable => "unavailable", CoverageStatus.Failed => "failed", _ => throw new FormatException("unknown coverage") };
    private static CoverageStatus ParseCoverage(string value) => value switch { "observed_complete" => CoverageStatus.ObservedComplete, "observed_partial" => CoverageStatus.ObservedPartial, "unsupported" => CoverageStatus.Unsupported, "unavailable" => CoverageStatus.Unavailable, "failed" => CoverageStatus.Failed, _ => throw new FormatException("unknown coverage") };
    private static void ParseErrorCode(string value) { var allowed = new HashSet<string>(new[] { "malformed_envelope", "unknown_message_type", "message_too_large", "protocol_mismatch", "adapter_mismatch", "game_mismatch", "duplicate_message", "sequence_error", "stale_identity", "snapshot_failed", "internal_error" }, StringComparer.Ordinal); if (!allowed.Contains(value)) throw new FormatException("unknown protocol error code"); }
}
