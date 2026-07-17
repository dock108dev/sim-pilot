"""Verified OpenTTD adapter."""

from sim_pilot.adapters.openttd.adapter import (
    OpenTTDAdapter,
    OpenTTDReadOnlyAdapter,
    OpenTTDValidation,
    SetCompanyNameOpenTTDAction,
    SetServerNameOpenTTDAction,
)

__all__ = [
    "OpenTTDAdapter",
    "OpenTTDReadOnlyAdapter",
    "OpenTTDValidation",
    "SetCompanyNameOpenTTDAction",
    "SetServerNameOpenTTDAction",
]
