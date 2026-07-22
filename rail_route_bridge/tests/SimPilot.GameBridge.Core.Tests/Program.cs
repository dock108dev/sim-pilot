using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using SimPilot.GameBridge;

var tests = new (string Name, Action Run)[]
{
    ("strict envelope round trip", GoldenEnvelopes),
    ("unknown and duplicate keys fail", StrictKeys),
    ("length prefix bounds", FrameBounds),
    ("read-only capability and snapshot", CapabilityModels),
    ("partial game-state coverage names only observed fields", PartialGameStateCoverage),
    ("semantic entities serialize with deterministic coverage", SemanticEntities),
    ("authenticated loopback exchange", AuthenticatedExchange),
    ("invalid authentication fails closed", InvalidAuthentication),
    ("idle authenticated client receives heartbeat", Heartbeat),
    ("single client ownership", SingleClientOwnership),
};
var failures = 0;
foreach (var test in tests)
{
    try { test.Run(); Console.WriteLine($"PASS {test.Name}"); }
    catch (Exception error) { failures++; Console.Error.WriteLine($"FAIL {test.Name}: {error}"); }
}
return failures == 0 ? 0 : 1;

static void GoldenEnvelopes()
{
    var expected = ProtocolCodec.SerializeEnvelope(ClientHello("correct-token-000000000000000000000"));
    var envelope = ProtocolCodec.ParseEnvelope(expected);
    Equal(expected, ProtocolCodec.SerializeEnvelope(envelope), "client hello");
}

static void StrictKeys()
{
    var hello = ProtocolCodec.SerializeEnvelope(ClientHello("correct-token-000000000000000000000"));
    Throws<FormatException>(() => ProtocolCodec.ParseEnvelope(hello.Replace("\"payload\":", "\"unknown\":1,\"payload\":")), "unknown key");
    Throws<FormatException>(() => StrictJson.Parse("{\"a\":1,\"a\":2}"), "duplicate JSON key");
    Throws<FormatException>(() => ProtocolCodec.ParseEnvelope(hello.Replace("\"protocol_version\":3,", "")), "missing key");
    Throws<FormatException>(() => ProtocolCodec.ParseEnvelope(hello.Replace("\"message_type\":\"client_hello\"", "\"message_type\":\"arbitrary_command\"")), "unknown message");
}

static void FrameBounds()
{
    using var stream = new MemoryStream();
    LengthPrefixedFrame.Write(stream, "hello", 16);
    stream.Position = 0;
    Equal("hello", LengthPrefixedFrame.Read(stream, 16), "frame round trip");
    using var oversized = new MemoryStream(new byte[] { 0, 0, 0, 17 });
    Throws<InvalidDataException>(() => LengthPrefixedFrame.Read(oversized, 16), "oversized frame");
    using var zero = new MemoryStream(new byte[] { 0, 0, 0, 0 });
    Throws<InvalidDataException>(() => LengthPrefixedFrame.Read(zero, 16), "zero frame");
}

static void CapabilityModels()
{
    var capability = ProtocolCodec.CapabilityPayload();
    Equal(0, capability.AsObject()["gameplay_actions"].AsArray().Count, "action catalog");
    var state = FakeProvider.State();
    var response = ProtocolCodec.SnapshotResponsePayload(state, "bridge", 3, DateTimeOffset.UtcNow);
    var surfaces = response.AsObject()["snapshot"].AsObject()["surfaces"].AsArray();
    True(surfaces.Count == 9, "all coverage surfaces are explicit");
    True(surfaces.All(item => item.AsObject()["entities"].AsArray().Count == 0), "no unproven entities");
    Equal(9, capability.AsObject()["observation_surfaces"].AsArray().Count, "advertised observation surfaces");
    True(capability.AsObject()["observation_surfaces"].AsArray().Any(item => item.AsString() == "track_occupancy"), "track occupancy capability");
}

static void SemanticEntities()
{
    var state = FakeProvider.State();
    state.SemanticSurfaces = new[]
    {
        new ObservationSurfaceState
        {
            Surface = "track_occupancy",
            Status = CoverageStatus.ObservedComplete,
            Fields = new[] { "allocation_state", "train_id" },
            Detail = "test track state",
            Entities = new[]
            {
                new ObservedEntityState
                {
                    EntityType = "train_track_segment",
                    EntityId = "train-1:occupied:0:track-1",
                    Values = new Dictionary<string, JsonValue>
                    {
                        ["allocation_state"] = JsonValue.String("Occupied"),
                        ["train_id"] = JsonValue.String("train-1"),
                    },
                },
            },
        },
        new ObservationSurfaceState
        {
            Surface = "trains",
            Status = CoverageStatus.ObservedComplete,
            Fields = new[] { "reporting_number", "uuid" },
            Detail = "test repository snapshot",
            Entities = new[]
            {
                new ObservedEntityState
                {
                    EntityType = "train",
                    EntityId = "train-1",
                    Values = new Dictionary<string, JsonValue>
                    {
                        ["reporting_number"] = JsonValue.String("SP-101"),
                        ["uuid"] = JsonValue.String("train-1"),
                    },
                },
            },
        },
    };
    var response = ProtocolCodec.SnapshotResponsePayload(state, "bridge", 3, DateTimeOffset.UtcNow);
    var surfaces = response.AsObject()["snapshot"].AsObject()["surfaces"].AsArray();
    var trains = surfaces.Single(item => item.AsObject()["coverage"].AsObject()["surface"].AsString() == "trains");
    Equal("observed_complete", trains.AsObject()["coverage"].AsObject()["status"].AsString(), "train coverage");
    Equal("train-1", trains.AsObject()["entities"].AsArray().Single().AsObject()["entity_id"].AsString(), "train identity");
    var occupancy = surfaces.Single(item => item.AsObject()["coverage"].AsObject()["surface"].AsString() == "track_occupancy");
    Equal("train-1:occupied:0:track-1", occupancy.AsObject()["entities"].AsArray().Single().AsObject()["entity_id"].AsString(), "track segment identity");
}

static void PartialGameStateCoverage()
{
    var state = FakeProvider.State();
    state.GameMode = null;
    state.SimulationSpeed = null;
    var response = ProtocolCodec.SnapshotResponsePayload(state, "bridge", 3, DateTimeOffset.UtcNow);
    var surfaces = response.AsObject()["snapshot"].AsObject()["surfaces"].AsArray();
    var gameState = surfaces.Single(item => item.AsObject()["coverage"].AsObject()["surface"].AsString() == "game_state");
    var coverage = gameState.AsObject()["coverage"].AsObject();
    Equal("observed_partial", coverage["status"].AsString(), "partial coverage status");
    var fields = coverage["fields"].AsArray().Select(item => item.AsString()).ToArray();
    Equal("current_time,paused", string.Join(",", fields), "partial coverage fields");
}

static void AuthenticatedExchange()
{
    const string token = "correct-token-000000000000000000000";
    var provider = new FakeProvider();
    using var server = new BridgeServer(token, provider, 0);
    server.Start();
    var endpoint = server.LocalEndpoint ?? throw new Exception("missing endpoint");
    Equal(IPAddress.Loopback, endpoint.Address, "listener address");
    using var client = Connect(endpoint);
    var stream = client.GetStream();
    LengthPrefixedFrame.Write(stream, ProtocolCodec.SerializeEnvelope(ClientHello(token)));
    var hello = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    Equal(MessageType.BridgeHello, hello.MessageType, "bridge hello");
    var capabilities = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    Equal(MessageType.CapabilityManifest, capabilities.MessageType, "manifest");
    Equal(0, capabilities.Payload.AsObject()["gameplay_actions"].AsArray().Count, "action catalog");
    var request = ClientEnvelope(MessageType.FullSnapshotRequest, 2, hello, JsonValue.Object(new Dictionary<string, JsonValue>
    {
        ["expected_bridge_instance_id"] = JsonValue.String(hello.BridgeInstanceId),
        ["expected_game_session_id"] = JsonValue.String(hello.GameSessionId),
    }));
    LengthPrefixedFrame.Write(stream, ProtocolCodec.SerializeEnvelope(request));
    var snapshot = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    Equal(MessageType.FullSnapshotResponse, snapshot.MessageType, "snapshot response");
    Equal(request.MessageId, snapshot.CorrelationId, "snapshot correlation");
}

static void InvalidAuthentication()
{
    var provider = new FakeProvider();
    using var server = new BridgeServer("correct-token-000000000000000000000", provider, 0);
    server.Start();
    using var client = Connect(server.LocalEndpoint!);
    var stream = client.GetStream();
    LengthPrefixedFrame.Write(stream, ProtocolCodec.SerializeEnvelope(ClientHello("incorrect-token-000000000000000000")));
    var response = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    Equal(MessageType.AuthenticationFailure, response.MessageType, "authentication response");
    True(!ProtocolCodec.SerializeEnvelope(response).Contains("correct-token", StringComparison.Ordinal), "token not disclosed");
}

static void Heartbeat()
{
    const string token = "correct-token-000000000000000000000";
    var provider = new FakeProvider();
    using var server = new BridgeServer(token, provider, 0);
    server.Start();
    using var client = Connect(server.LocalEndpoint!);
    var stream = client.GetStream();
    LengthPrefixedFrame.Write(stream, ProtocolCodec.SerializeEnvelope(ClientHello(token)));
    ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    var heartbeat = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream));
    Equal(MessageType.Heartbeat, heartbeat.MessageType, "heartbeat type");
    True(heartbeat.Payload.AsObject()["healthy"].AsBoolean(), "heartbeat health");
}

static void SingleClientOwnership()
{
    var provider = new FakeProvider();
    using var server = new BridgeServer("correct-token-000000000000000000000", provider, 0);
    server.Start();
    using var owner = Connect(server.LocalEndpoint!);
    LengthPrefixedFrame.Write(owner.GetStream(), ProtocolCodec.SerializeEnvelope(ClientHello("correct-token-000000000000000000000")));
    ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(owner.GetStream()));
    ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(owner.GetStream()));
    using var second = Connect(server.LocalEndpoint!);
    second.ReceiveTimeout = 1000;
    try
    {
        LengthPrefixedFrame.Write(second.GetStream(), ProtocolCodec.SerializeEnvelope(ClientHello("correct-token-000000000000000000000")));
        var value = second.GetStream().ReadByte();
        Equal(-1, value, "second client closed");
    }
    catch (IOException)
    {
        // A reset or an unserviced timeout both prove that the second client
        // could not complete an authenticated handshake while ownership was held.
    }
}

static Envelope ClientHello(string token) => new()
{
    ProtocolVersion = BridgeContract.ProtocolVersion,
    AdapterVersion = BridgeContract.AdapterVersion,
    GameId = BridgeContract.GameId,
    GameVersion = BridgeContract.SupportedGameVersion,
    Platform = "macos",
    Architecture = "x86_64",
    BridgeInstanceId = "client-unnegotiated",
    GameSessionId = "client-unnegotiated",
    MapIdentity = Identity.Unavailable("not negotiated"),
    SaveIdentity = Identity.Unavailable("not negotiated"),
    MessageId = "client:hello",
    BridgeSequence = 1,
    MessageType = MessageType.ClientHello,
    Timestamp = DateTimeOffset.UtcNow,
    Payload = JsonValue.Object(new Dictionary<string, JsonValue>
    {
        ["authentication_token"] = JsonValue.String(token),
        ["client_instance_id"] = JsonValue.String("test-client"),
        ["requested_protocol_version"] = JsonValue.Integer(BridgeContract.ProtocolVersion),
        ["expected_adapter_version"] = JsonValue.String(BridgeContract.AdapterVersion),
        ["expected_game_id"] = JsonValue.String(BridgeContract.GameId),
        ["expected_game_version"] = JsonValue.String(BridgeContract.SupportedGameVersion),
    }),
};

static Envelope ClientEnvelope(MessageType type, long sequence, Envelope identity, JsonValue payload) => new()
{
    ProtocolVersion = BridgeContract.ProtocolVersion,
    AdapterVersion = BridgeContract.AdapterVersion,
    GameId = BridgeContract.GameId,
    GameVersion = BridgeContract.SupportedGameVersion,
    Platform = "macos",
    Architecture = "x86_64",
    BridgeInstanceId = identity.BridgeInstanceId,
    GameSessionId = identity.GameSessionId,
    MapIdentity = identity.MapIdentity,
    SaveIdentity = identity.SaveIdentity,
    MessageId = "client:" + sequence,
    BridgeSequence = sequence,
    MessageType = type,
    Timestamp = DateTimeOffset.UtcNow,
    Payload = payload,
};

static TcpClient Connect(IPEndPoint endpoint)
{
    var client = new TcpClient(AddressFamily.InterNetwork) { ReceiveTimeout = 3000, SendTimeout = 3000 };
    client.Connect(endpoint);
    return client;
}

static void Equal<T>(T expected, T actual, string context)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual)) throw new Exception($"{context}: expected {expected}, found {actual}");
}
static void True(bool value, string context) { if (!value) throw new Exception(context); }
static void Throws<T>(Action action, string context) where T : Exception { try { action(); } catch (T) { return; } throw new Exception($"{context}: expected {typeof(T).Name}"); }

sealed class FakeProvider : IReadOnlyGameStateProvider
{
    public RuntimeSnapshot Capture() => State();
    public static RuntimeSnapshot State() => new()
    {
        GameVersion = BridgeContract.SupportedGameVersion,
        Platform = "macos",
        Architecture = "x86_64",
        GameSessionId = "session-test",
        MapIdentity = Identity.Unavailable("map identity unavailable"),
        SaveIdentity = Identity.Unavailable("save identity unavailable"),
        Paused = true,
        CurrentTime = "08:00",
        SimulationSpeed = "0",
        GameMode = "Sandbox",
        GameStateAvailable = true,
        GameStateDetail = "direct public API fixture",
    };
}
