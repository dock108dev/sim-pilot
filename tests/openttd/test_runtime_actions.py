"""Runtime-level verified OpenTTD action scenarios using the deterministic fake client."""

import asyncio

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
from sim_pilot.runtime import RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.models import RuntimeEventType
from tests.openttd.helpers import FakeOpenTTDClient
from tests.runtime.helpers import make_task


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
