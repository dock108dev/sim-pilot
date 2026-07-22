"""Rail Route bridge installation, observation, and one-action boundary."""

from .actions import RailRouteSetRouteResult, execute_set_route
from .client import rail_route_bridge_client, rail_route_bridge_configuration
from .errors import (
    RailRouteBridgeActionError,
    RailRouteBridgeCompatibilityError,
    RailRouteBridgeError,
    RailRouteBridgeInstallError,
    RailRouteBridgeObservationError,
    RailRouteBridgeVerificationError,
)
from .installer import RailRouteBridgeInstaller
from .models import (
    BridgeCompatibilityReport,
    BridgeInstallManifest,
    BridgeInstallResult,
    BridgeReadOnlyProof,
)
from .proof import prove_read_only_bridge
from .query import entity_from, render_entity, render_surface, surface_from

__all__ = [
    "BridgeCompatibilityReport",
    "BridgeInstallManifest",
    "BridgeInstallResult",
    "BridgeReadOnlyProof",
    "RailRouteBridgeCompatibilityError",
    "RailRouteBridgeActionError",
    "RailRouteBridgeError",
    "RailRouteBridgeInstallError",
    "RailRouteBridgeObservationError",
    "RailRouteBridgeVerificationError",
    "RailRouteBridgeInstaller",
    "rail_route_bridge_client",
    "rail_route_bridge_configuration",
    "prove_read_only_bridge",
    "entity_from",
    "render_entity",
    "render_surface",
    "surface_from",
    "RailRouteSetRouteResult",
    "execute_set_route",
]
