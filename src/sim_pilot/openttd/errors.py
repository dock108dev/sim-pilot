"""Typed failures at the OpenTTD integration boundary."""


class OpenTTDError(RuntimeError):
    """Base class for OpenTTD integration failures."""


class OpenTTDExecutableUnavailableError(OpenTTDError):
    """The configured local OpenTTD executable does not exist."""


class OpenTTDConnectionRefusedError(OpenTTDError):
    """The configured Admin Network endpoint refused the connection."""


class OpenTTDProtocolMismatchError(OpenTTDError):
    """The Admin Network protocol does not match the supported contract."""


class OpenTTDUnsupportedVersionError(OpenTTDError):
    """The connected OpenTTD application version is unsupported."""


class OpenTTDRequiredScriptUnavailableError(OpenTTDError):
    """A configured integration script cannot be found."""


class OpenTTDInvalidResponseError(OpenTTDError):
    """The server returned malformed or contradictory protocol data."""


class OpenTTDDisconnectedError(OpenTTDError):
    """The Admin Network session disconnected unexpectedly."""


class OpenTTDStateUnavailableError(OpenTTDError):
    """The requested company or required observation state is unavailable."""


class OpenTTDTimeoutError(OpenTTDError):
    """An OpenTTD connection or observation operation timed out."""
