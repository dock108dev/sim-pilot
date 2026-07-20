"""Safety prompts for structured analysis compilation and explanation."""

ANALYSIS_COMPILER_PROMPT = """
Map the player question to the supplied AnalysisCompilation schema.
Use only the closed analysis types and semantic fields in the schema.
Preserve the player's analyzer, subject, filter, ranking, period, and comparison semantics. Set
answer_intent to null: the trusted deterministic normalizer derives canonical question forms,
concept, metric, premise, conversational reference, and evidence requirements after validating the
provider-selected request. Do not duplicate those conditional contracts in provider output. Do not
replace a requested ranking metric with a nearby available one.
Do not invent entity IDs, comparison snapshots, periods, evidence, or capabilities.
The bounded resolution context is authoritative but not part of the player's question. Use its
comparison_snapshot_id when the question requests change or comparison. Use focus_entities and
prior_findings only to resolve explicit follow-up words such as "that"; do not scope broad ranking
questions merely because context is available. Entity counts are descriptive only.
Return clarification when required context is absent and unsupported_reason when the canonical
snapshot cannot support the request. Set subject_type when the question names an entity class even
when subject_ids is empty. Provide subject_ids only when the player supplied or context resolved
canonical entity IDs. Crash causality, predictive forecasts, construction, optimization, and
gameplay mutation are unsupported rather than clarification requests. Analysis is read-only.
Requests must use only subjects, filters, and ranking metrics allowed by the supplied compatibility
catalog. Normalize train to vehicle_type "rail", road vehicle to "road", ship to "water", and
aircraft to "air". Idle vehicles map to vehicle_performance. Underserved stations map to
station_performance. Losing vehicles grouped by route map to route_performance without profit
filters. Population or cargo changes map to world_changes without population or waiting-cargo
ranking. A station follow-up maps to station_performance or entity_summary, not service_coverage.
"Which route is bad?" requires clarification because bad has no chosen metric.
"Why am I losing money?" is company-level loss intent with an asserted premise and observed net
operating result. Debt requests use financial_summary and loan. Available-cash requests use cash.
"Which trains performed best last year?" preserves rail, descending profit_last_year, and last-year
period. "Which routes have the most losing vehicles?" preserves route_negative_vehicle_count
intent and must not become total vehicle_count. Comparison intent remains required even with a
compatible ID.
""".strip()

ANALYSIS_EXPLANATION_PROMPT = """
Explain only the supplied deterministic findings, evidence, typed inspection guidance,
recommendations, and limitations.
Every factual claim must reference supplied identifiers. Preserve every metric name, value,
severity, and confidence exactly. Do not add facts, evidence, causal certainty, or executable
instructions. The typed inspection guidance is authoritative: wording may be clearer, but the
target, observation, diagnostic distinction, and unavailable state must not change. Label
recommendations as recommendations, never facts. Preserve critical limitations
with limitation statements that reference the affected finding IDs. Use the requested compact,
coach, or technical style without adding generic strategy advice.
If recommendation_ids is non-empty, claim_type must be recommendation. Otherwise leave
recommendation_ids empty. Never attach recommendation IDs to summary or contributor statements.
Recommendation wording must include the exact inspection target label, target entity ID when one
exists, and every supporting finding ID from the typed guidance.
Return only the structured AnalysisExplanation schema.
""".strip()

COMPILER_PROMPT_VERSION = "analysis-compiler-v5"
EXPLANATION_PROMPT_VERSION = "analysis-explanation-v2"
