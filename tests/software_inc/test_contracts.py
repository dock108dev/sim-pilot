"""Prompt 6A contract observation, policy, approval, and persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from sim_pilot.game_bridge import (
    Architecture,
    CoverageStatus,
    FieldCoverage,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
)
from sim_pilot.software_inc.contracts.intent import (
    ContractIntentAction,
    parse_contract_intent,
)
from sim_pilot.software_inc.contracts.models import (
    ContractCommitment,
    ContractStage,
    ContractWorkflowStatus,
)
from sim_pilot.software_inc.contracts.policy import assess_contract, recommend_contracts
from sim_pilot.software_inc.contracts.projection import (
    active_contract_work,
    available_contracts,
)
from sim_pilot.software_inc.contracts.store import ContractWorkflowStore, store_is_owner_only
from sim_pilot.software_inc.contracts.workflow import (
    approval_for,
    create_workflow,
    resolve_approval,
    synchronize_workflow,
)
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError


def _surface(
    name: str,
    entities: tuple[ObservedEntity, ...] = (),
    *,
    status: CoverageStatus = CoverageStatus.OBSERVED_COMPLETE,
) -> ObservationSurface:
    return ObservationSurface(
        coverage=FieldCoverage(surface=name, status=status, fields=()), entities=entities
    )


def _snapshot(
    sequence: int = 1,
    *,
    reward: float = 12_000,
    penalty: float = 2_000,
    completion_months: int = 2,
    development_time: float = 1,
    active: bool = False,
) -> GameSnapshot:
    contract = ObservedEntity(
        entity_type="available_contract",
        entity_id="Acme|Utility Software|0-2026",
        values={
            "added": "January 2026",
            "art_ratio": 0.2,
            "client": "Acme",
            "deadline": "00:00 January 1900",
            "days_remaining": -1512.0,
            "dev_time": development_time,
            "difficulty": 0.15,
            "display_index": 0,
            "features": "Networking|UI",
            "minimum_progress": 1.0,
            "months": completion_months,
            "name": "Utility Software",
            "penalty": penalty,
            "per_bug_penalty": 100.0,
            "quality_target": 0.5,
            "reward": reward,
            "software_category": "Business",
            "software_type": "Utility Software",
            "status": "Available",
        },
    )
    employees = tuple(
        ObservedEntity(
            entity_type="employee",
            entity_id=str(index),
            values={
                "dismissed": False,
                "name": role,
                "role": role,
                "team": "Core",
            },
        )
        for index, role in enumerate(("Designer", "Programmer", "Artist"), start=1)
    )
    work_items: tuple[ObservedEntity, ...] = ()
    if active:
        work_items = (
            ObservedEntity(
                entity_type="work_item",
                entity_id="42",
                values={
                    "assigned_teams": "Core",
                    "bugs": 4.0,
                    "contract_client": "Acme",
                    "contract_days_remaining": 35.0,
                    "contract_deadline": "March 2026",
                    "contract_identity": contract.entity_id,
                    "contract_name": "Utility Software",
                    "contract_penalty": penalty,
                    "contract_reward": reward,
                    "done": False,
                    "employee_count": 3,
                    "fixed_bugs": 1.0,
                    "in_beta": False,
                    "is_contract": True,
                    "minimum_progress": 1.0,
                    "paused": False,
                    "progress": 0.4,
                    "released": False,
                    "stage": "Alpha",
                    "work_type": "Software Alpha",
                },
            ),
        )
    surfaces = (
        _surface("contract_market", (contract,)),
        _surface("contract_results"),
        _surface("contract_ui"),
        _surface(
            "teams",
            (
                ObservedEntity(
                    entity_type="team",
                    entity_id="Core",
                    values={"employee_count": 3, "name": "Core"},
                ),
            ),
        ),
        _surface("employees", employees),
        _surface(
            "offices",
            (
                ObservedEntity(
                    entity_type="office_room",
                    entity_id="room-1",
                    values={"assigned_teams": "Core", "valid_workstations": 3},
                ),
            ),
        ),
        _surface(
            "finances",
            (
                ObservedEntity(
                    entity_type="company_finances",
                    entity_id="company",
                    values={"cash": 100_000.0},
                ),
            ),
            status=CoverageStatus.OBSERVED_PARTIAL,
        ),
        _surface("work_items", work_items),
    )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=sequence,
        bridge_instance_id="bridge",
        game_session_id="session",
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v5",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="not applicable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value="contract-test"),
        game_state={"days_per_month": 20, "force_pause": True, "simulation_speed": "0"},
        surfaces=tuple(sorted(surfaces, key=lambda item: item.coverage.surface)),
    )


def test_contract_projection_and_recommendation_are_complete_and_bounded() -> None:
    snapshot = _snapshot()

    contracts = available_contracts(snapshot)
    recommendation = recommend_contracts(
        snapshot,
        team_name="Core",
        minimum_reward=Decimal("10000"),
        minimum_cash_reserve=Decimal("50000"),
    )

    assert len(contracts) == 1
    assert contracts[0].features == ("Networking", "UI")
    assert contracts[0].deadline == "2 in-game months after work starts (40 in-game days)"
    assert contracts[0].days_remaining == Decimal("40")
    assert recommendation.recommended is not None
    assert recommendation.recommended.team.suitable
    assert recommendation.recommended.team.deadline_buffer_days == Decimal("20.0")
    assert len(recommendation.alternatives) <= 2


def test_contract_store_index_columns_follow_the_canonical_workflow_body(
    tmp_path: Path,
) -> None:
    first = _snapshot(sequence=1)
    recommendation = recommend_contracts(
        first,
        team_name="Core",
        minimum_reward=Decimal("10000"),
        minimum_cash_reserve=Decimal("50000"),
    )
    assert recommendation.recommended is not None
    workflow = create_workflow(first, recommendation.recommended)
    store = ContractWorkflowStore(tmp_path / "workflows.sqlite3")
    store.save(workflow)

    rebound = workflow.model_copy(
        update={
            "game_session_id": "replacement-session",
            "last_bridge_sequence": 2,
            "updated_at": datetime.now(UTC),
        }
    )
    store.save(rebound)

    assert (
        store.current(
            game_session_id="replacement-session",
            save_identity=rebound.save_identity,
        )
        == rebound
    )
    assert (
        store.current(
            game_session_id=workflow.game_session_id,
            save_identity=workflow.save_identity,
        )
        is None
    )


def test_waiting_contract_retains_relative_deadline_until_work_starts() -> None:
    available = _snapshot(sequence=1)
    recommendation = recommend_contracts(
        available,
        team_name="Core",
        minimum_reward=Decimal("10000"),
        minimum_cash_reserve=Decimal("50000"),
    )
    assert recommendation.recommended is not None
    workflow = create_workflow(available, recommendation.recommended)
    active = _snapshot(sequence=2, active=True)
    surfaces: list[ObservationSurface] = []
    for surface in active.surfaces:
        if surface.coverage.surface == "work_items":
            waiting = surface.entities[0].model_copy(
                update={
                    "values": {
                        **surface.entities[0].values,
                        "contract_deadline": "00:00 January 1900",
                        "contract_days_remaining": -1512.0,
                        "contract_started": False,
                        "stage": "Waiting",
                        "work_type": "Design",
                    }
                }
            )
            surface = surface.model_copy(update={"entities": (waiting,)})
        surfaces.append(surface)
    waiting_snapshot = active.model_copy(update={"surfaces": tuple(surfaces)})

    item = active_contract_work(waiting_snapshot)[0]
    synchronized = synchronize_workflow(workflow, waiting_snapshot)

    assert item.contract_started is False
    assert synchronized.deadline == "2 in-game months after work starts (40 in-game days)"


def test_unavailable_active_deadline_never_exposes_the_1900_sentinel() -> None:
    available = _snapshot(sequence=1)
    recommendation = recommend_contracts(
        available,
        team_name="Core",
        minimum_reward=Decimal("10000"),
        minimum_cash_reserve=Decimal("50000"),
    )
    assert recommendation.recommended is not None
    workflow = create_workflow(available, recommendation.recommended)
    active = _snapshot(sequence=2, active=True)
    surfaces: list[ObservationSurface] = []
    for surface in active.surfaces:
        if surface.coverage.surface == "work_items":
            unavailable = surface.entities[0].model_copy(
                update={
                    "values": {
                        **surface.entities[0].values,
                        "contract_deadline": "",
                        "contract_deadline_observed": False,
                        "contract_days_remaining": 0.0,
                        "contract_started": True,
                    }
                }
            )
            surface = surface.model_copy(update={"entities": (unavailable,)})
        surfaces.append(surface)
    active = active.model_copy(update={"surfaces": tuple(surfaces)})

    item = active_contract_work(active)[0]
    synchronized = synchronize_workflow(workflow, active)

    assert item.deadline == ""
    assert item.deadline_observed is False
    assert item.days_remaining == 0
    assert "1900" not in synchronized.deadline
    assert synchronized.deadline == "2 in-game months after work starts (40 in-game days)"


def test_any_role_founder_contributes_each_observed_positive_skill() -> None:
    snapshot = _snapshot()
    founder = ObservedEntity(
        entity_type="employee",
        entity_id="founder",
        values={
            "dismissed": False,
            "name": "Founder",
            "role": "Any role",
            "skill_artist": 0.5,
            "skill_designer": 0.5,
            "skill_lead": 0.5,
            "skill_programmer": 0.5,
            "skill_service": 0.5,
            "team": "Core",
        },
    )
    surfaces: list[ObservationSurface] = []
    for surface in snapshot.surfaces:
        if surface.coverage.surface == "employees":
            surface = surface.model_copy(update={"entities": (founder,)})
        elif surface.coverage.surface == "teams":
            team = surface.entities[0].model_copy(
                update={"values": {"employee_count": 1, "name": "Core"}}
            )
            surface = surface.model_copy(update={"entities": (team,)})
        elif surface.coverage.surface == "offices":
            room = surface.entities[0].model_copy(
                update={"values": {"assigned_teams": "Core", "valid_workstations": 1}}
            )
            surface = surface.model_copy(update={"entities": (room,)})
        surfaces.append(surface)
    snapshot = snapshot.model_copy(update={"surfaces": tuple(surfaces)})

    recommendation = recommend_contracts(
        snapshot,
        team_name="Core",
        minimum_reward=Decimal("0"),
    )

    assert recommendation.recommended is not None
    assert recommendation.recommended.team.observed_roles == (
        "Artist",
        "Designer",
        "Lead",
        "Programmer",
        "Service",
    )


@pytest.mark.parametrize(
    ("reward", "penalty", "completion_months", "development_time", "expected"),
    (
        (9_999, 2_000, 2, 1, "below the requested"),
        (12_000, 60_000, 2, 1, "below the $50,000.00 reserve"),
        (12_000, 2_000, 1, 2, "conservative budget"),
    ),
)
def test_recommendation_rejects_reward_runway_and_deadline_risk(
    reward: float,
    penalty: float,
    completion_months: int,
    development_time: float,
    expected: str,
) -> None:
    snapshot = _snapshot(
        reward=reward,
        penalty=penalty,
        completion_months=completion_months,
        development_time=development_time,
    )
    recommendation = recommend_contracts(
        snapshot,
        team_name="Core",
        minimum_reward=Decimal("10000"),
        minimum_cash_reserve=Decimal("50000"),
    )
    assessment = assess_contract(
        snapshot,
        available_contracts(snapshot)[0],
        team_name="Core",
        minimum_reward=Decimal("10000"),
        minimum_cash_reserve=Decimal("50000"),
    )

    assert recommendation.recommended is None
    assert expected in " ".join(assessment.reasons)
    assert expected in " ".join(recommendation.rejection_reasons)


def test_contract_workflow_uses_distinct_commitment_approvals_and_fresh_sync() -> None:
    recommendation = recommend_contracts(
        _snapshot(), team_name="Core", minimum_reward=Decimal("10000")
    )
    assert recommendation.recommended is not None
    workflow = create_workflow(_snapshot(), recommendation.recommended)
    assert workflow.pending_approval is not None
    assert workflow.pending_approval.commitment is ContractCommitment.ACCEPT

    approved = resolve_approval(workflow, approved=True)
    synchronized = synchronize_workflow(approved, _snapshot(2, active=True))
    promotion = approval_for(synchronized, ContractCommitment.PROMOTE)
    release = approval_for(synchronized, ContractCommitment.RELEASE)

    assert synchronized.status is ContractWorkflowStatus.ACTIVE
    assert synchronized.observed_stage is ContractStage.ALPHA
    assert promotion.approval_id != release.approval_id
    assert promotion.commitment is ContractCommitment.PROMOTE
    assert release.commitment is ContractCommitment.RELEASE
    with pytest.raises(SoftwareIncUIValidationError, match="fresh bridge sequence"):
        synchronize_workflow(synchronized, _snapshot(2, active=True))


def test_contract_store_is_durable_owner_only_and_duplicate_safe(tmp_path: Path) -> None:
    recommendation = recommend_contracts(
        _snapshot(), team_name="Core", minimum_reward=Decimal("10000")
    )
    assert recommendation.recommended is not None
    workflow = create_workflow(_snapshot(), recommendation.recommended)
    store = ContractWorkflowStore(tmp_path / "private" / "contracts.sqlite3")

    store.save(workflow)

    assert store.get(workflow.workflow_id) == workflow
    assert (
        store.current(
            game_session_id=workflow.game_session_id, save_identity=workflow.save_identity
        )
        == workflow
    )
    assert store_is_owner_only(store.path)

    conflicting = workflow.model_copy(
        update={"workflow_id": uuid4(), "contract_id": "another-contract"}
    )
    with pytest.raises(SoftwareIncUIValidationError, match="another open contract workflow"):
        store.save(conflicting)

    completed = workflow.model_copy(
        update={
            "status": ContractWorkflowStatus.COMPLETED,
            "completed_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    store.save(completed)
    assert (
        store.current(
            game_session_id=workflow.game_session_id, save_identity=workflow.save_identity
        )
        is None
    )
    assert (
        store.latest(game_session_id=workflow.game_session_id, save_identity=workflow.save_identity)
        == completed
    )


def test_contract_market_must_be_complete() -> None:
    snapshot = _snapshot().model_copy(
        update={
            "surfaces": tuple(
                surface.model_copy(
                    update={
                        "coverage": surface.coverage.model_copy(
                            update={"status": CoverageStatus.UNAVAILABLE, "detail": "closed"}
                        )
                    }
                )
                if surface.coverage.surface == "contract_market"
                else surface
                for surface in _snapshot().surfaces
            )
        }
    )

    with pytest.raises(SoftwareIncUIValidationError, match="not completely observed"):
        available_contracts(snapshot)


def test_active_work_does_not_require_or_manufacture_five_bugs() -> None:
    work = active_contract_work(_snapshot(active=True))

    assert len(work) == 1
    assert work[0].bugs == Decimal("4.0")
    assert work[0].fixed_bugs == Decimal("1.0")


def test_plain_english_contract_intent_preserves_exact_constraints() -> None:
    intent = parse_contract_intent(
        "find a small contract for Core with reward at least $10,000 "
        "while keeping $50,000 in reserve"
    )

    assert intent.action is ContractIntentAction.RECOMMEND
    assert intent.team_name == "Core"
    assert intent.minimum_reward == Decimal("10000.00")
    assert intent.minimum_cash_reserve == Decimal("50000.00")
    assert (
        parse_contract_intent("review the current contract").action is ContractIntentAction.REVIEW
    )


def test_plain_english_contract_intent_rejects_ambiguous_pronouns() -> None:
    with pytest.raises(SoftwareIncUIValidationError, match="exact team and reward floor"):
        parse_contract_intent("accept it")


def test_review_approval_binds_cost_and_configuration() -> None:
    recommendation = recommend_contracts(
        _snapshot(), team_name="Core", minimum_reward=Decimal("10000")
    )
    assert recommendation.recommended is not None
    workflow = create_workflow(_snapshot(), recommendation.recommended)

    approval = approval_for(
        workflow,
        ContractCommitment.REVIEW,
        one_time_cost=Decimal("1250"),
        configuration="mode=client, review_count=5",
    )

    assert approval.one_time_cost == Decimal("1250")
    assert approval.configuration == "mode=client, review_count=5"
    assert "$1,250.00" in approval.action_summary
