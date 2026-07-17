"""OpenTTD observational reconciliation classification tests."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.domain import Action
from sim_pilot.runtime import ReconciliationClassification
from sim_pilot.runtime.action_attempts import ActionAttempt, ActionAttemptStatus, action_fingerprint
from sim_pilot.runtime.recovery import reconcile_action
from tests.openttd.helpers import FakeOpenTTDClient


def test_server_name_reconciliation_is_definite_or_ambiguous() -> None:
    async def snapshot(client: FakeOpenTTDClient) -> AdapterSnapshot:
        adapter = OpenTTDAdapter(client, allow_writes=True)
        await adapter.initialize()
        observation = await adapter.observe()
        await adapter.shutdown()
        return AdapterSnapshot(
            adapter_type="sim_pilot.adapters.openttd.adapter.OpenTTDAdapter",
            simulation_schema_version=1,
            observation_sequence=observation.sequence,
            seed="0",
            state=observation.state,  # type: ignore[arg-type]
        )

    async def scenario() -> None:
        client = FakeOpenTTDClient()
        prior = await snapshot(client)
        action = Action(
            type="set_server_name",
            parameters={"name": "Recovered Name"},
            expected_effect="Set server name.",
        )
        now = datetime.now(UTC)
        attempt = ActionAttempt(
            task_id=UUID(int=1),
            runtime_sequence=1,
            action_id=UUID(int=2),
            action_fingerprint=action_fingerprint(action),
            action=action,
            prior_checkpoint_id=UUID(int=3),
            prior_observation_fingerprint="prior",
            expected_effect=action.expected_effect,
            estimated_cost=0,
            status=ActionAttemptStatus.EXECUTION_STARTED,
            prepared_at=now,
            updated_at=now,
        )
        not_executed = await reconcile_action(attempt, prior, await snapshot(client))
        await client.execute_rcon('server_name "Recovered Name"')
        executed = await reconcile_action(attempt, prior, await snapshot(client))
        await client.execute_rcon('server_name "Third Party Name"')
        ambiguous = await reconcile_action(attempt, prior, await snapshot(client))

        assert not_executed.classification is ReconciliationClassification.DEFINITELY_NOT_EXECUTED
        assert executed.classification is ReconciliationClassification.DEFINITELY_EXECUTED
        assert ambiguous.classification is ReconciliationClassification.AMBIGUOUS

    asyncio.run(scenario())
