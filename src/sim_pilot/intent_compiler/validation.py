"""Deterministic semantic validation for untrusted compiler output."""

import re
from collections.abc import Iterable
from typing import cast

from sim_pilot.domain import ConstraintType, ObjectiveType, TaskSpecification
from sim_pilot.domain.models import JsonValue
from sim_pilot.intent_compiler.models import CompilerCapabilityCatalog, CompilerValidationError
from sim_pilot.intent_compiler.prompt import REFERENCE_CAPABILITIES

STOP_CONDITION = re.compile(
    r"^\s*(?P<resource>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<operator>>=|<=|==|>|<)\s*"
    r"(?P<target>-?\d+(?:\.\d+)?)\s*$"
)
PERCENT_RESOURCES = frozenset({"infrastructure"})
UNIT_INTERVAL_RESOURCES = frozenset({"maintenance_level"})


def _error(code: str, message: str, path: str | None = None) -> CompilerValidationError:
    return CompilerValidationError(code=code, message=message, path=path)


def missing_specification_error() -> CompilerValidationError:
    return _error(
        "missing_specification",
        "provider returned neither a specification nor a clarification or unsupported request",
        "specification",
    )


def _numeric(value: JsonValue | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _validate_resource_threshold(
    resource: object,
    value: JsonValue | None,
    *,
    path: str,
    catalog: CompilerCapabilityCatalog,
) -> list[CompilerValidationError]:
    errors: list[CompilerValidationError] = []
    if not isinstance(resource, str) or resource not in catalog.resources:
        errors.append(
            _error("invalid_resource", f"unsupported resource: {resource!r}", f"{path}.resource")
        )
        return errors
    threshold = _numeric(value)
    if threshold is None:
        errors.append(_error("invalid_threshold", "threshold must be numeric", f"{path}.threshold"))
        return errors
    if threshold < 0:
        errors.append(
            _error("invalid_threshold", "threshold must be non-negative", f"{path}.threshold")
        )
    if resource in PERCENT_RESOURCES and threshold > 100:
        errors.append(
            _error(
                "impossible_objective",
                f"{resource} cannot exceed 100",
                f"{path}.threshold",
            )
        )
    if resource in UNIT_INTERVAL_RESOURCES and threshold > 1:
        errors.append(
            _error(
                "impossible_objective",
                f"{resource} cannot exceed 1",
                f"{path}.threshold",
            )
        )
    return errors


def _extra_parameter_errors(
    parameters: dict[str, JsonValue], expected: set[str], path: str
) -> list[CompilerValidationError]:
    missing = expected - parameters.keys()
    extra = parameters.keys() - expected
    return [
        *(
            _error("missing_parameter", f"missing parameter: {name}", f"{path}.{name}")
            for name in sorted(missing)
        ),
        *(
            _error("unsupported_parameter", f"unsupported parameter: {name}", f"{path}.{name}")
            for name in sorted(extra)
        ),
    ]


def _validate_objective(
    specification: TaskSpecification, catalog: CompilerCapabilityCatalog
) -> list[CompilerValidationError]:
    objective = specification.objective
    parameters = objective.parameters
    path = "specification.objective.parameters"
    if objective.type is ObjectiveType.COMPLETE_PROJECT:
        errors = _extra_parameter_errors(parameters, {"project_type"}, path)
        project_type = parameters.get("project_type")
        if not isinstance(project_type, str) or project_type not in catalog.project_types:
            errors.append(
                _error(
                    "invalid_project_type",
                    f"project_type must be one of {sorted(catalog.project_types)}",
                    f"{path}.project_type",
                )
            )
        return errors

    expected = {"resource", "target"}
    if objective.type in {ObjectiveType.MAINTAIN_RESOURCE, ObjectiveType.RUN_UNTIL}:
        expected.add("direction")
    errors = _extra_parameter_errors(parameters, expected, path)
    resource = parameters.get("resource")
    if not isinstance(resource, str) or resource not in catalog.resources:
        errors.append(
            _error("invalid_resource", f"unsupported resource: {resource!r}", f"{path}.resource")
        )
        return errors
    is_string_equality = (
        resource in catalog.string_resources
        and objective.type is ObjectiveType.RUN_UNTIL
        and parameters.get("direction") == "equal"
        and isinstance(parameters.get("target"), str)
    )
    if not is_string_equality:
        errors.extend(
            _validate_resource_threshold(
                resource, parameters.get("target"), path=path, catalog=catalog
            )
        )
    if "direction" in expected and parameters.get("direction") not in {
        "above",
        "below",
        "equal",
    }:
        errors.append(
            _error(
                "invalid_direction",
                "direction must be 'above', 'below', or 'equal'",
                f"{path}.direction",
            )
        )
    return errors


def _action_values(value: JsonValue | None) -> set[str] | None:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(cast("list[str]", value))
    return None


def _invalid_actions(actions: Iterable[str], catalog: CompilerCapabilityCatalog) -> set[str]:
    return set(actions) - set(catalog.actions)


def _validate_constraints(
    specification: TaskSpecification,
    catalog: CompilerCapabilityCatalog,
) -> tuple[list[CompilerValidationError], list[set[str]], set[str], list[tuple[str, float]]]:
    errors: list[CompilerValidationError] = []
    allowed_sets: list[set[str]] = []
    forbidden: set[str] = set(specification.authority.forbidden_actions)
    floors: list[tuple[str, float]] = []
    for index, constraint in enumerate(specification.constraints):
        path = f"specification.constraints.{index}.parameters"
        parameters = constraint.parameters
        if constraint.type is ConstraintType.FORBIDDEN_ACTION:
            errors.extend(_extra_parameter_errors(parameters, {"action"}, path))
            actions = _action_values(parameters.get("action"))
            if actions is None or len(actions) != 1:
                errors.append(
                    _error(
                        "invalid_action", "forbidden_action requires one action", f"{path}.action"
                    )
                )
            else:
                forbidden.update(actions)
                for action in sorted(_invalid_actions(actions, catalog)):
                    errors.append(
                        _error("invalid_action", f"unsupported action: {action}", f"{path}.action")
                    )
        elif constraint.type is ConstraintType.ALLOWED_ACTION:
            expected = {"actions"} if "actions" in parameters else {"action"}
            errors.extend(_extra_parameter_errors(parameters, expected, path))
            actions = _action_values(parameters.get(next(iter(expected), "actions")))
            if not actions:
                errors.append(
                    _error("invalid_action", "allowed_action requires actions", f"{path}.actions")
                )
            else:
                allowed_sets.append(actions)
                for action in sorted(_invalid_actions(actions, catalog)):
                    errors.append(
                        _error("invalid_action", f"unsupported action: {action}", f"{path}.actions")
                    )
        elif constraint.type in {ConstraintType.MAXIMUM_SPEND, ConstraintType.MINIMUM_RESERVE}:
            errors.extend(_extra_parameter_errors(parameters, {"amount"}, path))
            amount = _numeric(parameters.get("amount"))
            if amount is None or amount < 0:
                errors.append(
                    _error("invalid_threshold", "amount must be non-negative", f"{path}.amount")
                )
        elif constraint.type is ConstraintType.RESOURCE_FLOOR:
            errors.extend(_extra_parameter_errors(parameters, {"resource", "floor"}, path))
            resource = parameters.get("resource")
            errors.extend(
                _validate_resource_threshold(
                    resource, parameters.get("floor"), path=path, catalog=catalog
                )
            )
            floor = _numeric(parameters.get("floor"))
            if isinstance(resource, str) and floor is not None:
                floors.append((resource, floor))
    return errors, allowed_sets, forbidden, floors


def validate_specification(
    specification: TaskSpecification | None,
    catalog: CompilerCapabilityCatalog = REFERENCE_CAPABILITIES,
) -> tuple[CompilerValidationError, ...]:
    if specification is None:
        return ()
    errors = _validate_objective(specification, catalog)
    constraint_errors, allowed_sets, forbidden, floors = _validate_constraints(
        specification, catalog
    )
    errors.extend(constraint_errors)

    authority = specification.authority
    for path, actions in (
        ("specification.authority.forbidden_actions", authority.forbidden_actions),
        ("specification.authority.approval_actions", authority.approval_actions),
    ):
        for action in sorted(_invalid_actions(actions, catalog)):
            errors.append(_error("invalid_action", f"unsupported action: {action}", path))
    approval_forbidden = set(authority.approval_actions) & forbidden
    if approval_forbidden:
        errors.append(
            _error(
                "contradictory_authority",
                f"actions cannot require approval and be forbidden: {sorted(approval_forbidden)}",
                "specification.authority",
            )
        )
    if allowed_sets:
        allowed = allowed_sets[0].intersection(*allowed_sets[1:])
        if not allowed:
            errors.append(
                _error(
                    "contradictory_constraints",
                    "allowed_action constraints have no action in common",
                    "specification.constraints",
                )
            )
        elif allowed <= forbidden:
            errors.append(
                _error(
                    "contradictory_constraints",
                    "every allowed action is also forbidden",
                    "specification.constraints",
                )
            )

    objective = specification.objective
    if (
        objective.type is ObjectiveType.RUN_UNTIL
        and objective.parameters.get("direction") == "below"
    ):
        resource = objective.parameters.get("resource")
        target = _numeric(objective.parameters.get("target"))
        if isinstance(resource, str) and target is not None:
            conflicting = [floor for name, floor in floors if name == resource and floor >= target]
            if conflicting:
                errors.append(
                    _error(
                        "contradictory_constraints",
                        f"resource floor prevents running {resource} below {target:g}",
                        "specification.constraints",
                    )
                )

    for index, condition in enumerate(specification.stop_conditions):
        match = STOP_CONDITION.fullmatch(condition)
        if match is None:
            errors.append(
                _error(
                    "invalid_stop_condition",
                    f"unsupported stop condition: {condition}",
                    f"specification.stop_conditions.{index}",
                )
            )
        elif match.group("resource") not in catalog.resources:
            errors.append(
                _error(
                    "invalid_resource",
                    f"unsupported stop-condition resource: {match.group('resource')}",
                    f"specification.stop_conditions.{index}",
                )
            )
    return tuple(errors)
