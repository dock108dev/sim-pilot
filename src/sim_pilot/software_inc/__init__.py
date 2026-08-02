"""Frozen Software Inc. reference-integration boundary."""

from sim_pilot.software_inc.bridge import SoftwareIncBridgeInstaller
from sim_pilot.software_inc.discovery import SoftwareIncDiscovery
from sim_pilot.software_inc.errors import (
    SoftwareIncCompatibilityError,
    SoftwareIncDiscoveryError,
    SoftwareIncError,
    SoftwareIncProbeInstallError,
)
from sim_pilot.software_inc.probe import SoftwareIncProbeInstaller

__all__ = [
    "SoftwareIncCompatibilityError",
    "SoftwareIncBridgeInstaller",
    "SoftwareIncDiscovery",
    "SoftwareIncDiscoveryError",
    "SoftwareIncError",
    "SoftwareIncProbeInstallError",
    "SoftwareIncProbeInstaller",
]
