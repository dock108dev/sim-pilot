"""Typed failures for the game-neutral bridge protocol."""


class GameBridgeError(RuntimeError):
    """Base failure for a game bridge client."""


class GameBridgeConnectionError(GameBridgeError):
    """The loopback bridge could not be reached or disconnected."""


class GameBridgeTimeoutError(GameBridgeError):
    """A bounded bridge operation timed out."""


class GameBridgeAuthenticationError(GameBridgeError):
    """The bridge rejected local client authentication."""


class GameBridgeProtocolError(GameBridgeError):
    """A bridge message violated the negotiated protocol."""


class GameBridgeIncompatibleError(GameBridgeProtocolError):
    """The bridge identity or version is incompatible with this client."""


class GameBridgeSequenceError(GameBridgeProtocolError):
    """Message ordering, duplication, or identity continuity was lost."""


class GameBridgeMessageSizeError(GameBridgeProtocolError):
    """A framed bridge message exceeded the configured limit."""


class GameBridgeSnapshotError(GameBridgeProtocolError):
    """A snapshot was incomplete, stale, or internally inconsistent."""
