"""Storage-independent persistence failures."""


class PersistenceError(Exception):
    """Base class for failures crossing a repository boundary."""


class RecordNotFoundError(PersistenceError):
    """A requested durable record does not exist."""


class DuplicateRecordError(PersistenceError):
    """A stable identifier or uniqueness key already exists."""


class SequenceConflictError(PersistenceError):
    """An append or checkpoint did not follow the durable sequence."""


class StaleUpdateError(PersistenceError):
    """An update would replace a newer durable value."""


class TransactionError(PersistenceError):
    """A transaction could not begin, commit, or roll back."""


class UnsupportedSchemaVersionError(PersistenceError):
    """A durable record uses a schema version this runtime cannot read."""


class InvalidPersistedPayloadError(PersistenceError):
    """Stored data cannot be validated against its typed contract."""
