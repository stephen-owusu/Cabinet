"""Structural guardrails for the workspace.

If a package stops looking like the others - wrong name, missing marker,
an errant cip/__init__.py breaking the namespace package, a package that
exists but was never wired into the root project - this catches it before
an import error does, somewhere less obvious.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = ROOT / "packages"

EXPECTED_PACKAGES = {
    "core",
    "retrieval",
    "ingestion",
    "tools",
    "agents",
    "evaluation",
    "api",
    "bootstrap",
}


def _package_dirs() -> list[Path]:
    return sorted(p for p in PACKAGES_DIR.iterdir() if p.is_dir())


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_every_expected_package_exists():
    found = {p.name for p in _package_dirs()}
    assert found == EXPECTED_PACKAGES


def test_every_package_has_a_pyproject_named_cip_dash_package():
    for pkg_dir in _package_dirs():
        pyproject = pkg_dir / "pyproject.toml"
        assert pyproject.exists(), f"{pkg_dir} has no pyproject.toml"
        data = _load_toml(pyproject)
        assert data["project"]["name"] == f"cip-{pkg_dir.name}"


def test_every_package_has_an_init_module_with_a_docstring():
    for pkg_dir in _package_dirs():
        init = pkg_dir / "src" / "cip" / pkg_dir.name / "__init__.py"
        assert init.exists(), f"{init} is missing"
        assert init.read_text(encoding="utf-8").strip(), f"{init} has no docstring"


def test_every_package_declares_py_typed():
    for pkg_dir in _package_dirs():
        marker = pkg_dir / "src" / "cip" / pkg_dir.name / "py.typed"
        assert marker.exists(), f"{marker} is missing"


def test_cip_namespace_has_no_init_module():
    """cip is a namespace package (PEP 420). An __init__.py here would
    break that for every other package sharing the namespace."""
    for pkg_dir in _package_dirs():
        assert not (pkg_dir / "src" / "cip" / "__init__.py").exists()


def test_every_package_builds_with_hatchling():
    for pkg_dir in _package_dirs():
        data = _load_toml(pkg_dir / "pyproject.toml")
        assert data["build-system"]["build-backend"] == "hatchling.build"
        assert data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/cip"]


def test_root_pyproject_depends_on_every_package():
    root = _load_toml(ROOT / "pyproject.toml")
    expected = {f"cip-{name}" for name in EXPECTED_PACKAGES}

    assert set(root["project"]["dependencies"]) == expected
    assert set(root["tool"]["uv"]["sources"]) == expected
    for source in root["tool"]["uv"]["sources"].values():
        assert source == {"workspace": True}


def test_mypy_path_covers_every_package():
    root = _load_toml(ROOT / "pyproject.toml")
    expected = {f"packages/{name}/src" for name in EXPECTED_PACKAGES}

    assert set(root["tool"]["mypy"]["mypy_path"]) == expected


def test_every_package_sources_from_itself_not_a_stray_copy():
    for pkg_dir in _package_dirs():
        data = _load_toml(pkg_dir / "pyproject.toml")
        declared = {dep for dep in data["project"]["dependencies"] if dep.startswith("cip-")}
        sourced = set(data.get("tool", {}).get("uv", {}).get("sources", {}))
        assert declared == sourced, (
            f"{pkg_dir} declares workspace deps it doesn't source, or vice versa"
        )
