"""Runtime-level verified OpenTTD action scenarios using the deterministic fake client."""

import asyncio
from typing import cast

from sim_pilot.adapters.openttd import OpenTTDAdapter
from sim_pilot.domain import (
    Action,
    AdapterId,
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.messages import CommandCompletedPayload
from sim_pilot.openttd.gamescript.models import BridgeHealth, SynchronizationState
from sim_pilot.runtime import RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.models import RuntimeEventType
from tests.openttd.gamescript.helpers import capabilities, command_fingerprint, snapshot
from tests.openttd.helpers import FakeOpenTTDClient
from tests.runtime.helpers import make_task


class FakeCommandBridge:
    def __init__(self, admin: FakeOpenTTDClient) -> None:
        self.admin = admin
        bridge_capabilities = capabilities()
        self.health = BridgeHealth(
            connected=True,
            authenticated=True,
            openttd_version="15.3",
            bridge_detected=True,
            bridge_protocol_version=1,
            script_version=1,
            script_instance_id="runtime-bridge",
            last_sequence=4,
            synchronization_state=SynchronizationState.SYNCHRONIZED,
            active_company_context=0,
            capability_fingerprint=bridge_capabilities.fingerprint,
            capabilities=bridge_capabilities,
            snapshot=snapshot(snapshot_id="runtime-bridge:snapshot:4"),
        )

    async def synchronize(self) -> BridgeHealth:
        return self.health

    async def refresh_snapshot(self) -> object:
        assert self.health.snapshot is not None
        return self.health.snapshot

    async def execute_set_company_name(
        self, *, name: str, prior_snapshot_id: str
    ) -> tuple[CommandCompletedPayload, object]:
        assert self.health.snapshot is not None
        assert self.health.snapshot.snapshot_id == prior_snapshot_id
        assert self.health.snapshot.company is not None
        before = self.health.snapshot.company.name
        updated_company = self.health.snapshot.company.model_copy(update={"name": name})
        updated_snapshot = self.health.snapshot.model_copy(
            update={
                "snapshot_id": "runtime-bridge:snapshot:6",
                "company": updated_company,
            }
        )
        self.health = self.health.model_copy(
            update={"last_sequence": 6, "snapshot": updated_snapshot}
        )
        self.admin.states = [
            state.model_copy(update={"company": state.company.model_copy(update={"name": name})})
            for state in self.admin.states
        ]
        result = CommandCompletedPayload(
            command_id="runtime-command",
            action_fingerprint=command_fingerprint(name),
            before_name=before,
            after_name=name,
            state_changed=before != name,
            cost=0,
        )
        return result, updated_snapshot

    async def close(self) -> None:
        self.health = self.health.model_copy(
            update={"synchronization_state": SynchronizationState.DISCONNECTED}
        )


def test_server_name_action_completes_through_runtime_and_is_journaled() -> None:
    client = FakeOpenTTDClient()
    adapter = OpenTTDAdapter(client, allow_writes=True)
    task = make_task(
        specification=TaskSpecification(
            objective=Objective(
                type=ObjectiveType.RUN_UNTIL,
                description="Set the server name.",
                parameters={
                    "resource": "server_name",
                    "target": "Sim Pilot Runtime",
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
                reason="Use the advertised server-name action.",
                action=Action(
                    type="set_server_name",
                    parameters={"name": "Sim Pilot Runtime"},
                    expected_effect="Set the observed server name.",
                ),
            )
        ]
    )
    runtime = RuntimeEngine()

    outcome = asyncio.run(runtime.run(task, adapter, provider))
    context = runtime.reconstruct(task.id)

    assert outcome.status is TaskStatus.COMPLETED
    assert client.rcon_commands == ['server_name "Sim Pilot Runtime"']
    event_types = [event.event_type for event in context.events]
    assert RuntimeEventType.ACTION_PREPARED in event_types
    assert RuntimeEventType.ACTION_EXECUTION_CONFIRMED in event_types
    assert RuntimeEventType.ACTION_CHECKPOINT_COMMITTED in event_types
    assert event_types[-1] is RuntimeEventType.TASK_COMPLETED


def test_server_name_action_honours_approval_before_one_execution() -> None:
    client = FakeOpenTTDClient()
    task = make_task(
        specification=TaskSpecification(
            objective=Objective(
                type=ObjectiveType.RUN_UNTIL,
                description="Set the approved server name.",
                parameters={
                    "resource": "server_name",
                    "target": "Approved Name",
                    "direction": "equal",
                },
            ),
            authority=AuthorityPolicy(approval_actions=("set_server_name",)),
        )
    )
    decision = Decision(
        type=DecisionType.EXECUTE,
        reason="Request the supported action.",
        action=Action(
            type="set_server_name",
            parameters={"name": "Approved Name"},
            expected_effect="Set the observed server name.",
        ),
    )
    runtime = RuntimeEngine()

    waiting = asyncio.run(
        runtime.run(
            task,
            OpenTTDAdapter(client, allow_writes=True),
            ScriptedDecisionProvider([decision]),
        )
    )
    assert waiting.status is TaskStatus.WAITING_FOR_APPROVAL
    assert waiting.pending_approval is not None
    runtime.approve(task.id)
    completed = asyncio.run(
        runtime.resume(
            task.id,
            lambda _: OpenTTDAdapter(client, allow_writes=True),
            ScriptedDecisionProvider([]),
        )
    )

    assert completed.status is TaskStatus.COMPLETED
    assert client.rcon_commands == ['server_name "Approved Name"']


def test_company_name_bridge_action_completes_with_durable_checkpoint_metadata() -> None:
    admin = FakeOpenTTDClient()
    bridge = cast("GameScriptBridgeClient", FakeCommandBridge(admin))
    adapter = OpenTTDAdapter(
        admin,
        bridge=bridge,
        allow_gamescript_writes=True,
    )
    task = make_task(
        specification=TaskSpecification(
            adapter_type=AdapterId.OPENTTD,
            objective=Objective(
                type=ObjectiveType.RUN_UNTIL,
                description="Set the company name.",
                parameters={
                    "resource": "company_name",
                    "target": "Runtime Bridge Company",
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
                reason="Use the negotiated company-name action.",
                action=Action(
                    type="set_company_name",
                    parameters={"name": "Runtime Bridge Company"},
                    expected_effect="Set and re-observe the company name.",
                ),
            )
        ]
    )
    runtime = RuntimeEngine()
    outcome = asyncio.run(runtime.run(task, adapter, provider))
    context = runtime.reconstruct(task.id)
    assert outcome.status is TaskStatus.COMPLETED
    assert context.checkpoint is not None
    persisted_bridge = context.checkpoint.state["bridge"]
    assert isinstance(persisted_bridge, dict)
    assert persisted_bridge["script_instance_id"] == "runtime-bridge"
    assert persisted_bridge["last_sequence"] == 6
    event_types = [event.event_type for event in context.events]
    assert RuntimeEventType.ACTION_PREPARED in event_types
    assert RuntimeEventType.ACTION_EXECUTION_CONFIRMED in event_types
    assert RuntimeEventType.ACTION_CHECKPOINT_COMMITTED in event_types
