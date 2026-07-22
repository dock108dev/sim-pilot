using System;
using System.Globalization;
using System.Diagnostics;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using BepInEx;
using BepInEx.Logging;
using SimPilot.GameBridge;
using UnityEngine;

namespace SimPilot.RailRoute.Bridge;

[BepInPlugin(PluginGuid, PluginName, PluginVersion)]
public sealed class Plugin : BaseUnityPlugin
{
    public const string PluginGuid = "com.simpilot.railroute.bridge";
    public const string PluginName = "Sim Pilot Rail Route Bridge";
    public const string PluginVersion = "3.0.0";

    private void Awake()
    {
        var startupStage = "resolve authentication token";
        GameObject? hostObject = null;
        try
        {
            var tokenPath = TokenPath();
            if (!TokenFileIsPrivate(tokenPath))
            {
                Logger.LogError("Bridge authentication token is unavailable or unsafe; listener was not started.");
                return;
            }
            startupStage = "read authentication token";
            var token = File.ReadAllText(tokenPath).Trim();
            startupStage = "create persistent runtime host";
            hostObject = new GameObject("Sim Pilot Rail Route UI Observer Bridge Runtime")
            {
                hideFlags = HideFlags.HideAndDontSave,
            };
            DontDestroyOnLoad(hostObject);
            var host = hostObject.AddComponent<RailRouteBridgeRuntimeHost>();
            startupStage = "start loopback listener";
            host.Initialize(token, ConfiguredPort(), Logger);
        }
        catch (Exception error)
        {
            Logger.LogError($"Semantic bridge failed closed during {startupStage}: {error.GetType().Name}");
            if (hostObject != null) Destroy(hostObject);
        }
    }

    private void OnDestroy()
    {
        Logger.LogInfo("Semantic bridge bootstrap component was released; the persistent runtime host owns shutdown.");
    }

    private static int ConfiguredPort()
    {
        var raw = Environment.GetEnvironmentVariable("SIM_PILOT_RAIL_ROUTE_BRIDGE_PORT");
        if (raw == null) return BridgeContract.DefaultPort;
        if (!int.TryParse(raw, NumberStyles.None, CultureInfo.InvariantCulture, out var port) || port < 1 || port > 65535) throw new InvalidOperationException("SIM_PILOT_RAIL_ROUTE_BRIDGE_PORT is invalid");
        return port;
    }

    private static string TokenPath()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library", "Application Support", "Sim Pilot", "rail-route-bridge", "auth-token");
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Sim Pilot", "rail-route-bridge", "auth-token");
    }

    private static bool TokenFileIsPrivate(string path)
    {
        if (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) return false;
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.OSX)) return true;
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = "/usr/bin/stat",
            Arguments = "-f %Lp \"" + path.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        });
        if (process == null) return false;
        var mode = process.StandardOutput.ReadToEnd().Trim();
        process.WaitForExit();
        return process.ExitCode == 0 && (mode == "600" || mode == "400");
    }
}

internal sealed class RailRouteBridgeRuntimeHost : MonoBehaviour
{
    private BridgeServer? server;
    private RailRouteStateProvider? stateProvider;
    private ManualLogSource? log;

    internal void Initialize(string token, int port, ManualLogSource logger)
    {
        log = logger;
        stateProvider = new RailRouteStateProvider();
        server = new BridgeServer(token, stateProvider, port);
        server.Start();
        log.LogInfo($"Semantic bridge listening on {server.LocalEndpoint}.");
    }

    private void Update()
    {
        try
        {
            stateProvider?.RefreshFromGame();
        }
        catch (Exception error)
        {
            stateProvider?.MarkUnavailable($"game-state sampling failed closed: {error.GetType().Name}");
        }
    }

    private void OnDestroy()
    {
        if (server == null) return;
        log?.LogInfo("Semantic bridge runtime host is shutting down.");
        server.Dispose();
        server = null;
    }
}

internal sealed class RailRouteStateProvider : IReadOnlyGameStateProvider
{
    private readonly object sync = new();
    private RuntimeSnapshot current;
    private bool lastLoaded;

    internal RailRouteStateProvider()
    {
        current = BaseSnapshot(Guid.NewGuid().ToString("D"));
    }

    internal void RefreshFromGame()
    {
        var dependencies = Game.Context.Ctx.Deps;
        var controller = dependencies == null ? null : dependencies.GameController;
        var gameControllers = dependencies == null ? null : dependencies.GameControllers;
        var time = gameControllers == null ? null : gameControllers.TimeController;
        var loaded = controller != null && controller.Loaded && time != null;
        lock (sync)
        {
            if (loaded != lastLoaded)
            {
                current.GameSessionId = Guid.NewGuid().ToString("D");
                lastLoaded = loaded;
            }
            current.GameVersion = Application.version;
            current.Platform = RuntimeInformation.IsOSPlatform(OSPlatform.OSX) ? "macos" : RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "windows" : RuntimeInformation.OSDescription;
            current.Architecture = ArchitectureName(RuntimeInformation.ProcessArchitecture);
            current.MapIdentity = MapIdentity(dependencies);
            current.SaveIdentity = SaveIdentity(controller);
            if (!loaded || time == null)
            {
                current.Paused = null;
                current.CurrentTime = null;
                current.SimulationSpeed = null;
                current.GameMode = null;
                current.GameStateAvailable = false;
                current.GameStateDetail = "no loaded game is available";
                current.SemanticSurfaces = UnavailableSurfaces("no loaded game is available");
                current.Limitations = new[] { "No semantic collections are authoritative until a game is loaded." };
                return;
            }
            current.Paused = time.TimeMultiplier <= 0f;
            current.CurrentTime = time.CurrentTime.ToString("c", CultureInfo.InvariantCulture);
            current.SimulationSpeed = SpeedName(time);
            current.GameMode = dependencies!.CurrentMode.ToString().ToLowerInvariant();
            current.GameStateAvailable = true;
            current.GameStateDetail = "sampled from public time and context APIs on the Unity main thread";
            current.SemanticSurfaces = CaptureSemanticSurfaces(dependencies, gameControllers!);
            current.Warnings = Array.Empty<string>();
            current.Limitations = new[]
            {
                "Routes contain active signal allocations only, not every possible path.",
                "Track occupancy reports model allocation and train segment state, not presentation colors.",
            };
        }
    }

    public RuntimeSnapshot Capture()
    {
        lock (sync)
        {
            return new RuntimeSnapshot
            {
                GameVersion = current.GameVersion,
                Platform = current.Platform,
                Architecture = current.Architecture,
                GameSessionId = current.GameSessionId,
                MapIdentity = current.MapIdentity,
                SaveIdentity = current.SaveIdentity,
                Paused = current.Paused,
                CurrentTime = current.CurrentTime,
                SimulationSpeed = current.SimulationSpeed,
                GameMode = current.GameMode,
                GameStateAvailable = current.GameStateAvailable,
                GameStateDetail = current.GameStateDetail,
                SemanticSurfaces = current.SemanticSurfaces,
                Warnings = current.Warnings,
                Limitations = current.Limitations,
            };
        }
    }

    internal void MarkUnavailable(string detail)
    {
        lock (sync)
        {
            current.Paused = null;
            current.CurrentTime = null;
            current.SimulationSpeed = null;
            current.GameMode = null;
            current.GameStateAvailable = false;
            current.GameStateDetail = detail;
            current.SemanticSurfaces = UnavailableSurfaces(detail);
            current.Warnings = new[] { detail };
        }
    }

    private static RuntimeSnapshot BaseSnapshot(string sessionId) => new()
    {
        GameVersion = BridgeContract.SupportedGameVersion,
        Platform = RuntimeInformation.IsOSPlatform(OSPlatform.OSX) ? "macos" : RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? "windows" : RuntimeInformation.OSDescription,
        Architecture = ArchitectureName(RuntimeInformation.ProcessArchitecture),
        GameSessionId = sessionId,
        GameStateAvailable = false,
        GameStateDetail = "game state has not been sampled",
        SemanticSurfaces = UnavailableSurfaces("game state has not been sampled"),
        Limitations = new[] { "No semantic collections are authoritative until a game is loaded." },
    };

    private static Identity MapIdentity(Game.Context.IControllers? dependencies)
    {
        var definition = dependencies?.LevelController?.CurrentLevel?.LevelDefinition;
        if (definition == null || string.IsNullOrWhiteSpace(definition.Uuid))
            return Identity.Unavailable("loaded level does not expose a stable UUID");
        return Identity.Observed(definition.Uuid, EmptyToNull(definition.Name), "Rail Route LevelDefinition.Uuid");
    }

    private static Identity SaveIdentity(Game.IGameController? controller)
    {
        var save = controller?.LoadedSave;
        if (save == null || string.IsNullOrWhiteSpace(save.FileName))
            return Identity.Unavailable("the current session is not backed by an identified save file");
        var value = string.Join(":", new[] { save.LevelUuid ?? string.Empty, save.Discriminator ?? string.Empty, save.FileName });
        return Identity.Observed(value, EmptyToNull(save.SaveName), "Rail Route LoadedSave stable fields");
    }

    private static string? EmptyToNull(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;

    private static string SpeedName(Game.Time.ITimeController time)
    {
        if (time.TimeMultiplier <= 0f) return "paused";
        if (time is not Game.Time.TimeController)
            return time.TimeMultiplier.ToString("R", CultureInfo.InvariantCulture);
        if (Near(time.TimeMultiplier, Game.Time.TimeController.TimeNormalMultiplier)) return "normal";
        if (Near(time.TimeMultiplier, Game.Time.TimeController.Time2Multiplier)) return "5x";
        if (Near(time.TimeMultiplier, Game.Time.TimeController.Time3Multiplier)) return "15x";
        if (Near(time.TimeMultiplier, Game.Time.TimeController.Time4Multiplier)) return "25x";
        return time.TimeMultiplier.ToString("R", CultureInfo.InvariantCulture);
    }

    private static bool Near(float left, float right) => Math.Abs(left - right) < 0.0001f;

    private static IReadOnlyList<ObservationSurfaceState> CaptureSemanticSurfaces(Game.Context.IControllers dependencies, Game.IGameControllers gameControllers)
    {
        return new[]
        {
            TrySurface("incoming_traffic", new[] { "destination", "due_time", "origin", "reporting_number", "requested_platform", "source", "uuid" }, () => IncomingTraffic(gameControllers)),
            TrySurface("platforms", new[] { "active", "length", "name", "occupied_train_ids", "station_id", "station_name", "station_number" }, () => dependencies.NodeRepository.GetNodes().OfType<Game.Railroad.Platform>().Select(PlatformEntity)),
            TrySurface("routes", new[] { "destination_connection", "locked", "signal_id" }, () => dependencies.NodeRepository.GetSemaphores().Where(signal => signal.CurrentRouteTo != null).Select(RouteEntity), "active signal routes observed from Semaphore.CurrentRouteTo; absence does not mean a path is impossible"),
            TrySurface("signals", new[] { "allocation_state", "current_route_to", "internal_name", "is_acting", "locked", "name", "occupied_train_ids", "signal_type" }, () => dependencies.NodeRepository.GetSemaphores().Select(SignalEntity)),
            TrySurface("stations", new[] { "active", "border_station", "friendly_name", "level_ref", "name", "station_index", "waiting_train_ids" }, () => dependencies.StationRepository.GetStations().Select(StationEntity)),
            TrySurface("switches", new[] { "active", "connected_count", "linked_connection", "name", "occupied_train_ids" }, () => dependencies.NodeRepository.GetNodes().OfType<Game.Railroad.Switch>().Select(SwitchEntity)),
            TrySurface("track_occupancy", new[] { "allocation_state", "end", "node_name", "node_type", "segment_kind", "start", "train_id" }, () => TrackOccupancy(dependencies)),
            TrySurface("trains", new[] { "current_speed_kmph", "destination", "next_station", "on_board", "origin", "reporting_number", "scheduled_arrival", "scheduled_departure", "uuid", "waiting_to_spawn" }, () => dependencies.TrainRepository.Trains.Select(TrainEntity)),
        };
    }

    private static ObservationSurfaceState TrySurface(string name, string[] fields, Func<IEnumerable<ObservedEntityState>> collect, string? detail = null)
    {
        try { return Surface(name, fields, collect(), detail); }
        catch (Exception error)
        {
            return new ObservationSurfaceState
            {
                Surface = name,
                Status = CoverageStatus.Failed,
                Detail = $"collection failed closed: {error.GetType().Name}",
            };
        }
    }

    private static ObservationSurfaceState Surface(string name, string[] fields, IEnumerable<ObservedEntityState> entities, string? detail = null)
    {
        var ordered = entities.OrderBy(entity => entity.EntityType, StringComparer.Ordinal).ThenBy(entity => entity.EntityId, StringComparer.Ordinal).ToArray();
        return new ObservationSurfaceState
        {
            Surface = name,
            Status = CoverageStatus.ObservedComplete,
            Fields = fields.OrderBy(value => value, StringComparer.Ordinal).ToArray(),
            Detail = detail ?? "complete public-repository collection for the captured Unity frame",
            Entities = ordered,
        };
    }

    private static ObservedEntityState TrainEntity(Game.Train.Train train)
    {
        var next = train.NextStationVisit();
        return Entity("train", TrainId(train), new Dictionary<string, JsonValue>
        {
            ["current_speed_kmph"] = JsonValue.Integer(train.CurrentSpeedKmph),
            ["destination"] = Nullable(train.Destination),
            ["next_station"] = Nullable(next?.Station?.Name),
            ["on_board"] = JsonValue.Boolean(train.OnBoard),
            ["origin"] = Nullable(train.Origin),
            ["reporting_number"] = Nullable(train.ReportingNumber),
            ["scheduled_arrival"] = Nullable(next == null ? null : next.From.ToString("c", CultureInfo.InvariantCulture)),
            ["scheduled_departure"] = Nullable(next == null ? null : next.To.ToString("c", CultureInfo.InvariantCulture)),
            ["uuid"] = JsonValue.String(TrainId(train)),
            ["waiting_to_spawn"] = JsonValue.Boolean(train.IsWaitingToBeSpawned),
        });
    }

    private static IEnumerable<ObservedEntityState> IncomingTraffic(Game.IGameControllers gameControllers)
    {
        var byId = new Dictionary<string, IncomingCandidate>(StringComparer.Ordinal);
        AddIncoming(byId, gameControllers.Timetable.GetScheduledTrainsEnumerable(), "timetable");
        AddIncoming(byId, gameControllers.TrainSpawnController.WaitingTrains, "waiting");
        AddIncoming(byId, gameControllers.TrainSpawnController.WaitingToSpawn.Trains, "waiting_to_spawn");
        return byId.Values.Select(candidate => IncomingEntity(candidate.Train, candidate.Source));
    }

    private static void AddIncoming(Dictionary<string, IncomingCandidate> byId, IEnumerable<Game.Train.Train> trains, string source)
    {
        foreach (var train in trains) byId[TrainId(train)] = new IncomingCandidate(train, source);
    }

    private static ObservedEntityState IncomingEntity(Game.Train.Train train, string source)
    {
        var next = source == "timetable"
            ? train.NextStationVisit()
            : train.NextStationVisitForDispatching() ?? train.NextStationVisit();
        return Entity("incoming_train", TrainId(train), new Dictionary<string, JsonValue>
        {
            ["destination"] = Nullable(train.Destination),
            ["due_time"] = Nullable(next == null ? null : next.From.ToString("c", CultureInfo.InvariantCulture)),
            ["origin"] = Nullable(train.Origin),
            ["reporting_number"] = Nullable(train.ReportingNumber),
            ["requested_platform"] = next?.PlatformNumber.HasValue == true ? JsonValue.Integer(next.PlatformNumber.Value) : JsonValue.Null(),
            ["source"] = JsonValue.String(source),
            ["uuid"] = JsonValue.String(TrainId(train)),
        });
    }

    private static IEnumerable<ObservedEntityState> TrackOccupancy(Game.Context.IControllers dependencies)
    {
        foreach (var node in dependencies.NodeRepository.GetNodes().Where(node => node.Trains.Count != 0 || Convert.ToInt64(node.AllocationState, CultureInfo.InvariantCulture) != 0))
            yield return TrackStateEntity(node);
        foreach (var train in dependencies.TrainRepository.Trains.Where(train => train.OnBoard))
        {
            foreach (var entity in TrackSegmentEntities(train, train.OccupiedSegments, "occupied")) yield return entity;
            foreach (var entity in TrackSegmentEntities(train, train.SegmentsInLookahead, "lookahead")) yield return entity;
        }
    }

    private static ObservedEntityState TrackStateEntity(Game.Railroad.Node node) => Entity("track_allocation", "allocation:" + NodeId(node), TrackValues(
        node, "allocated_node", null, null, null));

    private static IEnumerable<ObservedEntityState> TrackSegmentEntities(Game.Train.Train train, Game.Railroad.ReadonlySegments segments, string kind)
    {
        for (var index = 0; index < segments.Count; index++)
        {
            var node = segments.Nodes[index];
            yield return Entity("train_track_segment", $"{TrainId(train)}:{kind}:{index.ToString(CultureInfo.InvariantCulture)}:{NodeId(node)}", TrackValues(
                node, kind, train, segments.Starts[index], segments.Ends[index]));
        }
    }

    private static IReadOnlyDictionary<string, JsonValue> TrackValues(Game.Railroad.Node node, string kind, Game.Train.Train? train, float? start, float? end) => new Dictionary<string, JsonValue>
    {
        ["allocation_state"] = JsonValue.String(node.AllocationState.ToString()),
        ["end"] = end.HasValue ? JsonValue.Number(end.Value) : JsonValue.Null(),
        ["node_name"] = JsonValue.String(NodeId(node)),
        ["node_type"] = JsonValue.String(node.GetType().Name),
        ["segment_kind"] = JsonValue.String(kind),
        ["start"] = start.HasValue ? JsonValue.Number(start.Value) : JsonValue.Null(),
        ["train_id"] = train == null ? JsonValue.Null() : JsonValue.String(TrainId(train)),
    };

    private static ObservedEntityState StationEntity(Game.Railroad.Station station) => Entity("station", StationId(station), new Dictionary<string, JsonValue>
    {
        ["active"] = JsonValue.Boolean(station.Active),
        ["border_station"] = JsonValue.Boolean(station.BorderStation),
        ["friendly_name"] = Nullable(station.FriendlyName),
        ["level_ref"] = JsonValue.String(station.LevelChar.ToString()),
        ["name"] = JsonValue.String(station.Name),
        ["station_index"] = JsonValue.Integer(station.StationIndex),
        ["waiting_train_ids"] = Strings(station.WaitingTrains.Select(TrainId)),
    });

    private static ObservedEntityState PlatformEntity(Game.Railroad.Platform platform) => Entity("platform", platform.Name, new Dictionary<string, JsonValue>
    {
        ["active"] = JsonValue.Boolean(platform.Active),
        ["length"] = JsonValue.Number(platform.Length),
        ["name"] = JsonValue.String(platform.Name),
        ["occupied_train_ids"] = Strings(platform.Trains.Select(TrainId)),
        ["station_id"] = JsonValue.String(StationId(platform.Station)),
        ["station_name"] = JsonValue.String(platform.Station.Name),
        ["station_number"] = JsonValue.Integer(platform.StationNumber),
    });

    private static ObservedEntityState SignalEntity(Game.Railroad.Semaphore signal) => Entity("signal", SignalName(signal), new Dictionary<string, JsonValue>
    {
        ["allocation_state"] = JsonValue.String(signal.AllocationState.ToString()),
        ["current_route_to"] = Nullable(signal.CurrentRouteTo == null ? null : ConnectionId(signal.CurrentRouteTo)),
        ["internal_name"] = JsonValue.String(signal.Name),
        ["is_acting"] = JsonValue.Boolean(signal.IsActing),
        ["locked"] = JsonValue.Boolean(signal.Locked),
        ["name"] = JsonValue.String(SignalName(signal)),
        ["occupied_train_ids"] = Strings(signal.Trains.Select(TrainId)),
        ["signal_type"] = JsonValue.String(signal.Type.ToString()),
    });

    private static ObservedEntityState SwitchEntity(Game.Railroad.Switch item)
    {
        var linked = item.Connected.Length == 0 ? null : item.GetNextInPath(item.Connected[0]);
        return Entity("switch", item.Name, new Dictionary<string, JsonValue>
        {
            ["active"] = JsonValue.Boolean(item.Active),
            ["connected_count"] = JsonValue.Integer(item.Connected.Length),
            ["linked_connection"] = Nullable(linked == null ? null : ConnectionId(linked)),
            ["name"] = JsonValue.String(item.Name),
            ["occupied_train_ids"] = Strings(item.Trains.Select(TrainId)),
        });
    }

    private static ObservedEntityState RouteEntity(Game.Railroad.Semaphore signal) => Entity("route", SignalName(signal), new Dictionary<string, JsonValue>
    {
        ["destination_connection"] = JsonValue.String(ConnectionId(signal.CurrentRouteTo)),
        ["locked"] = JsonValue.Boolean(signal.Locked),
        ["signal_id"] = JsonValue.String(SignalName(signal)),
    });

    private static ObservedEntityState Entity(string type, string id, IReadOnlyDictionary<string, JsonValue> values) => new() { EntityType = type, EntityId = id, Values = values };
    private static string TrainId(Game.Train.Train train)
    {
        if (!string.IsNullOrWhiteSpace(train.Uuid)) return train.Uuid;
        if (!string.IsNullOrWhiteSpace(train.ReportingNumber)) return "reporting:" + train.ReportingNumber;
        throw new InvalidOperationException("Rail Route exposed a train without a stable public identity");
    }
    private static string StationId(Game.Railroad.Station station) => $"{station.LevelChar}:{station.StationIndex.ToString(CultureInfo.InvariantCulture)}";
    private static string SignalName(Game.Railroad.Semaphore signal) => string.IsNullOrWhiteSpace(signal.FriendlyName) ? signal.Name : signal.FriendlyName;
    private static string NodeId(Game.Railroad.Node node) => string.IsNullOrWhiteSpace(node.Name) ? throw new InvalidOperationException("Rail Route exposed a track node without a stable name") : node.Name;
    private static string ConnectionId(Game.Railroad.Connection connection) => string.Join("|", connection.EndPointGridPoints.Select(point => $"{point.x.ToString("R", CultureInfo.InvariantCulture)},{point.y.ToString("R", CultureInfo.InvariantCulture)}"));
    private static JsonValue Nullable(string? value) => string.IsNullOrWhiteSpace(value) ? JsonValue.Null() : JsonValue.String(value!);
    private static JsonValue Strings(IEnumerable<string> values) => JsonValue.Array(values.Where(value => !string.IsNullOrWhiteSpace(value)).Distinct(StringComparer.Ordinal).OrderBy(value => value, StringComparer.Ordinal).Select(JsonValue.String).ToArray());

    private static IReadOnlyList<ObservationSurfaceState> UnavailableSurfaces(string detail) => new[]
    {
        ObservationSurfaceState.Unavailable("incoming_traffic", detail),
        ObservationSurfaceState.Unavailable("platforms", detail),
        ObservationSurfaceState.Unavailable("routes", detail),
        ObservationSurfaceState.Unavailable("signals", detail),
        ObservationSurfaceState.Unavailable("stations", detail),
        ObservationSurfaceState.Unavailable("switches", detail),
        ObservationSurfaceState.Unavailable("track_occupancy", detail),
        ObservationSurfaceState.Unavailable("trains", detail),
    };

    private sealed class IncomingCandidate
    {
        internal IncomingCandidate(Game.Train.Train train, string source) { Train = train; Source = source; }
        internal Game.Train.Train Train { get; }
        internal string Source { get; }
    }

    private static string ArchitectureName(Architecture value) => value switch
    {
        Architecture.X64 => "x86_64",
        Architecture.Arm64 => "arm64",
        Architecture.X86 => "x86",
        Architecture.Arm => "arm",
        _ => value.ToString().ToLowerInvariant(),
    };
}
