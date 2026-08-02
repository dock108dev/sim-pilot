import subprocess

import pytest

from sim_pilot.software_inc.discovery import macos


def test_window_identity_is_bound_to_exact_process_and_largest_game_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def completed(
        _args: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=["osascript"],
            returncode=0,
            stdout="Software Inc\x1f10\x1f20\x1f1440\x1f900\n",
            stderr="",
        )

    monkeypatch.setattr(macos.subprocess, "run", completed)
    monkeypatch.setattr(macos, "_main_display_scale", lambda: 2.0)

    assert macos.window_identity(123) == ("Software Inc", 10, 20, 1440, 900, 2.0)


def test_window_identity_rejects_ambiguous_or_missing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(
        _args: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["osascript"], returncode=1, stdout="", stderr="ambiguous"
        )

    monkeypatch.setattr(macos.subprocess, "run", failed)

    assert macos.window_identity(123) is None
