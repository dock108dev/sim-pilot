"""Typed failures for the Rail Route semantic bridge lifecycle."""

from sim_pilot.rail_route.errors import RailRouteError


class RailRouteBridgeError(RailRouteError):
    """Base failure for bridge configuration, installation, or communication."""


class RailRouteBridgeCompatibilityError(RailRouteBridgeError):
    """The local game or bridge artifact is not the exact supported target."""


class RailRouteBridgeInstallError(RailRouteBridgeError):
    """A reversible installation operation could not be completed safely."""


class RailRouteBridgeObservationError(RailRouteBridgeError):
    """A requested semantic surface or entity is unavailable or ambiguous."""


class RailRouteBridgeActionError(RailRouteBridgeError):
    """A semantic gameplay action failed deterministic validation."""


class RailRouteBridgeVerificationError(RailRouteBridgeActionError):
    """One action was executed but its fresh snapshot postcondition failed."""
