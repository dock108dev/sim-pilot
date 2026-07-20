"""Guards against reintroducing removed aliases and silent adapter fallback."""

from inspect import signature

import pytest

import sim_pilot.adapters as adapters
import sim_pilot.config as configuration
import sim_pilot.intent_compiler as intent_compiler
from sim_pilot.adapters.base import AdapterValidation, SimulationAdapter
from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.analysis.output import render_analysis
from sim_pilot.intent_compiler.prompt import (
    OPENTTD_CAPABILITIES,
    REFERENCE_CAPABILITIES,
    capability_catalog,
)


def test_removed_compatibility_symbols_are_not_public() -> None:
    assert not hasattr(adapters, "OpenTTDReadOnlyAdapter")
    assert not hasattr(intent_compiler, "CompilerProviderMetadata")
    assert not hasattr(intent_compiler, "CompilerTokenUsage")
    assert not hasattr(configuration, "AppConfiguration")


def test_adapter_catalog_routing_is_explicit_and_fail_closed() -> None:
    assert capability_catalog("reference") is REFERENCE_CAPABILITIES
    assert capability_catalog("openttd") is OPENTTD_CAPABILITIES
    with pytest.raises(ValueError, match="unsupported adapter type"):
        capability_catalog("unknown")


def test_adapter_refresh_and_staleness_policy_is_an_explicit_contract() -> None:
    assert "requires_fresh_observation_on_resume" in SimulationAdapter.__annotations__
    assert "state_stale" in AdapterValidation.__annotations__
    assert ReferenceSimulationAdapter.requires_fresh_observation_on_resume is False
    assert OpenTTDAdapter.requires_fresh_observation_on_resume is True


def test_renderer_has_no_parallel_snapshot_freshness_inputs() -> None:
    parameters = signature(render_analysis).parameters
    assert "snapshot_age_seconds" not in parameters
    assert "cached" not in parameters
