"""Versioned, environment-specific prompt contract for the Intent Compiler."""

from sim_pilot.adapter_registry import adapter_registration
from sim_pilot.domain import AdapterId
from sim_pilot.intent_compiler.models import CompilerCapabilityCatalog

PROMPT_VERSION = "intent-compiler-v3"

SUPPORTED_RESOURCES = (
    "tick",
    "cash",
    "debt",
    "population",
    "housing",
    "power_capacity",
    "power_usage",
    "infrastructure",
    "maintenance_level",
    "income_per_tick",
    "expense_per_tick",
)

SUPPORTED_ACTIONS = (
    "advance_time",
    "build_housing",
    "build_power",
    "repair",
    "set_maintenance",
    "take_loan",
    "repay_loan",
    "pause",
    "resume",
)

REFERENCE_CAPABILITIES = CompilerCapabilityCatalog(
    name="reference_simulation",
    adapter_type=AdapterId.REFERENCE,
    resources=SUPPORTED_RESOURCES,
    actions=SUPPORTED_ACTIONS,
    project_types=("housing", "power"),
)

OPENTTD_CAPABILITIES = CompilerCapabilityCatalog(
    name="openttd_admin_network_v3_gamescript_v1",
    adapter_type=AdapterId.OPENTTD,
    resources=(
        "cash",
        "debt",
        "company_value",
        "profit",
        "vehicle_count",
        "station_count",
        "date_raw",
        "server_name",
        "paused",
        "town_count",
        "industry_count",
        "company_name",
    ),
    actions=("set_server_name", "set_company_name"),
    string_resources=("server_name", "company_name"),
)

RAIL_ROUTE_CAPABILITIES = CompilerCapabilityCatalog(
    name="rail_route_reference_integration_unavailable_to_task_runtime",
    adapter_type=AdapterId.RAIL_ROUTE,
    resources=(),
    actions=(),
)

SOFTWARE_INC_CAPABILITIES = CompilerCapabilityCatalog(
    name="software_inc_prompt_1_discovery_only",
    adapter_type=AdapterId.SOFTWARE_INC,
    resources=(),
    actions=(),
)

CAPABILITY_CATALOGS = {
    REFERENCE_CAPABILITIES.adapter_type: REFERENCE_CAPABILITIES,
    OPENTTD_CAPABILITIES.adapter_type: OPENTTD_CAPABILITIES,
    RAIL_ROUTE_CAPABILITIES.adapter_type: RAIL_ROUTE_CAPABILITIES,
    SOFTWARE_INC_CAPABILITIES.adapter_type: SOFTWARE_INC_CAPABILITIES,
}


def capability_catalog(adapter_type: str) -> CompilerCapabilityCatalog:
    """Return the sole supported catalog for an adapter or fail explicitly."""
    try:
        registration = adapter_registration(adapter_type)
        return CAPABILITY_CATALOGS[registration.adapter_id]
    except (KeyError, ValueError) as error:
        raise ValueError(f"unsupported adapter type: {adapter_type!r}") from error


INTENT_COMPILER_PROMPT = f"""
You are the Sim Pilot Intent Compiler, prompt version {PROMPT_VERSION}.

Translate one user instruction into structured CompilerResponse data only. Do not plan actions,
choose an action sequence, predict strategy, or execute anything. The runtime remains responsible
for decisions and execution.

Supported objective types and exact parameters:
- reach_resource: resource, numeric target
- maintain_resource: resource, numeric target, direction (above or below)
- run_until: resource, numeric target, direction (above or below)
- complete_project: project_type (housing or power)

Supported resources: {", ".join(SUPPORTED_RESOURCES)}.
Supported actions: {", ".join(SUPPORTED_ACTIONS)}.

Supported constraint types:
- forbidden_action with action
- allowed_action with actions
- minimum_reserve with amount
- maximum_spend with amount
- resource_floor with resource and floor

Authority fields:
- maximum_single_spend means ask for approval above a per-action cost
- maximum_total_spend is a hard cumulative ceiling
- approval_actions lists actions requiring approval
- forbidden_actions lists actions never allowed

Put notification requests in notifications. Put deterministic stop expressions in stop_conditions
using '<resource> <operator> <number>', where operator is >, >=, <, <=, or ==.

Never invent a resource, action, threshold, project type, runtime capability, or missing number.
When the user requires a particular action as the method for reaching an objective, preserve that
method as an allowed_action constraint. If that same action is forbidden, preserve both rules so
deterministic validation can reject the contradiction; never silently discard the required method.
maintenance_level accepts only 0, 0.5, or 1. If maintenance wording uses a percentage-like value
such as 90 without clearly identifying maintenance_level, request clarification instead of scaling
or emitting an impossible threshold.
If material information is missing, return no specification and describe it in ambiguities. If the
request is outside supported capabilities, return no specification and describe it in
unsupported_requests. Report every minor interpretation in assumptions. Use warnings for supported
but risky or surprising intent. Broad requests such as 'beat the game', 'win efficiently', or
'make smart decisions' are unsupported. All tuple fields must be present, using empty arrays when
there are no entries.
""".strip()


def compiler_prompt(catalog: CompilerCapabilityCatalog) -> str:
    if catalog == REFERENCE_CAPABILITIES:
        return INTENT_COMPILER_PROMPT
    string_guidance = (
        " String resources use run_until with direction equal and an exact string target."
        if catalog.string_resources
        else ""
    )
    resources = ", ".join(catalog.resources) or "none"
    actions = ", ".join(catalog.actions) or "none"
    return f"""
You are the Sim Pilot Intent Compiler, prompt version {PROMPT_VERSION}.

Translate one user instruction into structured CompilerResponse data only. The active environment
is {catalog.name}. Supported resources: {resources}. Supported actions: {actions}.{string_guidance}

Use only reach_resource, maintain_resource, run_until, and complete_project objectives and the
existing TaskSpecification schema. Never invent capabilities. If a request requires any action or
resource outside this catalog, return no specification and put the request in unsupported_requests.
For numeric resources, use reach_resource without a direction parameter and use run_until only
when the instruction explicitly asks to wait or monitor until the threshold is reached. A supported
observed resource may be a passive run_until objective even when no advertised action changes it.
For an instruction to set a supported string resource, compile a run_until equality objective and
use the matching action in allowed_action constraints when appropriate. Preserve explicit approval
and forbidden-action language. Report material missing information in ambiguities. Return structured
data only and include every tuple field, using empty arrays when needed.
""".strip()
