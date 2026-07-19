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
    for name in ("evaluator.py", "policy.py", "verification.py", "reconstruction.py"):
        path = PACKAGE_ROOT / "runtime" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls_execute = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            for node in ast.walk(tree)
        )
        assert not calls_execute, f"{name} must not execute actions"


def test_runtime_contracts_do_not_import_storage_implementations() -> None:
    runtime_files = (PACKAGE_ROOT / "runtime").rglob("*.py")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module
            for module in imported_modules(path)
            if module.startswith(
                ("sim_pilot.persistence.sqlite", "sim_pilot.persistence.in_memory")
            )
        )
        for path in runtime_files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_persistence_interfaces_do_not_import_sqlite_implementations() -> None:
    interface_files = (
        PACKAGE_ROOT / "persistence" / "repositories.py",
        PACKAGE_ROOT / "persistence" / "unit_of_work.py",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module
            for module in imported_modules(path)
            if module.startswith("sim_pilot.persistence.sqlite")
        )
        for path in interface_files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_adapters_and_reference_simulation_do_not_import_persistence() -> None:
    files = tuple((PACKAGE_ROOT / "adapters").rglob("*.py")) + tuple(
        (PACKAGE_ROOT / "reference_simulation").rglob("*.py")
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module
            for module in imported_modules(path)
            if module.startswith("sim_pilot.persistence")
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_alembic_does_not_leak_into_domain_or_runtime() -> None:
    files = tuple((PACKAGE_ROOT / "domain").rglob("*.py")) + tuple(
        (PACKAGE_ROOT / "runtime").rglob("*.py")
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith("alembic")
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_sqlite_does_not_import_reference_adapter_internals() -> None:
    files = (PACKAGE_ROOT / "persistence" / "sqlite").rglob("*.py")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module
            for module in imported_modules(path)
            if module.startswith("sim_pilot.adapters.reference")
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_repositories_do_not_import_runtime_policy_or_execution() -> None:
    files = tuple((PACKAGE_ROOT / "persistence").rglob("*.py"))
    forbidden = (
        "sim_pilot.runtime.engine",
        "sim_pilot.runtime.evaluator",
        "sim_pilot.runtime.policy",
        "sim_pilot.runtime.verification",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden)
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_openai_sdk_is_isolated_to_openai_provider() -> None:
    files = (PACKAGE_ROOT).rglob("*.py")
    provider_modules = {
        PACKAGE_ROOT / "intent_compiler" / "providers" / "openai.py",
        PACKAGE_ROOT / "decision_provider" / "providers" / "openai.py",
        PACKAGE_ROOT / "analysis_provider" / "openai.py",
    }
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module
            for module in imported_modules(path)
            if module == "openai" or module.startswith("openai.")
        )
        for path in files
        if path not in provider_modules
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_runtime_does_not_import_intent_compiler_or_provider_sdk() -> None:
    files = (PACKAGE_ROOT / "runtime").rglob("*.py")
    forbidden = ("sim_pilot.intent_compiler", "openai")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden)
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_decision_providers_do_not_import_adapters_or_sqlite() -> None:
    files = (PACKAGE_ROOT / "decision_provider").rglob("*.py")
    forbidden = (
        "sim_pilot.adapters.reference",
        "sim_pilot.persistence.sqlite",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden)
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_openttd_client_is_below_adapter_and_provider_boundaries() -> None:
    files = (PACKAGE_ROOT / "openttd").rglob("*.py")
    forbidden = (
        "sim_pilot.adapters",
        "sim_pilot.runtime",
        "sim_pilot.persistence",
        "sim_pilot.intent_compiler",
        "sim_pilot.decision_provider",
        "openai",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden)
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_runtime_does_not_import_openttd_client() -> None:
    files = (PACKAGE_ROOT / "runtime").rglob("*.py")
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith("sim_pilot.openttd")
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_runtime_orchestration_modules_stay_reviewable() -> None:
    """Keep the facade and extracted execution responsibilities below the review threshold."""
    limits = {
        "engine.py": 500,
        "execution.py": 500,
        "iteration.py": 500,
        "action_execution.py": 500,
        "execution_services.py": 500,
        "engine_support.py": 500,
    }

    sizes = {
        name: len((PACKAGE_ROOT / "runtime" / name).read_text(encoding="utf-8").splitlines())
        for name in limits
    }
    oversized = {name: size for name, size in sizes.items() if size > limits[name]}

    assert not oversized, f"Runtime orchestration modules exceeded 500 lines: {oversized}"


def test_codex_cli_boundary_is_shared_and_never_uses_a_shell() -> None:
    files = tuple((PACKAGE_ROOT / "provider_support" / "codex_cli").rglob("*.py"))
    forbidden = (
        "sim_pilot.adapters",
        "sim_pilot.cli",
        "sim_pilot.decision_provider",
        "sim_pilot.intent_compiler",
        "sim_pilot.persistence",
        "sim_pilot.runtime",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden)
        )
        for path in files
    }

    assert not {path: modules for path, modules in violations.items() if modules}
    assert all("shell=True" not in path.read_text(encoding="utf-8") for path in files)


def test_analysis_core_is_separate_from_action_and_integration_boundaries() -> None:
    files = tuple((PACKAGE_ROOT / "analysis").rglob("*.py"))
    forbidden = (
        "sim_pilot.adapters",
        "sim_pilot.runtime",
        "sim_pilot.persistence",
        "sim_pilot.intent_compiler",
        "sim_pilot.decision_provider",
        "sim_pilot.openttd",
        "openai",
    )
    violations = {
        str(path.relative_to(PACKAGE_ROOT)): sorted(
            module for module in imported_modules(path) if module.startswith(forbidden)
        )
        for path in files
    }
    assert not {path: modules for path, modules in violations.items() if modules}
