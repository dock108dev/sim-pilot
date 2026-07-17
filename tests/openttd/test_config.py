"""OpenTTD configuration tests."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from sim_pilot.openttd.config import OpenTTDConfiguration, openttd_configuration


def test_configuration_accepts_local_admin_port() -> None:
    configuration = OpenTTDConfiguration(password=SecretStr("local-only"))

    assert configuration.host == "127.0.0.1"
    assert configuration.port == 3977
    assert configuration.expected_version == "15.3"
    assert configuration.expected_protocol == 3
    assert configuration.password.get_secret_value() == "local-only"


def test_configuration_rejects_non_loopback_plaintext_authentication() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        OpenTTDConfiguration(host="192.0.2.1", password=SecretStr("unsafe"))


def test_environment_configuration_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIM_PILOT_OPENTTD_ADMIN_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        openttd_configuration()


def test_environment_configuration_loads_all_supported_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIM_PILOT_OPENTTD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_PORT", "4977")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_COMPANY_ID", "2")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_EXECUTABLE", "/Applications/OpenTTD.app")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_ALLOW_WRITES", "1")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_GS_ENABLED", "1")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES", "1")

    configuration = openttd_configuration()

    assert configuration.port == 4977
    assert configuration.company_id == 2
    assert configuration.executable == Path("/Applications/OpenTTD.app")
    assert configuration.allow_writes is True
    assert configuration.gamescript_enabled is True
    assert configuration.allow_gamescript_writes is True


def test_gamescript_write_flag_requires_boolean_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIM_PILOT_OPENTTD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES", "yes")

    with pytest.raises(ValueError, match="must be 0 or 1"):
        openttd_configuration()


def test_configuration_rejects_invalid_company_and_timeout() -> None:
    with pytest.raises(ValidationError):
        OpenTTDConfiguration(password=SecretStr("secret"), company_id=15)
    with pytest.raises(ValidationError):
        OpenTTDConfiguration(password=SecretStr("secret"), observation_timeout_seconds=0.0)
