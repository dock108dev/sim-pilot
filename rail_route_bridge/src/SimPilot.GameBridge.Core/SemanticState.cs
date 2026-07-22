using System;
using System.Collections.Generic;

namespace SimPilot.GameBridge;

public sealed class ObservedEntityState
{
    public string EntityType { get; set; } = string.Empty;
    public string EntityId { get; set; } = string.Empty;
    public IReadOnlyDictionary<string, JsonValue> Values { get; set; } = new Dictionary<string, JsonValue>();
}

public sealed class ObservationSurfaceState
{
    public string Surface { get; set; } = string.Empty;
    public CoverageStatus Status { get; set; } = CoverageStatus.Unsupported;
    public string[] Fields { get; set; } = Array.Empty<string>();
    public string Detail { get; set; } = "field semantics have not been live-proven";
    public IReadOnlyList<ObservedEntityState> Entities { get; set; } = Array.Empty<ObservedEntityState>();

    public static ObservationSurfaceState Unsupported(string surface) => new() { Surface = surface };
    public static ObservationSurfaceState Unavailable(string surface, string detail) => new()
    {
        Surface = surface,
        Status = CoverageStatus.Unavailable,
        Detail = detail,
    };
}

public sealed class SetRouteActionRequest
{
    public string OriginSignal { get; set; } = string.Empty;
    public string DestinationSignal { get; set; } = string.Empty;
    public string ExpectedBridgeInstanceId { get; set; } = string.Empty;
    public string ExpectedGameSessionId { get; set; } = string.Empty;
    public long ExpectedSnapshotSequence { get; set; }
}

public sealed class SetRouteActionResult
{
    public string Outcome { get; set; } = "rejected";
    public bool Executed { get; set; }
    public string OriginSignal { get; set; } = string.Empty;
    public string DestinationSignal { get; set; } = string.Empty;
    public string? DestinationConnection { get; set; }
    public string ReasonCode { get; set; } = "internal_error";
    public string Detail { get; set; } = "route request failed closed";

    public static SetRouteActionResult Rejected(SetRouteActionRequest request, string reasonCode, string detail) => new()
    {
        OriginSignal = request.OriginSignal,
        DestinationSignal = request.DestinationSignal,
        ReasonCode = reasonCode,
        Detail = detail,
    };
}

public interface IGameActionProvider
{
    SetRouteActionResult SubmitSetRoute(SetRouteActionRequest request, TimeSpan timeout);
}
