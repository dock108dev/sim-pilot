"""Safety prompts for structured analysis compilation and explanation."""

ANALYSIS_COMPILER_PROMPT = """
Map the player question to the supplied AnalysisCompilation schema.
Use only the closed analysis types and semantic fields in the schema.
Do not invent entity IDs, comparison snapshots, periods, evidence, or capabilities.
Return clarification when required context is absent and unsupported_reason when the canonical
snapshot cannot support the request. Analysis is read-only.
""".strip()

ANALYSIS_EXPLANATION_PROMPT = """
Explain only the supplied deterministic findings, evidence, recommendations, and limitations.
Every factual claim must reference supplied identifiers. Preserve every metric name, value,
severity, and confidence exactly. Do not add facts, evidence, causal certainty, or executable
instructions.
Return only the structured AnalysisExplanation schema.
""".strip()

COMPILER_PROMPT_VERSION = "analysis-compiler-v1"
EXPLANATION_PROMPT_VERSION = "analysis-explanation-v1"
