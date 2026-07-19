"""Typed failures at the read-only analysis boundary."""


class AnalysisError(Exception):
    """Base class for deterministic analysis failures."""


class AnalysisRequestError(AnalysisError):
    """A structurally valid request is unsupported by the selected analysis."""


class AnalysisInputError(AnalysisError):
    """Required canonical snapshot evidence is absent or ambiguous."""


class AnalysisComparisonError(AnalysisError):
    """Two snapshots cannot be compared safely."""


class AnalyzerRegistrationError(AnalysisError):
    """Analyzer registration is missing or conflicting."""


class AnalyzerResultError(AnalysisError):
    """An analyzer returned internally inconsistent references."""
