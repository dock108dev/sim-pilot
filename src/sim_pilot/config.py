"""Small environment and CLI configuration boundary."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfiguration:
    database_url: str
    compiler_model: str
    decision_model: str
    decision_timeout_seconds: float


def database_url(value: str | None = None) -> str:
    configured = value or os.getenv("SIM_PILOT_DATABASE") or "data/sim-pilot.db"
    if configured.startswith("sqlite:///"):
        return configured
    return f"sqlite:///{Path(configured).expanduser().resolve()}"


def compiler_model(value: str | None = None) -> str:
    return value or os.getenv("SIM_PILOT_COMPILER_MODEL") or "gpt-5.6"


def decision_model(value: str | None = None) -> str:
    return value or os.getenv("SIM_PILOT_DECISION_MODEL") or "gpt-5.6"


def codex_model(value: str | None = None) -> str:
    return value or os.getenv("SIM_PILOT_CODEX_MODEL") or "gpt-5.6-sol"


def decision_timeout_seconds(value: float | None = None) -> float:
    if value is not None:
        configured = value
    else:
        raw = os.getenv("SIM_PILOT_DECISION_TIMEOUT_SECONDS", "30")
        try:
            configured = float(raw)
        except ValueError as error:
            raise ValueError("SIM_PILOT_DECISION_TIMEOUT_SECONDS must be numeric") from error
    if configured <= 0:
        raise ValueError("decision timeout must be positive")
    return configured


def codex_executable(value: Path | None = None) -> Path | None:
    configured = value or (Path(raw) if (raw := os.getenv("SIM_PILOT_CODEX_EXECUTABLE")) else None)
    return None if configured is None else configured.expanduser().resolve()


def codex_timeout_seconds(value: float | None = None) -> float:
    if value is not None:
        configured = value
    else:
        raw = os.getenv("SIM_PILOT_CODEX_TIMEOUT_SECONDS", "120")
        try:
            configured = float(raw)
        except ValueError as error:
            raise ValueError("SIM_PILOT_CODEX_TIMEOUT_SECONDS must be numeric") from error
    if configured <= 0:
        raise ValueError("Codex CLI timeout must be positive")
    return configured


def codex_temporary_directory_root(value: Path | None = None) -> Path | None:
    configured = value or (
        Path(raw) if (raw := os.getenv("SIM_PILOT_CODEX_TEMPORARY_ROOT")) else None
    )
    return None if configured is None else configured.expanduser().resolve()


def codex_preserve_debug_directory(value: bool | None = None) -> bool:
    if value is not None:
        return value
    return os.getenv("SIM_PILOT_CODEX_PRESERVE_DEBUG_DIRECTORY", "0") == "1"


def _positive_codex_integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        configured = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if configured <= 0:
        raise ValueError(f"{name} must be positive")
    return configured


def codex_maximum_stdout_bytes() -> int:
    return _positive_codex_integer("SIM_PILOT_CODEX_MAXIMUM_STDOUT_BYTES", 2_000_000)


def codex_maximum_stderr_bytes() -> int:
    return _positive_codex_integer("SIM_PILOT_CODEX_MAXIMUM_STDERR_BYTES", 64_000)


def codex_capability_cache_seconds() -> float:
    raw = os.getenv("SIM_PILOT_CODEX_CAPABILITY_CACHE_SECONDS", "60")
    try:
        configured = float(raw)
    except ValueError as error:
        raise ValueError("SIM_PILOT_CODEX_CAPABILITY_CACHE_SECONDS must be numeric") from error
    if configured < 0:
        raise ValueError("SIM_PILOT_CODEX_CAPABILITY_CACHE_SECONDS must not be negative")
    return configured
