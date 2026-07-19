"""Task 3 deterministic runtime integration scenarios."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sim_pilot.adapters.base import ActionDefinition
from sim_pilot.adapters.reference import ReferenceSimulationAdapter
from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Constraint,
    ConstraintType,
    Decision,
    DecisionType,
    ExecutionResult,
    Objective,
    ObjectiveType,
    Observation,
    TaskSpecification,
    TaskStatus,
)
from sim_pilot.reference_simulation import ReferenceSimulation, SimulationState
from sim_pilot.reference_simulation.validation import ValidationResult
from sim_pilot.runtime import RuntimeConfiguration, RuntimeEngine, ScriptedDecisionProvider
from sim_pilot.runtime.models import RuntimeEventType
from tests.runtime.helpers import make_action, make_task


class TrackingAdapter(ReferenceSimulationAdapter):
    def __init__(self, simulation: ReferenceSimulation | None = None) -> None:
        super().__init__(simulation)
        self.shutdown_count = 0
        self.execution_count = 0

    async def execute(self, action: Action) -> ExecutionResult:
        self.execution_count += 1
        return await super().execute(action)

    async def shutdown(self) -> None:
        self.shutdown_count += 1
        await super().shutdown()


class InitializationFailureAdapter(TrackingAdapter):
    async def initialize(self) -> None:
        msg = "initialization failed"
        raise RuntimeError(msg)


class ExecutionFailureAdapter(TrackingAdapter):
    async def execute(self, action: Action) -> ExecutionResult:
        del action
        msg = "execution failed"
        raise RuntimeError(msg)


class FalseSuccessAdapter:
    def __init__(self) -> None:
        self.shutdown_count = 0
        self.observation_count = 0

    async def initialize(self) -> None:
        return None

    async def observe(self) -> Observation:
        self.observation_count += 1
        return Observation(
            sequence=self.observation_count,
            timestamp=datetime.now(UTC),
            tick=0,
            summary="Unchanged state.",
            state={"cash": 500_000, "failed": False},
        )

    async def available_actions(self) -> list[ActionDefinition]:
        return []

    async def validate(self, action: Action) -> ValidationResult:
        del action
        return ValidationResult(valid=True, message="Valid.", estimated_cost=0)

    async def execute(self, action: Action) -> ExecutionResult:
        del action
        return ExecutionResult(
            success=True,
            state_changed=True,
            cost=0,
            message="Falsely reported success.",
        )

    async def shutdown(self) -> None:
        self.shutdown_count += 1


def execute_decision(type_: str, **parameters: int | float) -> Decision:
    return Decision(
        type=DecisionType.EXECUTE,
        reason=f"Execute {type_}.",
        action=make_action(type_, **parameters),
    )


def test_scenario_a_completes_cash_objective_with_ordered_events() -> None:
    async def scenario() -> None:
        task = make_task(target=520_000)
        provider = ScriptedDecisionProvider(
            [execute_decision("advance_time", ticks=1) for _ in range(10)]
        )
        adapter = TrackingAdapter()
        engine = RuntimeEngine()

        outcome = await engine.run(task, adapter, provider)
        events = engine.event_store.list_events(task.id)

        assert outcome.status is TaskStatus.COMPLETED
        assert adapter.execution_count > 0
        assert adapter.shutdown_count == 1
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        assert events[0].event_type is RuntimeEventType.TASK_CREATED
        assert events[-1].event_type is RuntimeEventType.TASK_COMPLETED

    asyncio.run(scenario())


def test_complete_project_requires_start_and_completion_during_task() -> None:
    async def scenario() -> None:
        specification = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.COMPLETE_PROJECT,
                description="Complete a housing project.",
                parameters={"project_type": "housing"},
            ),
            authority=AuthorityPolicy(),
        )
        provider = ScriptedDecisionProvider(
            [
                execute_decision("build_housing", units=1),
                execute_decision("advance_time", ticks=5),
            ]
        )
        adapter = TrackingAdapter()

        outcome = await RuntimeEngine().run(
            make_task(specification=specification),
            adapter,
            provider,
        )

        assert outcome.status is TaskStatus.COMPLETED
        assert provider.request_count == 2
        assert adapter.execution_count == 2
        assert adapter.simulation.state.housing == 601

    asyncio.run(scenario())


def test_already_satisfied_run_until_completes_without_a_decision() -> None:
    async def scenario() -> None:
        specification = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.RUN_UNTIL,
                description="Run until debt is at or below 25,000.",
                parameters={"resource": "debt", "target": 25_000, "direction": "below"},
            ),
            authority=AuthorityPolicy(forbidden_actions=("take_loan",)),
            stop_conditions=("debt <= 25000",),
        )
        provider = ScriptedDecisionProvider([])

        outcome = await RuntimeEngine().run(
            make_task(specification=specification),
            TrackingAdapter(),
            provider,
        )

        assert outcome.status is TaskStatus.COMPLETED
        assert provider.request_count == 0
        assert outcome.reason == "debt=0; target=25000."

    asyncio.run(scenario())


def test_scenario_b_forbidden_loan_is_never_executed() -> None:
    async def scenario() -> None:
        constraint = Constraint(
            type=ConstraintType.FORBIDDEN_ACTION,
            description="Loans are forbidden.",
            parameters={"action": "take_loan"},
        )
        spec = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.REACH_RESOURCE,
                description="Reach cash.",
                parameters={"resource": "cash", "target": 1_000_000},
            ),
            constraints=(constraint,),
            authority=AuthorityPolicy(),
        )
        task = make_task(specification=spec)
        adapter = TrackingAdapter()
        engine = RuntimeEngine(configuration=RuntimeConfiguration(max_consecutive_failures=1))

        outcome = await engine.run(
            task,
            adapter,
            ScriptedDecisionProvider([execute_decision("take_loan", amount=100_000)]),
        )

        assert outcome.status is TaskStatus.BLOCKED
        assert adapter.execution_count == 0
        assert adapter.simulation.state.debt == 0
        assert any(
            event.event_type is RuntimeEventType.ACTION_REJECTED
            for event in engine.event_store.list_events(task.id)
        )

    asyncio.run(scenario())


def test_scenario_c_minimum_reserve_rejects_project() -> None:
    async def scenario() -> None:
        reserve = Constraint(
            type=ConstraintType.MINIMUM_RESERVE,
            description="Keep 450000 cash.",
            parameters={"amount": 450_000},
        )
        spec = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.REACH_RESOURCE,
                description="Reach cash.",
                parameters={"resource": "cash", "target": 1_000_000},
            ),
            constraints=(reserve,),
            authority=AuthorityPolicy(),
        )
        task = make_task(specification=spec)
        adapter = TrackingAdapter()

        outcome = await RuntimeEngine().run(
            task,
            adapter,
            ScriptedDecisionProvider([execute_decision("build_housing", units=100)]),
        )

        assert outcome.status is TaskStatus.BLOCKED
        assert adapter.execution_count == 0
        assert adapter.simulation.state.cash == 500_000

    asyncio.run(scenario())


def test_scenario_d_approval_executes_action_once_after_resume() -> None:
    async def scenario() -> None:
        spec = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.REACH_RESOURCE,
                description="Reach cash.",
                parameters={"resource": "cash", "target": 1_000_000},
            ),
            authority=AuthorityPolicy(maximum_single_spend=Decimal(50_000)),
        )
        task = make_task(specification=spec)
        adapter = TrackingAdapter()
        engine = RuntimeEngine()
        first = await engine.run(
            task,
            adapter,
            ScriptedDecisionProvider([execute_decision("build_housing", units=100)]),
        )

        assert first.status is TaskStatus.WAITING_FOR_APPROVAL
        assert adapter.execution_count == 0
        assert adapter.shutdown_count == 1
        engine.approve(task.id)
        resumed_task = task.model_copy(update={"status": TaskStatus.WAITING_FOR_APPROVAL})
        second = await engine.run(
            resumed_task,
            adapter,
            ScriptedDecisionProvider(
                [Decision(type=DecisionType.BLOCKED, reason="End deterministic test.")]
            ),
        )

        assert second.status is TaskStatus.BLOCKED
        assert adapter.execution_count == 1
        assert adapter.shutdown_count == 2
        assert len(adapter.simulation.state.active_projects) == 1
        event_types = [event.event_type for event in engine.event_store.list_events(task.id)]
        assert event_types.count(RuntimeEventType.APPROVAL_GRANTED) == 1
        assert event_types.count(RuntimeEventType.ACTION_EXECUTED) == 1

    asyncio.run(scenario())


def test_scenario_e_denial_blocks_task() -> None:
    async def scenario() -> None:
        spec = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.REACH_RESOURCE,
                description="Reach cash.",
                parameters={"resource": "cash", "target": 1_000_000},
            ),
            authority=AuthorityPolicy(approval_actions=("build_housing",)),
        )
        task = make_task(specification=spec)
        engine = RuntimeEngine()
        outcome = await engine.run(
            task,
            TrackingAdapter(),
            ScriptedDecisionProvider([execute_decision("build_housing", units=1)]),
        )
        assert outcome.status is TaskStatus.WAITING_FOR_APPROVAL

        request = engine.deny(task.id)
        events = engine.event_store.list_events(task.id)
        assert request.status.value == "denied"
        assert events[-2].event_type is RuntimeEventType.APPROVAL_DENIED
        assert events[-1].event_type is RuntimeEventType.TASK_BLOCKED

    asyncio.run(scenario())


def test_scenario_f_false_completion_is_rejected() -> None:
    async def scenario() -> None:
        task = make_task(target=1_000_000)
        provider = ScriptedDecisionProvider(
            [
                Decision(type=DecisionType.COMPLETE, reason="Claim complete."),
                Decision(type=DecisionType.BLOCKED, reason="No valid plan."),
            ]
        )
        engine = RuntimeEngine()

        outcome = await engine.run(task, TrackingAdapter(), provider)

        assert outcome.status is TaskStatus.BLOCKED
        assert provider.request_count == 2
        assert any(
            event.event_type is RuntimeEventType.ACTION_REJECTED
            for event in engine.event_store.list_events(task.id)
        )

    asyncio.run(scenario())


def test_scenario_g_false_success_causes_verification_failure() -> None:
    async def scenario() -> None:
        task = make_task(target=1_000_000)
        adapter = FalseSuccessAdapter()
        outcome = await RuntimeEngine().run(
            task,
            adapter,
            ScriptedDecisionProvider([execute_decision("advance_time", ticks=1)]),
        )

        assert outcome.status is TaskStatus.FAILED
        assert "did not change state" in cast("str", outcome.reason)
        assert adapter.shutdown_count == 1

    asyncio.run(scenario())


def test_scenario_h_wait_loop_is_detected() -> None:
    async def scenario() -> None:
        task = make_task(target=1_000_000)
        waits = [Decision(type=DecisionType.WAIT, reason="Wait.") for _ in range(4)]
        outcome = await RuntimeEngine().run(
            task,
            TrackingAdapter(),
            ScriptedDecisionProvider(waits),
        )
        assert outcome.status is TaskStatus.BLOCKED
        assert outcome.reason == "repeated state detected"

    asyncio.run(scenario())


def test_repeated_ineffective_action_is_detected() -> None:
    async def scenario() -> None:
        constraint = Constraint(
            type=ConstraintType.FORBIDDEN_ACTION,
            description="Loans are forbidden.",
            parameters={"action": "take_loan"},
        )
        spec = TaskSpecification(
            objective=Objective(
                type=ObjectiveType.REACH_RESOURCE,
                description="Reach cash.",
                parameters={"resource": "cash", "target": 1_000_000},
            ),
            constraints=(constraint,),
            authority=AuthorityPolicy(),
        )
        task = make_task(specification=spec)
        decisions = [execute_decision("take_loan", amount=10_000) for _ in range(3)]
        engine = RuntimeEngine(
            configuration=RuntimeConfiguration(
                max_consecutive_failures=4,
                repeated_action_limit=3,
            )
        )

        outcome = await engine.run(task, TrackingAdapter(), ScriptedDecisionProvider(decisions))

        assert outcome.status is TaskStatus.BLOCKED
        assert outcome.reason == "repeated action detected"

    asyncio.run(scenario())


def test_scenario_i_terminal_simulation_failure_fails_task() -> None:
    async def scenario() -> None:
        state = SimulationState(
            cash=1,
            population=0,
            housing=0,
            power_capacity=0,
            power_usage=0,
        )
        task = make_task(target=1_000_000)
        outcome = await RuntimeEngine().run(
            task,
            TrackingAdapter(ReferenceSimulation(state)),
            ScriptedDecisionProvider([execute_decision("advance_time", ticks=1)]),
        )
        assert outcome.status is TaskStatus.FAILED
        assert outcome.reason == "simulation entered terminal failure"

    asyncio.run(scenario())


def test_scenario_j_cancels_between_iterations() -> None:
    async def scenario() -> None:
        checks = 0

        def cancellation_check(task_id: UUID) -> bool:
            nonlocal checks
            del task_id
            checks += 1
            return checks > 1

        task = make_task(target=1_000_000)
        adapter = TrackingAdapter()
        engine = RuntimeEngine(cancellation_check=cancellation_check)
        decisions = [execute_decision("advance_time", ticks=1) for _ in range(3)]

        outcome = await engine.run(task, adapter, ScriptedDecisionProvider(decisions))

        assert outcome.status is TaskStatus.CANCELLED
        assert adapter.execution_count == 1
        assert adapter.shutdown_count == 1
        assert (
            engine.event_store.list_events(task.id)[-1].event_type
            is RuntimeEventType.TASK_CANCELLED
        )

    asyncio.run(scenario())


def test_maximum_iterations_and_initialization_failure_shutdown() -> None:
    async def scenario() -> None:
        task = make_task(target=1_000_000)
        engine = RuntimeEngine(
            configuration=RuntimeConfiguration(max_iterations=1, repeated_state_limit=3)
        )
        limited = TrackingAdapter()
        outcome = await engine.run(
            task,
            limited,
            ScriptedDecisionProvider([execute_decision("advance_time", ticks=1)]),
        )
        assert outcome.status is TaskStatus.BLOCKED
        assert outcome.reason == "maximum iterations reached"
        assert limited.shutdown_count == 1

        failed_task = make_task()
        failed_task = failed_task.model_copy(update={"id": UUID(int=257)})
        failing = InitializationFailureAdapter()
        failed = await RuntimeEngine().run(
            failed_task,
            failing,
            ScriptedDecisionProvider([]),
        )
        assert failed.status is TaskStatus.FAILED
        assert failing.shutdown_count == 1

        execution_task = make_task().model_copy(update={"id": UUID(int=258)})
        execution_failure = ExecutionFailureAdapter()
        execution_outcome = await RuntimeEngine().run(
            execution_task,
            execution_failure,
            ScriptedDecisionProvider([execute_decision("advance_time", ticks=1)]),
        )
        assert execution_outcome.status is TaskStatus.FAILED
        assert "execution failed" in cast("str", execution_outcome.reason)
        assert execution_failure.shutdown_count == 1

    asyncio.run(scenario())
