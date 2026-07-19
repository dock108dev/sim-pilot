"""Generic simulation adapter contracts and capability schemas."""

from sim_pilot.adapters.base import (
    ActionDefinition,
    ActionParameterDefinition,
    ActionParameterType,
    AdapterSnapshot,
    SimulationAdapter,
)
from sim_pilot.adapters.openttd import OpenTTDAdapter, OpenTTDValidation

__all__ = [
    "ActionDefinition",
    "ActionParameterDefinition",
    "ActionParameterType",
    "AdapterSnapshot",
    "SimulationAdapter",
    "OpenTTDAdapter",
    "OpenTTDValidation",
]
