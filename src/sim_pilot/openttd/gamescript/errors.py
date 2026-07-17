"""Typed GameScript bridge failures."""

from sim_pilot.openttd.errors import OpenTTDError


class BridgeError(OpenTTDError):
    """Base failure for the production bridge."""


class BridgeUnavailableError(BridgeError):
    """No compatible GameScript bridge responded."""


class BridgeIncompatibleError(BridgeError):
    """The detected bridge does not satisfy protocol compatibility."""


class BridgeSequenceError(BridgeError):
    """Bridge ordering or identity continuity was lost."""


class BridgeCommandError(BridgeError):
    """A bridge command was rejected or failed."""
