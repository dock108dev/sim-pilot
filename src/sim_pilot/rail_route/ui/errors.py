"""Typed Rail Route UI failures."""

from sim_pilot.rail_route.errors import RailRouteError


class RailRouteUIError(RailRouteError):
    """Base UI-controller failure."""


class RailRouteUIObservationError(RailRouteUIError):
    """A synchronized, actionable UI state could not be proven."""


class RailRouteUIVerificationError(RailRouteUIError):
    """An input was sent but its intended effect was not proven."""
