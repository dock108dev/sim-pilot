"""Pure task-policy evaluation for proposed actions."""

from decimal import Decimal

from sim_pilot.adapters.base import AdapterValidation
from sim_pilot.domain import Action, ConstraintType, Observation, TaskSpecification
from sim_pilot.runtime.models import PolicyDecision


class PolicyEngine:
    """Evaluate task constraints and authority without mutating dependencies."""

    def evaluate(
        self,
        specification: TaskSpecification,
        action: Action,
        observation: Observation,
        total_spend: Decimal,
        adapter_validation: AdapterValidation,
    ) -> PolicyDecision:
        reasons: list[str] = []
        if not adapter_validation.valid:
            reasons.append(f"adapter validation failed: {adapter_validation.message}")

        authority = specification.authority
        forbidden = set(authority.forbidden_actions)
        allowed_sets: list[set[str]] = []
        minimum_reserves: list[Decimal] = []
        resource_floors: list[tuple[str, float]] = []
        hard_maximums: list[Decimal] = []

        for constraint in specification.constraints:
            if constraint.type is ConstraintType.FORBIDDEN_ACTION:
                value = constraint.parameters.get("action")
                if isinstance(value, str):
                    forbidden.add(value)
            elif constraint.type is ConstraintType.ALLOWED_ACTION:
                values = constraint.parameters.get("actions")
                if isinstance(values, list) and all(isinstance(item, str) for item in values):
                    allowed_sets.append({item for item in values if isinstance(item, str)})
                else:
                    value = constraint.parameters.get("action")
                    if isinstance(value, str):
                        allowed_sets.append({value})
            elif constraint.type is ConstraintType.MINIMUM_RESERVE:
                amount = constraint.parameters.get("amount")
                if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                    minimum_reserves.append(Decimal(str(amount)))
            elif constraint.type is ConstraintType.RESOURCE_FLOOR:
                resource = constraint.parameters.get("resource")
                floor = constraint.parameters.get("floor")
                if (
                    isinstance(resource, str)
                    and isinstance(floor, (int, float))
                    and not isinstance(floor, bool)
                ):
                    resource_floors.append((resource, float(floor)))
            elif constraint.type is ConstraintType.MAXIMUM_SPEND:
                amount = constraint.parameters.get("amount")
                if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                    hard_maximums.append(Decimal(str(amount)))

        if action.type in forbidden:
            reasons.append(f"action is forbidden: {action.type}")
        if allowed_sets and any(action.type not in allowed for allowed in allowed_sets):
            reasons.append(f"action is not in the allowed set: {action.type}")

        cost = Decimal(str(adapter_validation.estimated_cost))
        if (
            authority.maximum_total_spend is not None
            and total_spend + cost > authority.maximum_total_spend
        ):
            reasons.append("action would exceed maximum total spend")
        if any(total_spend + cost > maximum for maximum in hard_maximums):
            reasons.append("action would exceed maximum spend constraint")

        cash = observation.state.get("cash")
        if minimum_reserves:
            if isinstance(cash, bool) or not isinstance(cash, (int, float)):
                reasons.append("cash is unavailable for reserve enforcement")
            elif any(Decimal(str(cash)) - cost < reserve for reserve in minimum_reserves):
                reasons.append("action would violate minimum reserve")
        for resource, floor in resource_floors:
            value = observation.state.get(resource)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                reasons.append(f"resource floor cannot be evaluated: {resource}")
            elif float(value) < floor:
                reasons.append(f"resource is below required floor: {resource}")

        approval_required = action.type in authority.approval_actions
        if authority.maximum_single_spend is not None and cost > authority.maximum_single_spend:
            approval_required = True

        return PolicyDecision(
            allowed=not reasons,
            approval_required=approval_required and not reasons,
            reasons=tuple(reasons),
        )
