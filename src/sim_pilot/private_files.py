"""Small shared helpers for owner-only local artifacts."""

from pathlib import Path


def ensure_private_directory(path: Path) -> None:
    """Create a directory and enforce owner-only access on an existing path too."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def atomic_write_private_text(path: Path, content: str) -> None:
    """Atomically replace one text file without leaving a permissive intermediate file."""
    ensure_private_directory(path.parent)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
