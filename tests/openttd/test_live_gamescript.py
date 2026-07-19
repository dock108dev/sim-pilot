"""Explicitly gated live acceptance tests for the production GameScript bridge."""

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.domain.models import JsonValue
from sim_pilot.openttd import OpenTTDAdminClient, openttd_configuration
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.models import SynchronizationState
from sim_pilot.openttd.models import OpenTTDObservationState
from sim_pilot.persistence.sqlite import SQLiteUnitOfWork, create_sqlite_engine, upgrade_database
from sim_pilot.reconciliation import default_reconciliation_dispatcher
from sim_pilot.runtime import ReconciliationClassification, RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.action_attempts import RecoveryResolution
from sim_pilot.runtime.errors import SimulatedCrash
from sim_pilot.runtime.recovery import CrashPoint
from tests.runtime.helpers import make_task


def _require_live_bridge() -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD_GS") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD_GS=1 for the disposable OpenTTD server")


@pytest.mark.live
def test_live_bridge_snapshot_and_process_reconnect_preserve_identity() -> None:
    _require_live_bridge()

    async def synchronize_once() -> tuple[str | None, int, int, int, str, tuple[str, ...]]:
        configuration = openttd_configuration()
        admin = OpenTTDAdminClient(configuration)
        bridge = GameScriptBridgeClient(admin, company_id=configuration.company_id)
        adapter = OpenTTDAdapter(admin, bridge=bridge)
        await adapter.initialize()
        try:
            observation = await adapter.observe()
            assert bridge.health.synchronization_state is SynchronizationState.SYNCHRONIZED
            assert bridge.health.snapshot is not None
            assert bridge.health.snapshot.town_count >= 1
            assert bridge.health.world_snapshot is not None
            assert bridge.health.world_snapshot.complete is True
            assert bridge.health.capabilities is not None
            assert bridge.health.capability_fingerprint == bridge.health.capabilities.fingerprint
            capability_fingerprint = bridge.health.capability_fingerprint
            assert capability_fingerprint is not None
            state = OpenTTDObservationState.model_validate_json(json.dumps(observation.state))
            assert state.world is not None
            assert len(state.world.towns) == bridge.health.snapshot.town_count
            follow_up = OpenTTDObservationState.model_validate_json(
                json.dumps((await adapter.observe()).state)
            )
            assert follow_up.world is not None
            assert follow_up.world.changes_from_snapshot_id == state.world.metadata.snapshot_id
            assert tuple(town.id for town in follow_up.world.towns) == tuple(
                town.id for town in state.world.towns
            )
            return (
                bridge.health.script_instance_id,
                bridge.health.last_sequence or 0,
                observation.tick,
                bridge.health.snapshot.save_generation,
                capability_fingerprint,
                tuple(town.id for town in follow_up.world.towns),
            )
        finally:
            await adapter.shutdown()

    first = asyncio.run(synchronize_once())
    second = asyncio.run(synchronize_once())
    assert second[0] == first[0]
    assert second[1] > first[1]
    assert second[2] >= first[2]
    assert second[3] == first[3]
    assert second[4] == first[4]
    assert second[5] == first[5]


@pytest.mark.live
def test_live_bridge_company_name_action_is_verified_and_restored() -> None:
    _require_live_bridge()
    if os.getenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES") != "1":
        pytest.skip("set SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1 for the disposable server")

    async def scenario() -> None:
        configuration = openttd_configuration()
        admin = OpenTTDAdminClient(configuration)
        bridge = GameScriptBridgeClient(
            admin,
            company_id=configuration.company_id,
            allow_writes=True,
        )
        adapter = OpenTTDAdapter(admin, bridge=bridge, allow_gamescript_writes=True)
        await adapter.initialize()
        try:
            before = await adapter.observe()
            resources = OpenTTDObservationState.model_validate_json(
                json.dumps(before.state)
            ).resources
            original = resources.company_name
            assert isinstance(original, str)
            temporary = "Sim Pilot Task 7B Live"
            action = Action(
                type="set_company_name",
                parameters={"name": temporary},
                expected_effect="Set and independently observe the company name.",
            )
            assert (await adapter.validate(action)).valid
            assert (await adapter.execute(action)).success
            changed = await adapter.observe()
            changed_resources = OpenTTDObservationState.model_validate_json(
                json.dumps(changed.state)
            ).resources
            assert changed_resources.company_name == temporary
            restore = action.model_copy(update={"parameters": {"name": original}})
            assert (await adapter.execute(restore)).success
            restored = await adapter.observe()
            restored_resources = OpenTTDObservationState.model_validate_json(
                json.dumps(restored.state)
            ).resources
            assert restored_resources.company_name == original
        finally:
            await adapter.shutdown()

    asyncio.run(scenario())


@pytest.mark.live
def test_live_company_name_crash_reconciles_and_resumes_without_retry(tmp_path: Path) -> None:
    _require_live_bridge()
    if os.getenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES") != "1":
        pytest.skip("set SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=1 for the disposable server")

    def crasher(point: CrashPoint) -> None:
        if point is CrashPoint.AFTER_EXECUTION:
            raise SimulatedCrash(point.value)

    def runtime(hook: Callable[[CrashPoint], None] | None = None) -> tuple[Engine, RuntimeEngine]:
        url = f"sqlite:///{tmp_path / 'live-company-crash.db'}"
        upgrade_database(url)
        engine = create_sqlite_engine(url)
        return engine, RuntimeEngine(
            unit_of_work_factory=lambda: SQLiteUnitOfWork(engine),
            crash_hook=hook,
            reconciliation_dispatcher=default_reconciliation_dispatcher(),
        )

    def adapter() -> OpenTTDAdapter:
        configuration = openttd_configuration()
        admin = OpenTTDAdminClient(configuration)
        bridge = GameScriptBridgeClient(
            admin,
            company_id=configuration.company_id,
            allow_writes=True,
        )
        return OpenTTDAdapter(admin, bridge=bridge, allow_gamescript_writes=True)

    async def scenario() -> None:
        probe = adapter()
        await probe.initialize()
        before = await probe.observe()
        original = OpenTTDObservationState.model_validate_json(
            json.dumps(before.state)
        ).resources.company_name
        await probe.shutdown()
        assert isinstance(original, str)
        target = "Sim Pilot Recovery 7.6"
        if original == target:
            target = "Sim Pilot Recovery 7.6 B"
        task = make_task(
            specification=TaskSpecification(
                adapter_type="openttd",
                objective=Objective(
                    type=ObjectiveType.RUN_UNTIL,
                    description="Set the crash-test company name.",
                    parameters={
                        "resource": "company_name",
                        "target": target,
                        "direction": "equal",
                    },
                ),
                authority=AuthorityPolicy(),
            )
        )
        decision = Decision(
            type=DecisionType.EXECUTE,
            reason="Execute once before the injected crash.",
            action=Action(
                type="set_company_name",
                parameters={"name": target},
                expected_effect="Set and re-observe the company name.",
            ),
        )
        engine, first_runtime = runtime(crasher)
        with pytest.raises(SimulatedCrash):
            await first_runtime.run(task, adapter(), ScriptedDecisionProvider([decision]))
        engine.dispose()

        fresh = adapter()
        await fresh.initialize()
        fresh_observation = await fresh.observe()
        current = AdapterSnapshot(
            adapter_type="openttd",
            simulation_schema_version=1,
            observation_sequence=fresh_observation.sequence,
            seed="0",
            state=cast("dict[str, JsonValue]", fresh_observation.state),
        )
        await fresh.shutdown()
        engine2, second_runtime = runtime()
        report = await second_runtime.inspect_recovery(task.id, current)
        assert report is not None
        assert report.classification is ReconciliationClassification.DEFINITELY_EXECUTED
        await second_runtime.resolve_recovery(
            task.id,
            RecoveryResolution.MARK_EXECUTED,
            current_snapshot=current,
        )
        outcome = await second_runtime.resume(
            task.id,
            lambda context: adapter(),
            ScriptedDecisionProvider([]),
            iteration_budget=1,
        )
        assert outcome.status is TaskStatus.COMPLETED
        engine2.dispose()

        restore_adapter = adapter()
        await restore_adapter.initialize()
        try:
            await restore_adapter.observe()
            restore = Action(
                type="set_company_name",
                parameters={"name": original},
                expected_effect="Restore the original company name.",
            )
            assert (await restore_adapter.validate(restore)).valid
            assert (await restore_adapter.execute(restore)).success
            restored = await restore_adapter.observe()
            assert (
                OpenTTDObservationState.model_validate_json(
                    json.dumps(restored.state)
                ).resources.company_name
                == original
            )
        finally:
            await restore_adapter.shutdown()

    asyncio.run(scenario())
