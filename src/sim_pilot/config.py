"""Small environment and CLI configuration boundary."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfiguration:
    database_url: str


def database_url(value: str | None = None) -> str:
    configured = value or os.getenv("SIM_PILOT_DATABASE") or "data/sim-pilot.db"
    if configured.startswith("sqlite:///"):
        return configured
    return f"sqlite:///{Path(configured).expanduser().resolve()}"
