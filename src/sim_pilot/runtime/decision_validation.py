"""Deterministic semantic validation for untrusted provider decisions."""

import math
import re

from sim_pilot.adapters.base import ActionDefinition, ActionParameterDefinition, ActionParameterType
from sim_pilot.domain import Decision, DecisionType
from sim_pilot.domain.models import JsonValue
from sim_pilot.runtime.action_attempts import action_fingerprint
from sim_pilot.runtime.decision_context import DecisionContext
from sim_pilot.runtime.decision_errors import DecisionSemanticValidationError

FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def validate_provider_decision(decision: Decision, context: DecisionContext) -> str:
    """Return a stable action fingerprint after all context-local checks pass."""
    if decision.type is DecisionType.COMPLETE and not context.progress.complete:
        raise DecisionSemanticValidationError(
            "completion is not confirmed by the deterministic evaluator"
        )
    if decision.type is DecisionType.BLOCKED and not decision.reason.strip():
        raise DecisionSemanticValidationError("blocked decision requires a reason")
    if decision.action is None:
        return "no-action"
    if decision.action.type in {
        *context.pending_restrictions.rejected_actions,
        *context.pending_restrictions.denied_actions,
    }:
        raise DecisionSemanticValidationError(
            f"action was previously rejected or denied: {decision.action.type}"
        )
    if not decision.action.estimated_cost.is_finite():
        raise DecisionSemanticValidationError("estimated cost must be finite")
    definitions = {definition.type: definition for definition in context.available_actions}
    definition = definitions.get(decision.action.type)
    if definition is None:
        raise DecisionSemanticValidationError(
            f"action is not advertised by the adapter: {decision.action.type}"
        )
    _validate_parameters(decision.action.parameters, definition)
    fingerprint = action_fingerprint(decision.action)
    if FINGERPRINT.fullmatch(fingerprint) is None:
        raise DecisionSemanticValidationError("action fingerprint is invalid")
    return fingerprint


def _validate_parameters(parameters: dict[str, JsonValue], definition: ActionDefinition) -> None:
    schemas = {parameter.name: parameter for parameter in definition.parameters}
    missing = sorted(
        parameter.name
        for parameter in definition.parameters
        if parameter.required and parameter.name not in parameters
    )
    unknown = sorted(set(parameters) - set(schemas))
    if missing:
        raise DecisionSemanticValidationError(
            f"action {definition.type} is missing parameters: {', '.join(missing)}"
        )
    if unknown:
        raise DecisionSemanticValidationError(
            f"action {definition.type} has unknown parameters: {', '.join(unknown)}"
        )
    for name, value in parameters.items():
        _validate_parameter(value, schemas[name])


def _validate_parameter(value: JsonValue, schema: ActionParameterDefinition) -> None:
    if schema.type is ActionParameterType.INTEGER:
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    elif schema.type is ActionParameterType.NUMBER:
        valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif schema.type is ActionParameterType.STRING:
        valid_type = isinstance(value, str)
    else:
        valid_type = isinstance(value, bool)
    if not valid_type:
        raise DecisionSemanticValidationError(
            f"parameter {schema.name} must be {schema.type.value}"
        )
    if schema.allowed_values and value not in schema.allowed_values:
        raise DecisionSemanticValidationError(f"parameter {schema.name} is not an allowed value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise DecisionSemanticValidationError(f"parameter {schema.name} must be finite")
        if schema.minimum is not None:
            invalid = (
                numeric <= schema.minimum if schema.exclusive_minimum else numeric < schema.minimum
            )
            if invalid:
                comparator = "greater than" if schema.exclusive_minimum else "at least"
                raise DecisionSemanticValidationError(
                    f"parameter {schema.name} must be {comparator} {schema.minimum:g}"
                )
        if schema.maximum is not None and numeric > schema.maximum:
            raise DecisionSemanticValidationError(
                f"parameter {schema.name} must be at most {schema.maximum:g}"
            )
