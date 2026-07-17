"""Supported OpenTTD Admin Network integration."""

from sim_pilot.openttd.client import OpenTTDAdminClient
from sim_pilot.openttd.config import OpenTTDConfiguration, openttd_configuration
from sim_pilot.openttd.errors import (
    OpenTTDConnectionRefusedError,
    OpenTTDDisconnectedError,
    OpenTTDError,
    OpenTTDExecutableUnavailableError,
    OpenTTDInvalidResponseError,
    OpenTTDProtocolMismatchError,
    OpenTTDRequiredScriptUnavailableError,
    OpenTTDStateUnavailableError,
    OpenTTDTimeoutError,
    OpenTTDUnsupportedVersionError,
)
from sim_pilot.openttd.models import (
    OpenTTDAdapterCapabilities,
    OpenTTDAdapterMetadata,
    OpenTTDClient,
    OpenTTDCompanyState,
    OpenTTDConnectionMetadata,
    OpenTTDObservationState,
    OpenTTDResourceMapping,
    OpenTTDState,
)

__all__ = [
    "OpenTTDAdminClient",
    "OpenTTDAdapterCapabilities",
    "OpenTTDAdapterMetadata",
    "OpenTTDClient",
    "OpenTTDCompanyState",
    "OpenTTDConfiguration",
    "OpenTTDConnectionMetadata",
    "OpenTTDConnectionRefusedError",
    "OpenTTDDisconnectedError",
    "OpenTTDError",
    "OpenTTDExecutableUnavailableError",
    "OpenTTDInvalidResponseError",
    "OpenTTDProtocolMismatchError",
    "OpenTTDRequiredScriptUnavailableError",
    "OpenTTDResourceMapping",
    "OpenTTDObservationState",
    "OpenTTDState",
    "OpenTTDStateUnavailableError",
    "OpenTTDTimeoutError",
    "OpenTTDUnsupportedVersionError",
    "openttd_configuration",
]
