"""Single-source adapter availability and authority tests."""

import pytest

from sim_pilot.adapter_registry import adapter_registration, adapter_registrations
from sim_pilot.domain import AdapterId
from sim_pilot.intent_compiler.prompt import capability_catalog


def test_software_inc_is_frozen_reference_with_read_only_observation() -> None:
    registration = adapter_registration(AdapterId.SOFTWARE_INC)

    assert registration.flagship is False
    assert registration.frozen_reference is True
    assert registration.display_name == "Software Inc. frozen reference integration"
    assert registration.discovery_available is True
    assert registration.runtime_factory_available is False
    assert registration.observation_available is True
    assert registration.reconciliation_available is False
    assert registration.direct_ui_actions == ("open_manage_teams", "pause", "resume")
    assert registration.advertised_actions == ()
    assert capability_catalog("software_inc").actions == ()
    assert capability_catalog("software_inc").resources == ()


def test_every_known_adapter_has_one_registration_and_unknown_fails() -> None:
    registrations = adapter_registrations()

    assert {item.adapter_id for item in registrations} == set(AdapterId)
    assert sum(item.flagship for item in registrations) == 0
    assert sum(item.frozen_reference for item in registrations) == 1
    with pytest.raises(ValueError, match="unsupported adapter type"):
        adapter_registration("invented")
