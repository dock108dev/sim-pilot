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


def test_reference_simulation_does_not_import_adapters_or_runtime() -> None:
    simulation_files = (PACKAGE_ROOT / "reference_simulation").rglob("*.py")
    forbidden_prefixes = ("sim_pilot.adapters", "sim_pilot.runtime")

    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden_prefixes)
        )
        for path in simulation_files
    }
    violations = {path: modules for path, modules in violations.items() if modules}

    assert not violations, (
        "The reference simulation must remain independent of adapters and runtime modules: "
        f"{violations}"
    )


def test_event_store_does_not_import_adapters() -> None:
    event_store = PACKAGE_ROOT / "runtime" / "events.py"

    violations = sorted(
        module
        for module in imported_modules(event_store)
        if module.startswith("sim_pilot.adapters")
    )

    assert not violations, f"Event stores must not depend on adapters: {violations}"


def test_pure_runtime_components_do_not_execute_actions() -> None:
    for name in ("evaluator.py", "policy.py", "verification.py"):
        path = PACKAGE_ROOT / "runtime" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls_execute = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            for node in ast.walk(tree)
        )
        assert not calls_execute, f"{name} must not execute actions"
