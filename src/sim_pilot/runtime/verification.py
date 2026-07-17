"""Pure deterministic verification of reference adapter effects."""

from typing import cast

from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.runtime.models import VerificationResult


def changed(before: Observation, after: Observation, key: str) -> bool:
    return before.state.get(key) != after.state.get(key)


class ActionVerifier:
    """Compare reported execution with observed state effects."""

    def verify(
        self,
        before: Observation,
        action: Action,
        result: ExecutionResult,
        after: Observation,
        expected_cost: float,
    ) -> VerificationResult:
        reasons: list[str] = []
        state_changed = before.state != after.state or before.tick != after.tick
        if result.state_changed != state_changed:
            reasons.append("reported state_changed does not match observations")
        if abs(result.cost - expected_cost) > 1e-6:
            reasons.append("execution cost does not match validated cost")
        if not result.success:
            if state_changed:
                reasons.append("failed execution unexpectedly mutated state")
            return VerificationResult(verified=not reasons, reasons=tuple(reasons))
        if not state_changed:
            reasons.append("successful execution did not change state")

        effect = False
        if action.type == "advance_time":
            effect = after.tick > before.tick
        elif action.type in {"build_housing", "build_power"}:
            before_projects = before.state.get("active_projects")
            after_projects = after.state.get("active_projects")
            if isinstance(before_projects, list) and isinstance(after_projects, list):
                before_items = cast("list[object]", before_projects)
                after_items = cast("list[object]", after_projects)
                effect = len(after_items) == len(before_items) + 1
        elif action.type == "repair":
            effect = self._numeric_increased(before, after, "infrastructure")
        elif action.type == "set_maintenance":
            effect = changed(before, after, "maintenance_level")
        elif action.type == "take_loan":
            effect = self._numeric_increased(before, after, "debt")
        elif action.type == "repay_loan":
            effect = self._numeric_decreased(before, after, "debt")
        elif action.type == "pause":
            effect = after.state.get("paused") is True
        elif action.type == "resume":
            effect = before.state.get("paused") is True and after.state.get("paused") is False
        elif action.type == "set_server_name":
            requested = action.parameters.get("name")
            effect = (
                isinstance(requested, str)
                and self._resource(before, "server_name") != requested
                and self._resource(after, "server_name") == requested
            )
        if not effect:
            reasons.append(f"expected effect was not observed for action: {action.type}")
        return VerificationResult(verified=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _resource(observation: Observation, name: str) -> object:
        resources = observation.state.get("resources")
        if isinstance(resources, dict):
            return cast("dict[object, object]", resources).get(name)
        return observation.state.get(name)

    def _numeric_increased(self, before: Observation, after: Observation, key: str) -> bool:
        left, right = before.state.get(key), after.state.get(key)
        return isinstance(left, (int, float)) and isinstance(right, (int, float)) and right > left

    def _numeric_decreased(self, before: Observation, after: Observation, key: str) -> bool:
        left, right = before.state.get(key), after.state.get(key)
        return isinstance(left, (int, float)) and isinstance(right, (int, float)) and right < left
