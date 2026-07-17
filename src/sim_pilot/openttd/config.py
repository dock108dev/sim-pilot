"""Configuration for the loopback-only OpenTTD integration."""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

SUPPORTED_OPENTTD_VERSION = "15.3"
SUPPORTED_ADMIN_PROTOCOL = 3


class OpenTTDConfiguration(BaseModel):
    """Validated connection and local-development settings."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=3977, ge=1, le=65535)
    password: SecretStr
    company_id: int = Field(default=0, ge=0, le=14)
    expected_version: str = SUPPORTED_OPENTTD_VERSION
    expected_protocol: int = Field(default=SUPPORTED_ADMIN_PROTOCOL, ge=1)
    connection_timeout_seconds: float = Field(default=5.0, gt=0)
    observation_timeout_seconds: float = Field(default=5.0, gt=0)
    polling_interval_seconds: float = Field(default=1.0, ge=0.1)
    action_timeout_seconds: float = Field(default=5.0, gt=0)
    stale_observation_threshold_days: int = Field(default=3, ge=0)
    allow_writes: bool = False
    gamescript_enabled: bool = False
    allow_gamescript_writes: bool = False
    executable: Path | None = None
    required_script_path: Path | None = None
    save_path: Path | None = None

    @model_validator(mode="after")
    def require_loopback_for_plaintext_admin_login(self) -> OpenTTDConfiguration:
        """Never transmit the Task 6B admin password beyond loopback."""
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(self.host, self.port)}
        except socket.gaierror as error:
            raise ValueError(f"OpenTTD host cannot be resolved: {self.host}") from error
        if not addresses or any(
            not ipaddress.ip_address(address).is_loopback for address in addresses
        ):
            raise ValueError("Task 6B plaintext admin authentication requires a loopback host")
        return self


def _positive_float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _optional_path(name: str) -> Path | None:
    raw = os.getenv(name)
    return Path(raw).expanduser() if raw else None


def _enabled(name: str) -> bool:
    value = os.getenv(name, "0")
    if value not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1")
    return value == "1"


def openttd_configuration() -> OpenTTDConfiguration:
    """Load OpenTTD settings without initializing any hosted provider."""
    password = os.getenv("SIM_PILOT_OPENTTD_ADMIN_PASSWORD")
    if not password:
        raise ValueError("SIM_PILOT_OPENTTD_ADMIN_PASSWORD is required")
    try:
        port = int(os.getenv("SIM_PILOT_OPENTTD_PORT", "3977"))
        company_id = int(os.getenv("SIM_PILOT_OPENTTD_COMPANY_ID", "0"))
    except ValueError as error:
        raise ValueError("OpenTTD port and company ID must be integers") from error
    return OpenTTDConfiguration(
        host=os.getenv("SIM_PILOT_OPENTTD_HOST", "127.0.0.1"),
        port=port,
        password=SecretStr(password),
        company_id=company_id,
        expected_version=os.getenv("SIM_PILOT_OPENTTD_VERSION", SUPPORTED_OPENTTD_VERSION),
        expected_protocol=SUPPORTED_ADMIN_PROTOCOL,
        connection_timeout_seconds=_positive_float(
            "SIM_PILOT_OPENTTD_CONNECTION_TIMEOUT_SECONDS", "5"
        ),
        observation_timeout_seconds=_positive_float(
            "SIM_PILOT_OPENTTD_OBSERVATION_TIMEOUT_SECONDS", "5"
        ),
        polling_interval_seconds=_positive_float("SIM_PILOT_OPENTTD_POLL_INTERVAL_SECONDS", "1"),
        action_timeout_seconds=_positive_float("SIM_PILOT_OPENTTD_ACTION_TIMEOUT_SECONDS", "5"),
        stale_observation_threshold_days=int(
            os.getenv("SIM_PILOT_OPENTTD_STALE_THRESHOLD_DAYS", "3")
        ),
        allow_writes=_enabled("SIM_PILOT_OPENTTD_ALLOW_WRITES"),
        gamescript_enabled=_enabled("SIM_PILOT_OPENTTD_GS_ENABLED"),
        allow_gamescript_writes=_enabled("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES"),
        executable=_optional_path("SIM_PILOT_OPENTTD_EXECUTABLE"),
        required_script_path=_optional_path("SIM_PILOT_OPENTTD_REQUIRED_SCRIPT"),
        save_path=_optional_path("SIM_PILOT_OPENTTD_SAVE_PATH"),
    )
