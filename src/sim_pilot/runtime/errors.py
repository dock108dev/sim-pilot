"""Typed runtime persistence and reconstruction failures."""


class DurablePersistenceError(RuntimeError):
    """An atomic runtime persistence operation failed and rolled back."""


class ReconstructionConsistencyError(RuntimeError):
    """Durable records disagree and cannot be resumed safely."""
