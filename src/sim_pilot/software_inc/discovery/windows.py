"""Explicitly unverified Windows discovery design boundary."""

from pathlib import Path


def default_windows_steamapps() -> tuple[Path, ...]:
    """Return conventional candidates; no Windows runtime claim is made."""
    return (
        Path("C:/Program Files (x86)/Steam/steamapps"),
        Path("C:/Program Files/Steam/steamapps"),
    )
