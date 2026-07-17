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
