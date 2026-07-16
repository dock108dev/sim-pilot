"""Executable checks for package dependency direction."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "sim_pilot"


def imported_modules(path: Path) -> set[str]:
    """Return modules named by import statements in a Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_adapters_do_not_import_runtime() -> None:
    adapter_files = (PACKAGE_ROOT / "adapters").rglob("*.py")

    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith("sim_pilot.runtime")
        )
        for path in adapter_files
    }
    violations = {path: modules for path, modules in violations.items() if modules}

    assert not violations, f"Adapters must not import runtime modules: {violations}"
