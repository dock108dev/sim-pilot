"""Typed failures crossing the runtime decision-provider boundary."""


class DecisionProviderError(RuntimeError):
    """Base class for decision-provider failures."""


class DecisionProviderNotConfiguredError(DecisionProviderError):
    """No runtime decision provider was explicitly selected."""


class DecisionAuthenticationError(DecisionProviderError):
    """Provider credentials were missing or rejected."""


class DecisionTimeoutError(DecisionProviderError):
    """The provider request exceeded its configured timeout."""


class DecisionRateLimitError(DecisionProviderError):
    """The provider rejected the request due to rate limiting."""


class DecisionProviderUnavailableError(DecisionProviderError):
    """The provider could not be reached or was unavailable."""


class MalformedDecisionOutputError(DecisionProviderError):
    """Structured output did not satisfy the response schema."""


class DecisionSemanticValidationError(DecisionProviderError):
    """A schema-valid decision violated deterministic context rules."""


class DecisionContextTooLargeError(DecisionProviderError):
    """The bounded decision context cannot fit the configured limit."""


class DecisionRefusalError(DecisionProviderError):
    """The provider refused to select a decision."""


class EmptyDecisionResponseError(DecisionProviderError):
    """The provider returned no structured decision."""


class DecisionRecordingError(DecisionProviderError):
    """An explicitly requested decision recording could not be committed."""
