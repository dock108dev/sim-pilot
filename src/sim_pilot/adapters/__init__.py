"""Generic simulation adapter contracts and capability schemas."""

from sim_pilot.adapters.base import (
    ActionDefinition,
    ActionParameterDefinition,
    ActionParameterType,
    AdapterSnapshot,
    SimulationAdapter,
)
from sim_pilot.adapters.openttd import OpenTTDReadOnlyAdapter, ReadOnlyValidation

__all__ = [
    "ActionDefinition",
    "ActionParameterDefinition",
    "ActionParameterType",
    "AdapterSnapshot",
    "SimulationAdapter",
    "OpenTTDReadOnlyAdapter",
    "ReadOnlyValidation",
]
