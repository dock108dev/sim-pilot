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
