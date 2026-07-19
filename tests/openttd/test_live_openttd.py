"""Explicitly enabled OpenTTD integration acceptance tests."""

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.adapters.openttd import OpenTTDAdapter, OpenTTDReadOnlyAdapter
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
from sim_pilot.persistence.sqlite import SQLiteUnitOfWork, create_sqlite_engine, upgrade_database
from sim_pilot.reconciliation import default_reconciliation_dispatcher
from sim_pilot.runtime import ReconciliationClassification, RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.errors import SimulatedCrash
from sim_pilot.runtime.recovery import CrashPoint
from tests.runtime.helpers import make_task


@pytest.mark.live
def test_live_openttd_two_observations_and_read_only_rejection() -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD=1 with local OpenTTD 15.3 to run")

    async def scenario() -> None:
        adapter = OpenTTDReadOnlyAdapter(OpenTTDAdminClient(openttd_configuration()))
        await adapter.initialize()
        try:
            first = await adapter.observe()
            await asyncio.sleep(openttd_configuration().polling_interval_seconds)
            second = await adapter.observe()
            assert second.sequence == first.sequence + 1
            assert second.tick >= first.tick
            assert not (await adapter.validate(Action(type="pause", expected_effect="pause"))).valid
        finally:
            await adapter.shutdown()

    asyncio.run(scenario())


@pytest.mark.live
def test_live_openttd_crash_after_action_reconciles_without_retry(tmp_path: Path) -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD=1 with a disposable OpenTTD 15.3 server")
    if os.getenv("SIM_PILOT_OPENTTD_ALLOW_WRITES") != "1":
        pytest.skip("set SIM_PILOT_OPENTTD_ALLOW_WRITES=1 for the disposable test server")

    def crasher(point: CrashPoint) -> None:
        if point is CrashPoint.AFTER_EXECUTION:
            raise SimulatedCrash(point.value)

    def durable_runtime(
        hook: Callable[[CrashPoint], None] | None = None,
    ) -> tuple[Engine, RuntimeEngine]:
        url = f"sqlite:///{tmp_path / 'live-crash.db'}"
        upgrade_database(url)
        engine = create_sqlite_engine(url)
        return engine, RuntimeEngine(
            unit_of_work_factory=lambda: SQLiteUnitOfWork(engine),
            crash_hook=hook,
            reconciliation_dispatcher=default_reconciliation_dispatcher(),
        )

    async def scenario() -> None:
        configuration = openttd_configuration()
        probe = OpenTTDAdapter(OpenTTDAdminClient(configuration), allow_writes=True)
        await probe.initialize()
        current = await probe.observe()
        await probe.shutdown()
        resources = current.state["resources"]
        assert isinstance(resources, dict)
        target = (
            "Sim Pilot Crash 6C A"
            if resources["server_name"] != "Sim Pilot Crash 6C A"
            else "Sim Pilot Crash 6C B"
        )
        task = make_task(
            specification=TaskSpecification(
                objective=Objective(
                    type=ObjectiveType.RUN_UNTIL,
                    description="Set the crash-test server name.",
                    parameters={
                        "resource": "server_name",
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
                type="set_server_name",
                parameters={"name": target},
                expected_effect="Set and re-observe the server name.",
            ),
        )
        engine, runtime = durable_runtime(crasher)
        with pytest.raises(SimulatedCrash):
            await runtime.run(
                task,
                OpenTTDAdapter(OpenTTDAdminClient(configuration), allow_writes=True),
                ScriptedDecisionProvider([decision]),
            )
        engine.dispose()

        fresh_adapter = OpenTTDAdapter(OpenTTDAdminClient(configuration), allow_writes=True)
        await fresh_adapter.initialize()
        fresh_observation = await fresh_adapter.observe()
        current_snapshot = AdapterSnapshot(
            adapter_type="sim_pilot.adapters.openttd.adapter.OpenTTDAdapter",
            simulation_schema_version=1,
            observation_sequence=fresh_observation.sequence,
            seed="0",
            state=cast("dict[str, JsonValue]", fresh_observation.state),
        )
        await fresh_adapter.shutdown()
        engine2, runtime2 = durable_runtime()
        report = await runtime2.inspect_recovery(task.id, current_snapshot)
        assert report is not None
        assert report.classification is ReconciliationClassification.DEFINITELY_EXECUTED
        engine2.dispose()

    asyncio.run(scenario())


@pytest.mark.live
def test_live_openttd_server_name_action_through_runtime() -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD=1 with a disposable OpenTTD 15.3 server")
    if os.getenv("SIM_PILOT_OPENTTD_ALLOW_WRITES") != "1":
        pytest.skip("set SIM_PILOT_OPENTTD_ALLOW_WRITES=1 for the disposable test server")

    async def scenario() -> None:
        configuration = openttd_configuration()
        adapter = OpenTTDAdapter(
            OpenTTDAdminClient(configuration),
            allow_writes=configuration.allow_writes,
            stale_days=configuration.stale_observation_threshold_days,
        )
        target = "Sim Pilot Task 6C Live"
        task = make_task(
            specification=TaskSpecification(
                objective=Objective(
                    type=ObjectiveType.RUN_UNTIL,
                    description="Set the disposable server name.",
                    parameters={
                        "resource": "server_name",
                        "target": target,
                        "direction": "equal",
                    },
                ),
                authority=AuthorityPolicy(),
            )
        )
        provider = ScriptedDecisionProvider(
            [
                Decision(
                    type=DecisionType.EXECUTE,
                    reason="Execute the supported live action.",
                    action=Action(
                        type="set_server_name",
                        parameters={"name": target},
                        expected_effect="Set and re-observe the server name.",
                    ),
                )
            ]
        )
        runtime = RuntimeEngine()
        outcome = await runtime.run(task, adapter, provider)
        context = runtime.reconstruct(task.id)
        assert outcome.status is TaskStatus.COMPLETED
        assert context.observation is not None
        resources = context.observation.state["resources"]
        assert isinstance(resources, dict)
        assert resources["server_name"] == target
        assert context.unresolved_attempt is None

    asyncio.run(scenario())
