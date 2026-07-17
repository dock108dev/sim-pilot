"""Typed failures at the intent-compiler provider boundary."""


class CompilerError(RuntimeError):
    """Base class for intent compilation failures."""


class CompilerProviderError(CompilerError):
    """The hosted or scripted provider could not produce a response."""


class InvalidCompilerOutputError(CompilerError):
    """Provider output did not satisfy the structured response contract."""
