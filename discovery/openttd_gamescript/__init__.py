"""Task 7A GameScript discovery support; not a production adapter."""

from discovery.openttd_gamescript.protocol import (
    BridgeCapabilities,
    BridgeEnvelope,
    DuplicateTracker,
    MessageType,
)

__all__ = ["BridgeCapabilities", "BridgeEnvelope", "DuplicateTracker", "MessageType"]
