"""Shared fixtures for lockfile tests.

Adapted from m-mcgowan/pio-lock to operate against ``builder/lockfile.py``
inside this repository. The repo root contains ``platform.py`` which would
shadow Python's stdlib ``platform`` module if it were on ``sys.path``, so we
sanitize ``sys.path`` before importing PlatformIO.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


# ── Module bootstrap ─────────────────────────────────────────────────────────

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_LOCKFILE_PATH = _WORKSPACE_ROOT / "builder" / "lockfile.py"


def _scrub_sys_path() -> None:
    """Remove the workspace root from sys.path so the local ``platform.py``
    cannot shadow Python's stdlib platform module."""
    target = _WORKSPACE_ROOT.resolve()
    sys.path[:] = [p for p in sys.path if p and Path(p).resolve() != target]


_scrub_sys_path()


def _load_lockfile():
    spec = importlib.util.spec_from_file_location("lockfile", str(_LOCKFILE_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load lockfile from {_LOCKFILE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lockfile"] = mod
    spec.loader.exec_module(mod)
    return mod


lockfile = _load_lockfile()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal PlatformIO project structure."""
    (tmp_path / "platformio.ini").write_text(
        "[env:testenv]\nplatform = espressif32\nboard = esp32dev\n"
    )
    return tmp_path


@pytest.fixture
def make_registry_lib(tmp_path: Path):
    """Factory to create a fake registry library in .pio/libdeps/<env>/."""

    def _make(
        env: str,
        name: str,
        version: str = "1.0.0",
        owner: str = "testowner",
        *,
        project_dir: Path | None = None,
    ) -> Path:
        base = project_dir or tmp_path
        lib_dir = base / ".pio" / "libdeps" / env / name
        lib_dir.mkdir(parents=True, exist_ok=True)
        piopm: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": version,
            "spec": {
                "owner": owner,
                "id": 1234,
                "name": name,
                "requirements": None,
                "uri": None,
            },
        }
        (lib_dir / ".piopm").write_text(json.dumps(piopm))
        return lib_dir

    return _make


@pytest.fixture
def make_git_lib(tmp_path: Path):
    """Factory to create a fake git-sourced library in .pio/libdeps/<env>/."""

    def _make(
        env: str,
        name: str,
        sha: str = "abc123def456",
        url: str = "https://github.com/test/lib.git",
        *,
        project_dir: Path | None = None,
        library_json_name: str | None = None,
    ) -> Path:
        base = project_dir or tmp_path
        lib_dir = base / ".pio" / "libdeps" / env / name
        lib_dir.mkdir(parents=True, exist_ok=True)
        # Fake .git marker (file, not real repo)
        (lib_dir / ".git").write_text("fake git marker")
        if library_json_name:
            (lib_dir / "library.json").write_text(
                json.dumps({"name": library_json_name, "version": "0.0.0"})
            )
        # Sentinel files used by mock_git_commands
        (lib_dir / ".pio-lock-test-sha").write_text(sha)
        (lib_dir / ".pio-lock-test-url").write_text(url)
        return lib_dir

    return _make


@pytest.fixture
def make_local_lib(tmp_path: Path):
    """Factory to create a fake local (file://) library."""

    def _make(
        env: str,
        name: str,
        uri: str = "file://lib/mylib",
        *,
        project_dir: Path | None = None,
    ) -> Path:
        base = project_dir or tmp_path
        lib_dir = base / ".pio" / "libdeps" / env / name
        lib_dir.mkdir(parents=True, exist_ok=True)
        piopm: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": "1.0.0",
            "spec": {
                "owner": None,
                "id": None,
                "name": name,
                "requirements": None,
                "uri": uri,
            },
        }
        (lib_dir / ".piopm").write_text(json.dumps(piopm))
        return lib_dir

    return _make


@pytest.fixture
def mock_git_commands(monkeypatch: pytest.MonkeyPatch):
    """Replace ``lockfile._run_cmd`` to handle git/pio commands deterministically."""
    real_run = lockfile._default_run_cmd
    call_log: list[list[str]] = []

    def fake_run(args, cwd=None, check=True):
        call_log.append(args)

        if args[:2] == ["git", "rev-parse"] and args[2:3] == ["HEAD"]:
            sha_file = Path(cwd) / ".pio-lock-test-sha" if cwd else None
            if sha_file and sha_file.exists():
                return sha_file.read_text().strip()
            return "0000000000000000000000000000000000000000"

        if args[:2] == ["git", "rev-parse"] and "--short" in args:
            return "abc1234"

        if args[:3] == ["git", "remote", "get-url"]:
            url_file = Path(cwd) / ".pio-lock-test-url" if cwd else None
            if url_file and url_file.exists():
                return url_file.read_text().strip()
            return "https://github.com/unknown/unknown.git"

        if args[:2] == ["git", "status"]:
            return ""

        if args[:2] == ["pio", "system"]:
            return "PlatformIO Core    6.1.18"

        if args[:3] == ["pio", "project", "config"]:
            return json.dumps([["env:testenv", [["platform", "espressif32"]]]])

        if args[:3] == ["pio", "pkg", "install"]:
            return ""

        return real_run(args, cwd=cwd, check=check)

    monkeypatch.setattr(lockfile, "_run_cmd", fake_run)
    return call_log


@pytest.fixture
def make_global_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create fake global packages and point PLATFORMIO_CORE_DIR at them."""
    packages_dir = tmp_path / "pio_home" / "packages"
    packages_dir.mkdir(parents=True)
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "pio_home"))

    def _make(name: str, version: str) -> Path:
        pkg_dir = packages_dir / name
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "package.json").write_text(json.dumps({"name": name, "version": version}))
        return pkg_dir

    return _make


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch):
    """Make sure SOURCE_DATE_EPOCH and release-mode flags don't leak between tests."""
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    monkeypatch.delenv("PIO_RELEASE_BUILD", raising=False)
    yield
    os.environ.pop("SOURCE_DATE_EPOCH", None)


def write_lockfile(
    project_dir: Path,
    envs: dict[str, list[dict[str, Any]]],
) -> Path:
    """Write a pio.lock.json for testing."""
    lockdata = {
        "_comment": "test lockfile",
        "generated_at": "2026-01-01T00:00:00Z",
        "generated_from_commit": "test123",
        "pio_core_version": "6.1.18",
        "platform_url": "espressif32",
        "global_packages": {},
        "envs": {name: {"libraries": libs} for name, libs in envs.items()},
    }
    path = project_dir / "pio.lock.json"
    path.write_text(json.dumps(lockdata, indent=2))
    return path
