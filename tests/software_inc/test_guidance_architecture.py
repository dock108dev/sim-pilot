"""Guided-operator architecture and capability-boundary tests."""

from __future__ import annotations

from pathlib import Path

from sim_pilot.guidance import CapabilityEvidenceStage
from sim_pilot.software_inc.guidance.state import project_state
from tests.software_inc.guidance_helpers import guidance_context, snapshot


def test_game_neutral_guidance_contracts_do_not_import_game_adapters() -> None:
    source = Path("src/sim_pilot/guidance/models.py").read_text(encoding="utf-8")

    assert "sim_pilot.software_inc" not in source
    assert "sim_pilot.openttd" not in source
    assert "sim_pilot.rail_route" not in source


def test_read_only_services_cannot_import_ui_execution() -> None:
    guidance_root = Path("src/sim_pilot/software_inc/guidance")
    for name in ("knowledge.py", "state.py", "capabilities.py", "context.py", "read_service.py"):
        source = (guidance_root / name).read_text(encoding="utf-8")
        assert ".ui.controller" not in source
        assert "execute_ui_action" not in source
        assert "execute_staffing_intent" not in source

    delegation = (guidance_root / "delegation.py").read_text(encoding="utf-8")
    assert "execute_ui_action" in delegation


def test_current_state_projection_is_deterministic_and_financially_bounded() -> None:
    observed = snapshot(empty_support_team=False)

    first = project_state(observed)
    second = project_state(observed)

    assert first == second
    assert first.company_name == "Fixture Labs"
    assert first.cash is not None and str(first.cash) == "100000"
    assert first.recurring_payroll is not None and str(first.recurring_payroll) == "6200"
    assert first.teams_complete is True
    assert first.employees_complete is True
    assert first.finances_partial is True


def test_unified_capability_view_never_promotes_phase4_from_offline_tests() -> None:
    view = guidance_context().capabilities
    actions = {item.action: item for item in view.actions}

    assert view.semantic_gameplay_actions == ()
    assert view.generic_task_runtime_available is False
    assert actions["pause"].evidence_stage is CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
    assert actions["pause"].compatible is True
    for action in ("create_team", "observe_applicants", "hire_employee"):
        assert actions[action].evidence_stage is CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED
        assert actions[action].live_verified is False
        assert actions[action].approval_required is True

    for action in (
        "open_contracts",
        "accept_contract",
        "advance_contract",
        "review_contract",
        "promote_contract",
        "release_contract",
    ):
        assert actions[action].evidence_stage is CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
        assert actions[action].live_verified is True


def test_bridge_artifact_mismatch_disables_current_execution_without_erasing_history() -> None:
    view = guidance_context(artifact_matches=False).capabilities

    assert all(action.compatible is False for action in view.actions)
    assert any("differs" in limitation for limitation in view.limitations)
    assert next(action for action in view.actions if action.action == "pause").live_verified is True


def test_guidance_has_no_paid_provider_or_runtime_network_dependency() -> None:
    root = Path("src/sim_pilot/software_inc/guidance")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))

    assert "OpenAI" not in source
    assert "CodexCLI" not in source
    assert "requests" not in source
    assert "httpx" not in source
