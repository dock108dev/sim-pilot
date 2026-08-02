"""Typed failures for Software Inc. discovery and probe lifecycle."""


class SoftwareIncError(RuntimeError):
    """Base error for the Software Inc. integration boundary."""

    reason_code = "software_inc_error"


class SoftwareIncDiscoveryError(SoftwareIncError):
    """Local installation or process evidence could not be collected safely."""

    reason_code = "discovery_failed"


class SoftwareIncCompatibilityError(SoftwareIncError):
    """The exact local installation cannot load the official probe safely."""

    reason_code = "incompatible_installation"


class SoftwareIncForegroundError(SoftwareIncError):
    """The already-running Software Inc. process could not be foregrounded."""

    reason_code = "foreground_failed"


class SoftwareIncProbeInstallError(SoftwareIncError):
    """A reversible probe lifecycle operation failed closed."""

    reason_code = "probe_install_failed"


class SoftwareIncUIError(SoftwareIncError):
    """Base failure for verified visible-UI observation or control."""

    reason_code = "ui_control_failed"


class SoftwareIncUIObservationError(SoftwareIncUIError):
    """A synchronized, unambiguous UI observation could not be produced."""

    reason_code = "ui_observation_failed"


class SoftwareIncUIValidationError(SoftwareIncUIError):
    """A proposed UI gesture failed deterministic preflight validation."""

    reason_code = "ui_validation_failed"


class SoftwareIncUIVerificationError(SoftwareIncUIError):
    """Input may have been sent but its expected effect was not proven."""

    reason_code = "effect_unverified"
