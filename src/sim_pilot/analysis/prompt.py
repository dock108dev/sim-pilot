"""Safety prompts for structured analysis compilation and explanation."""

ANALYSIS_COMPILER_PROMPT = """
Map the player question to the supplied AnalysisCompilation schema.
Use only the closed analysis types and semantic fields in the schema.
Do not invent entity IDs, comparison snapshots, periods, evidence, or capabilities.
Return clarification when required context is absent and unsupported_reason when the canonical
snapshot cannot support the request. Set subject_type to null whenever subject_ids is empty; provide
subject_type and subject_ids together only when the player supplied resolvable canonical entity IDs.
Use an empty subject_ids array for an unscoped company, fleet, station, route, town, industry, or
world question. Analysis is read-only.
""".strip()

ANALYSIS_EXPLANATION_PROMPT = """
Explain only the supplied deterministic findings, evidence, recommendations, and limitations.
Every factual claim must reference supplied identifiers. Preserve every metric name, value,
severity, and confidence exactly. Do not add facts, evidence, causal certainty, or executable
instructions. Label recommendations as recommendations, never facts. Preserve critical limitations
with limitation statements that reference the affected finding IDs. Use the requested compact,
coach, or technical style without adding generic strategy advice.
Return only the structured AnalysisExplanation schema.
""".strip()

COMPILER_PROMPT_VERSION = "analysis-compiler-v2"
EXPLANATION_PROMPT_VERSION = "analysis-explanation-v1"
