"""Guards against reintroducing removed aliases and silent adapter fallback."""

import pytest

import sim_pilot.adapters as adapters
import sim_pilot.config as configuration
import sim_pilot.intent_compiler as intent_compiler
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
