using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace SimPilot.GameBridge;

public sealed class BridgeServer : IDisposable
{
    private readonly string authenticationToken;
    private readonly IReadOnlyGameStateProvider stateProvider;
    private readonly TcpListener listener;
    private readonly BridgeContractDescriptor contract;
    private readonly Action<string>? errorLogger;
    private readonly string bridgeInstanceId = Guid.NewGuid().ToString("D");
    private readonly HashSet<string> messageIds = new(StringComparer.Ordinal);
    private Thread? thread;
    private volatile bool stopping;
    private int activeClient;
    private long sequence;

    public BridgeServer(string authenticationToken, IReadOnlyGameStateProvider stateProvider,
        int port = BridgeContract.DefaultPort, BridgeContractDescriptor? contract = null,
        Action<string>? errorLogger = null)
    {
        if (string.IsNullOrWhiteSpace(authenticationToken) || Encoding.UTF8.GetByteCount(authenticationToken) < 32)
            throw new ArgumentException("authentication token must contain at least 32 UTF-8 bytes", nameof(authenticationToken));
        this.authenticationToken = authenticationToken;
        this.stateProvider = stateProvider ?? throw new ArgumentNullException(nameof(stateProvider));
        this.contract = contract ?? BridgeContract.RailRoute;
        this.errorLogger = errorLogger;
        BridgeContract.Configure(this.contract);
        listener = new TcpListener(IPAddress.Loopback, port);
    }

    public IPEndPoint? LocalEndpoint => listener.LocalEndpoint as IPEndPoint;

    public void Start()
    {
        if (thread != null) throw new InvalidOperationException("bridge server already started");
        listener.Start(1);
        var endpoint = (IPEndPoint)listener.LocalEndpoint;
        if (!IPAddress.IsLoopback(endpoint.Address)) throw new InvalidOperationException("bridge refused a non-loopback listener");
        thread = new Thread(AcceptLoop) { IsBackground = true, Name = contract.ThreadName };
        thread.Start();
    }

    public void Dispose()
    {
        stopping = true;
        listener.Stop();
        if (thread != null && thread != Thread.CurrentThread) thread.Join(TimeSpan.FromSeconds(2));
        thread = null;
    }

    private void AcceptLoop()
    {
        while (!stopping)
        {
            try
            {
                var client = listener.AcceptTcpClient();
                if (!TryAcquireClient())
                {
                    client.Client.LingerState = new LingerOption(true, 0);
                    client.Close();
                    continue;
                }
                ThreadPool.QueueUserWorkItem(_ => HandleOwnedClient(client));
            }
            catch (SocketException) when (stopping) { return; }
            catch (ObjectDisposedException) when (stopping) { return; }
        }
    }

    private bool TryAcquireClient()
    {
        // A reconnect can reach AcceptTcpClient just before the previous handler
        // observes EOF and releases ownership. Allow only that short handoff; a
        // genuinely concurrent second client is still rejected within 250 ms.
        for (var attempt = 0; attempt < 25; attempt++)
        {
            if (Interlocked.CompareExchange(ref activeClient, 1, 0) == 0) return true;
            Thread.Sleep(10);
        }
        return false;
    }

    private void HandleOwnedClient(TcpClient client)
    {
        try { HandleClient(client); }
        catch (IOException) { }
        catch (SocketException) { }
        catch (FormatException) { }
        catch (Exception error)
        {
            errorLogger?.Invoke("bridge client failed: " + error.GetType().Name + ": " + error.Message);
        }
        finally
        {
            client.Close();
            Interlocked.Exchange(ref activeClient, 0);
        }
    }

    private void HandleClient(TcpClient client)
    {
        client.ReceiveTimeout = 2000;
        client.SendTimeout = 5000;
        client.NoDelay = true;
        var stream = client.GetStream();
        Envelope hello;
        try { hello = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream)); }
        catch (Exception error) when (error is FormatException || error is InvalidDataException)
        {
            SendError(stream, null, "malformed_envelope", "request did not satisfy the strict protocol envelope", false);
            return;
        }
        if (hello.MessageType != MessageType.ClientHello)
        {
            SendError(stream, hello.MessageId, "protocol_mismatch", "client_hello must be the first message", false);
            return;
        }
        if (!FixedTimeEquals(ProtocolCodec.AuthenticationToken(hello), authenticationToken))
        {
            Send(stream, MessageType.AuthenticationFailure, hello.MessageId, ProtocolCodec.AuthenticationFailurePayload());
            return;
        }
        lock (messageIds)
        {
            messageIds.Clear();
            messageIds.Add(hello.MessageId);
        }
        SendHelloAndCapabilities(stream, hello.MessageId);
        var lastClientSequence = hello.BridgeSequence;
        while (!stopping && client.Connected)
        {
            Envelope request;
            try { request = ProtocolCodec.ParseEnvelope(LengthPrefixedFrame.Read(stream)); }
            catch (EndOfStreamException) { return; }
            catch (IOException)
            {
                // Mono on macOS does not consistently preserve SocketError.TimedOut as
                // the inner exception for NetworkStream read timeouts. EOF is handled
                // above; if this was a reset rather than an idle timeout, the heartbeat
                // write fails and the owning handler closes the connection.
                Send(stream, MessageType.Heartbeat, null, ProtocolCodec.HeartbeatPayload());
                continue;
            }
            catch (Exception error) when (error is FormatException || error is InvalidDataException)
            {
                SendError(stream, null, "malformed_envelope", "request did not satisfy the strict protocol contract", false);
                return;
            }
            lock (messageIds)
            {
                if (!messageIds.Add(request.MessageId)) { SendError(stream, request.MessageId, "duplicate_message", "message_id was already processed", false); return; }
            }
            if (request.BridgeSequence != lastClientSequence + 1)
            {
                SendError(stream, request.MessageId, "sequence_error", "client sequence is not contiguous", false);
                return;
            }
            lastClientSequence = request.BridgeSequence;
            if (request.BridgeInstanceId != null && request.BridgeInstanceId != bridgeInstanceId)
            {
                SendError(stream, request.MessageId, "stale_identity", "bridge identity changed; resynchronize", false);
                return;
            }
            var currentState = stateProvider.Capture();
            if (request.MessageType != MessageType.ResynchronizationRequest && (request.GameSessionId != currentState.GameSessionId || !SameIdentity(request.MapIdentity, currentState.MapIdentity) || !SameIdentity(request.SaveIdentity, currentState.SaveIdentity)))
            {
                SendError(stream, request.MessageId, "stale_identity", "game, map, or save identity changed; resynchronize", false);
                return;
            }
            if (request.MessageType == MessageType.FullSnapshotRequest)
            {
                var expected = request.Payload.AsObject();
                var state = currentState;
                if (expected["expected_bridge_instance_id"].AsString() != bridgeInstanceId || expected["expected_game_session_id"].AsString() != state.GameSessionId)
                {
                    SendError(stream, request.MessageId, "stale_identity", "snapshot identity is stale; resynchronize", false);
                    return;
                }
                SendSnapshot(stream, request.MessageId, state);
            }
            else if (request.MessageType == MessageType.ResynchronizationRequest) SendHelloAndCapabilities(stream, request.MessageId);
            else { SendError(stream, request.MessageId, "unknown_message_type", "message is not accepted from a client", false); return; }
        }
    }

    private void SendHelloAndCapabilities(Stream stream, string correlationId)
    {
        var state = stateProvider.Capture();
        Send(stream, MessageType.BridgeHello, correlationId, ProtocolCodec.BridgeHelloPayload(), state);
        Send(stream, MessageType.CapabilityManifest, null, ProtocolCodec.CapabilityPayload(), state);
    }

    private long? SendSnapshot(Stream stream, string correlationId, RuntimeSnapshot? captured = null)
    {
        RuntimeSnapshot state;
        try { state = captured ?? stateProvider.Capture(); }
        catch (Exception)
        {
            SendError(stream, correlationId, "snapshot_failed", "snapshot collection failed", true);
            return null;
        }
        var responseSequence = Interlocked.Read(ref sequence) + 1;
        Send(stream, MessageType.FullSnapshotResponse, correlationId, ProtocolCodec.SnapshotResponsePayload(state, bridgeInstanceId, responseSequence, DateTimeOffset.UtcNow), state);
        return responseSequence;
    }

    private void SendError(Stream stream, string? correlationId, string code, string message, bool retryable) => Send(stream, MessageType.ProtocolError, correlationId ?? "client:unavailable", ErrorPayload(code, message, retryable));

    private void Send(Stream stream, MessageType type, string? correlationId, JsonValue payload, RuntimeSnapshot? captured = null)
    {
        var state = captured ?? stateProvider.Capture();
        var envelope = new Envelope
        {
            ProtocolVersion = contract.ProtocolVersion,
            AdapterVersion = contract.AdapterVersion,
            GameId = contract.GameId,
            GameVersion = state.GameVersion,
            Platform = state.Platform,
            Architecture = state.Architecture,
            BridgeInstanceId = bridgeInstanceId,
            GameSessionId = state.GameSessionId,
            MapIdentity = state.MapIdentity,
            SaveIdentity = state.SaveIdentity,
            MessageId = bridgeInstanceId + ":" + Interlocked.Increment(ref sequence).ToString(CultureInfo.InvariantCulture),
            CorrelationId = correlationId,
            BridgeSequence = sequence,
            MessageType = type,
            Timestamp = DateTimeOffset.UtcNow,
            Payload = payload,
        };
        LengthPrefixedFrame.Write(stream, ProtocolCodec.SerializeEnvelope(envelope));
    }

    private static JsonValue ErrorPayload(string code, string message, bool retryable) => JsonValue.Object(new Dictionary<string, JsonValue>
    {
        ["code"] = JsonValue.String(code),
        ["message"] = JsonValue.String(message),
        ["retryable"] = JsonValue.Boolean(retryable),
    });

    private static bool FixedTimeEquals(string supplied, string expected)
    {
        var left = Encoding.UTF8.GetBytes(supplied);
        var right = Encoding.UTF8.GetBytes(expected);
        var difference = left.Length ^ right.Length;
        var count = Math.Max(left.Length, right.Length);
        for (var index = 0; index < count; index++) difference |= left[index % left.Length] ^ right[index % right.Length];
        return difference == 0;
    }

    private static bool SameIdentity(Identity left, Identity right) =>
        left.Status == right.Status && left.Value == right.Value && left.Label == right.Label && left.Detail == right.Detail;
}
