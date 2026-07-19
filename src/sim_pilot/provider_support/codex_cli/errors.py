"""Typed failures for the local Codex CLI subprocess boundary."""


class CodexCLIError(RuntimeError):
    """Base failure for capability probing or isolated execution."""


class CodexCLIExecutableNotFoundError(CodexCLIError):
    """The configured Codex executable could not be located."""


class CodexCLICompatibilityError(CodexCLIError):
    """The installed CLI lacks a required provider capability."""


class CodexCLIUnauthenticatedError(CodexCLIError):
    """The CLI has no authenticated session usable by codex exec."""


class CodexCLIProcessStartError(CodexCLIError):
    """The subprocess could not be started."""


class CodexCLITimeoutError(CodexCLIError):
    """The subprocess exceeded its configured deadline."""


class CodexCLIProcessTerminationError(CodexCLIError):
    """A timed-out or invalid subprocess could not be terminated."""


class CodexCLINonzeroExitError(CodexCLIError):
    """The subprocess exited unsuccessfully without a more specific classification."""


class CodexCLIAuthenticationExpiredError(CodexCLINonzeroExitError):
    """The cached Codex authentication was rejected or expired."""


class CodexCLIUsageLimitError(CodexCLINonzeroExitError):
    """The authenticated Codex plan limit or credit allowance was exhausted."""


class CodexCLIRefusalError(CodexCLIError):
    """Codex refused to return the requested structured result."""


class CodexCLISandboxError(CodexCLINonzeroExitError):
    """The required read-only sandbox could not be established."""


class CodexCLIMalformedJSONLError(CodexCLIError):
    """Stdout contained a malformed JSONL event."""


class CodexCLITelemetryError(CodexCLIError):
    """Terminal or usage telemetry was internally inconsistent."""


class CodexCLIOutputLimitError(CodexCLIError):
    """Stdout or stderr exceeded its configured byte limit."""


class CodexCLIMissingFinalResponseError(CodexCLIError):
    """Execution completed without exactly one structured final response."""


class CodexCLIConflictingFinalResponseError(CodexCLIError):
    """The event stream contained conflicting final agent responses."""


class CodexCLIInvalidStructuredOutputError(CodexCLIError):
    """The final response did not validate against the canonical Pydantic model."""


class CodexCLITemporaryDirectoryError(CodexCLIError):
    """The isolated temporary directory could not be created or cleaned."""


class CodexCLISchemaFileError(CodexCLIError):
    """The output JSON Schema could not be written safely."""
