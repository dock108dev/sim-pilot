"""Model-backed decision results flowing through existing runtime controls."""

import asyncio
from decimal import Decimal

import pytest

from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Decision,
    DecisionType,
    ExecutionResult,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.persistence import in_memory_unit_of_work_factory
from sim_pilot.provider_metadata import ProviderMetadata
from sim_pilot.runtime import RuntimeConfiguration, RuntimeEngine
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult
from sim_pilot.runtime.decision_errors import DecisionProviderUnavailableError
from sim_pilot.runtime.decision_validation import validate_provider_decision
from sim_pilot.runtime.errors import SimulatedCrash
from sim_pilot.runtime.models import RuntimeEventType
from sim_pilot.runtime.recovery import CrashPoint
from tests.runtime.helpers import make_action, make_task


class FakeModelProvider:
    def __init__(self, decisions: list[Decision], *, validate: bool = True) -> None:
        self.decisions = decisions
        self.validate = validate
        self.calls = 0

    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        decision = self.decisions[min(self.calls, len(self.decisions) - 1)]
        self.calls += 1
        if self.validate:
            validate_provider_decision(decision, context)
        return DecisionProviderResult(
            decision=decision,
            metadata=ProviderMetadata(
                provider="fake-openai",
                model="test-model",
                request_id=f"req_{self.calls}",
                latency_ms=1.5,
                prompt_version="decision-provider-v1",
                validation_result="valid",
            ),
        )


class FailingModelProvider:
    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        del context
        raise DecisionProviderUnavailableError("provider remained unavailable")


class TrackingAdapter(ReferenceSimulationAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.execution_count = 0

    async def execute(self, action: Action) -> ExecutionResult:
        self.execution_count += 1
        return await super().execute(action)


def _execute(action: Action) -> Decision:
    return Decision(type=DecisionType.EXECUTE, reason="Execute one action.", action=action)


def test_model_backed_provider_completes_and_persists_metadata() -> None:
    async def scenario() -> None:
        runtime = RuntimeEngine()
        task = make_task(target=506_000)
        provider = FakeModelProvider([_execute(make_action("advance_time", ticks=1))])
        outcome = await runtime.run(task, ReferenceSimulationAdapter(), provider)
        assert outcome.status is TaskStatus.COMPLETED
        decision_event = next(
            event
            for event in runtime.event_store.list_events(task.id)
            if event.event_type is RuntimeEventType.DECISION_GENERATED
        )
        metadata = decision_event.payload["provider_metadata"]
        assert isinstance(metadata, dict)
        assert metadata["provider"] == "fake-openai"
        assert metadata["model"] == "test-model"
        assert metadata["prompt_version"] == "decision-provider-v1"

    asyncio.run(scenario())


def test_model_provider_restart_and_recovery_boundaries_remain_intact() -> None:
    async def scenario() -> None:
        factory = in_memory_unit_of_work_factory()
        task = make_task(target=510_000)
        first_runtime = RuntimeEngine(unit_of_work_factory=factory)
        first = await first_runtime.run(
            task,
            ReferenceSimulationAdapter(),
            FakeModelProvider([_execute(make_action("advance_time", ticks=1))]),
            iteration_budget=1,
        )
        assert first.status is TaskStatus.RUNNING

        second_runtime = RuntimeEngine(unit_of_work_factory=factory)
        resumed = await second_runtime.resume(
            task.id,
            lambda context: ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot()),
            FakeModelProvider([_execute(make_action("advance_time", ticks=1))]),
        )
        assert resumed.status is TaskStatus.COMPLETED

        crash_factory = in_memory_unit_of_work_factory()

        def crash(point: CrashPoint) -> None:
            if point is CrashPoint.AFTER_EXECUTION:
                raise SimulatedCrash(point.value)

        crashed_task = make_task(target=1_000_000)
        crashing_runtime = RuntimeEngine(
            unit_of_work_factory=crash_factory,
            crash_hook=crash,
        )
        with pytest.raises(SimulatedCrash):
            await crashing_runtime.run(
                crashed_task,
                ReferenceSimulationAdapter(),
                FakeModelProvider([_execute(make_action("advance_time", ticks=1))]),
            )
        recovery_runtime = RuntimeEngine(unit_of_work_factory=crash_factory)
        recovery = await recovery_runtime.resume(
            crashed_task.id,
            lambda context: ReferenceSimulationAdapter.from_snapshot(context.adapter_snapshot()),
            FailingModelProvider(),
        )
        assert recovery.status is TaskStatus.RUNNING
        assert recovery.reason == "recovery intervention required"

    asyncio.run(scenario())


def test_invented_action_is_rejected_before_adapter_execution() -> None:
    async def scenario() -> None:
        runtime = RuntimeEngine()
        adapter = TrackingAdapter()
        provider = FakeModelProvider([_execute(make_action("invent_train", count=1))])
        outcome = await runtime.run(make_task(), adapter, provider)
        assert outcome.status is TaskStatus.FAILED
        assert adapter.execution_count == 0
        assert any(
            event.event_type is RuntimeEventType.DECISION_PROVIDER_FAILED
            for event in runtime.event_store.list_events(outcome.task_id)
        )

    asyncio.run(scenario())


def test_policy_and_approval_authority_remain_in_runtime() -> None:
    async def scenario() -> None:
        forbidden_spec = make_task().specification.model_copy(
            update={
                "authority": AuthorityPolicy(forbidden_actions=("take_loan",)),
            }
        )
        runtime = RuntimeEngine(configuration=RuntimeConfiguration(max_consecutive_failures=1))
        adapter = TrackingAdapter()
        forbidden = FakeModelProvider([_execute(make_action("take_loan", amount=100_000))])
        rejected = await runtime.run(make_task(specification=forbidden_spec), adapter, forbidden)
        assert rejected.status is TaskStatus.BLOCKED
        assert adapter.execution_count == 0

        approval_runtime = RuntimeEngine()
        approval_spec = TaskSpecification(
            objective=make_task().specification.objective,
            authority=AuthorityPolicy(maximum_single_spend=Decimal("50000")),
        )
        approval = FakeModelProvider([_execute(make_action("build_housing", units=100))])
        waiting = await approval_runtime.run(
            make_task(specification=approval_spec), ReferenceSimulationAdapter(), approval
        )
        assert waiting.status is TaskStatus.WAITING_FOR_APPROVAL
        assert waiting.pending_approval is not None

    asyncio.run(scenario())


def test_false_completion_and_persistent_failure_are_durable_failures() -> None:
    async def scenario() -> None:
        false_runtime = RuntimeEngine()
        false_complete = FakeModelProvider(
            [Decision(type=DecisionType.COMPLETE, reason="Premature completion.")]
        )
        false_outcome = await false_runtime.run(
            make_task(), ReferenceSimulationAdapter(), false_complete
        )
        assert false_outcome.status is TaskStatus.FAILED

        failed_runtime = RuntimeEngine()
        failed = await failed_runtime.run(
            make_task(), ReferenceSimulationAdapter(), FailingModelProvider()
        )
        assert failed.status is TaskStatus.FAILED
        events = failed_runtime.event_store.list_events(failed.task_id)
        assert events[-2].event_type is RuntimeEventType.DECISION_PROVIDER_FAILED
        assert events[-1].event_type is RuntimeEventType.TASK_FAILED

    asyncio.run(scenario())
