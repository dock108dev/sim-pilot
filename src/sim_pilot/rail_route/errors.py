"""Typed Rail Route control failures."""


class RailRouteError(RuntimeError):
    """Base error for the local Rail Route boundary."""


class RailRouteDiscoveryError(RailRouteError):
    """Rail Route is missing, stopped, or incompatible."""


class RailRouteObservationError(RailRouteError):
    """The current game state cannot be observed reliably."""


class RailRouteIntentError(RailRouteError):
    """Natural-language input is unsupported or ambiguous."""


class RailRouteVerificationError(RailRouteError):
    """An input was sent but its intended effect was not observed."""
