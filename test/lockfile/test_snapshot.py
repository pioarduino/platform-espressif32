"""Tests for build snapshot functionality."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import lockfile


class FakePioEnv:
    """Minimal mock of a PlatformIO SCons environment."""

    def __init__(self):
        self.exit_code = None

    def Exit(self, code):  # noqa: N802
        self.exit_code = code

    def GetProjectOption(self, key, default=""):  # noqa: N802
        return default


@pytest.fixture
def snapshot_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal project directory with git mocked."""
    (tmp_path / "platformio.ini").write_text(
        "[env:testenv]\nplatform = espressif32\nboard = esp32dev\n"
    )

    def fake_run(args, cwd=None, check=True):
        if args[:2] == ["git", "rev-parse"] and "--short" in args:
            return "abc12345"
        if args[:2] == ["git", "status"]:
            return ""  # clean
        return ""

    monkeypatch.setattr(lockfile, "_run_cmd", fake_run)
    return tmp_path


class TestGenerateSnapshot:
    def test_creates_file(self, snapshot_project: Path):
        lockfile.generate_snapshot(snapshot_project)
        path = snapshot_project / lockfile.SNAPSHOT_NAME
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["git_commit"] == "abc12345"
        assert data["git_dirty"] is False
        assert data["pinned"] is False
        assert "source_date_epoch" in data
        assert "build_date" in data

    def test_pinned_flag(self, snapshot_project: Path):
        snapshot = lockfile.generate_snapshot(snapshot_project, pinned=True)
        assert snapshot["pinned"] is True
        data = json.loads((snapshot_project / lockfile.SNAPSHOT_NAME).read_text())
        assert data["pinned"] is True

    def test_dirty_detection(self, snapshot_project: Path, monkeypatch):
        def fake_run(args, cwd=None, check=True):
            if args[:2] == ["git", "rev-parse"] and "--short" in args:
                return "abc12345"
            if args[:2] == ["git", "status"]:
                return " M some_file.c"  # dirty
            return ""

        monkeypatch.setattr(lockfile, "_run_cmd", fake_run)
        snapshot = lockfile.generate_snapshot(snapshot_project)
        assert snapshot["git_dirty"] is True


class TestLoadSnapshot:
    def test_returns_none_when_missing(self, snapshot_project: Path):
        assert lockfile.load_snapshot(snapshot_project) is None

    def test_loads_valid_snapshot(self, snapshot_project: Path):
        data = {"source_date_epoch": 1700000000, "git_commit": "abc12345"}
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text(json.dumps(data))
        result = lockfile.load_snapshot(snapshot_project)
        assert result == data

    def test_returns_none_on_invalid_json(self, snapshot_project: Path):
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text("not json{{{")
        assert lockfile.load_snapshot(snapshot_project) is None


class TestIsSnapshotStale:
    def test_fresh_when_commit_matches(self, snapshot_project: Path):
        snapshot = {"git_commit": "abc12345"}
        assert lockfile.is_snapshot_stale(snapshot, snapshot_project) is False

    def test_stale_when_commit_differs(self, snapshot_project: Path):
        snapshot = {"git_commit": "old_commit"}
        assert lockfile.is_snapshot_stale(snapshot, snapshot_project) is True

    def test_not_stale_when_git_unavailable(self, snapshot_project: Path, monkeypatch):
        def fake_run(args, cwd=None, check=True):
            if "rev-parse" in args:
                raise subprocess.CalledProcessError(1, "git")
            return ""

        monkeypatch.setattr(lockfile, "_run_cmd", fake_run)
        # get_git_commit returns "unknown" on failure — can't determine staleness
        snapshot = {"git_commit": "abc12345"}
        assert lockfile.is_snapshot_stale(snapshot, snapshot_project) is False


class TestApplySnapshot:
    def test_sets_source_date_epoch(self, snapshot_project: Path):
        snapshot = {
            "source_date_epoch": 1700000000,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "abc12345",
        }
        lockfile.apply_snapshot(snapshot)
        assert os.environ["SOURCE_DATE_EPOCH"] == "1700000000"

    def test_pinned_tag_in_output(self, snapshot_project: Path, capsys):
        snapshot = {
            "source_date_epoch": 1700000000,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "abc12345",
            "pinned": True,
        }
        lockfile.apply_snapshot(snapshot)
        captured = capsys.readouterr()
        assert "[pinned]" in captured.out


class TestSnapshotAutoManage:
    def test_generates_when_missing(self, snapshot_project: Path):
        lockfile.snapshot_auto_manage(snapshot_project)
        assert (snapshot_project / lockfile.SNAPSHOT_NAME).exists()
        assert "SOURCE_DATE_EPOCH" in os.environ

    def test_reuses_when_commit_matches(self, snapshot_project: Path):
        original_epoch = 1700000000
        data = {
            "source_date_epoch": original_epoch,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "abc12345",
        }
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text(json.dumps(data))
        lockfile.snapshot_auto_manage(snapshot_project)
        assert os.environ["SOURCE_DATE_EPOCH"] == str(original_epoch)

    def test_regenerates_when_stale(self, snapshot_project: Path):
        data = {
            "source_date_epoch": 1700000000,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "old_commit",
        }
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text(json.dumps(data))
        lockfile.snapshot_auto_manage(snapshot_project)
        new_data = json.loads((snapshot_project / lockfile.SNAPSHOT_NAME).read_text())
        assert new_data["git_commit"] == "abc12345"
        assert new_data["source_date_epoch"] != 1700000000

    def test_pinned_never_regenerates(self, snapshot_project: Path):
        original_epoch = 1700000000
        data = {
            "source_date_epoch": original_epoch,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "old_commit",
            "pinned": True,
        }
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text(json.dumps(data))
        lockfile.snapshot_auto_manage(snapshot_project)
        assert os.environ["SOURCE_DATE_EPOCH"] == str(original_epoch)


class TestReleaseMode:
    def test_pinned_is_release(self, snapshot_project: Path):
        snapshot = {"pinned": True}
        assert lockfile._is_release_mode(snapshot) is True

    def test_env_var_is_release(self, snapshot_project: Path, monkeypatch):
        monkeypatch.setenv("PIO_RELEASE_BUILD", "1")
        assert lockfile._is_release_mode(None) is True

    def test_not_release_by_default(self, snapshot_project: Path):
        assert lockfile._is_release_mode(None) is False
        assert lockfile._is_release_mode({"pinned": False}) is False

    def test_release_mode_fails_when_no_snapshot(
        self, snapshot_project: Path, monkeypatch
    ):
        monkeypatch.setenv("PIO_RELEASE_BUILD", "1")
        fake_env = FakePioEnv()
        lockfile.snapshot_auto_manage(snapshot_project, fake_env)
        assert fake_env.exit_code == 1

    def test_release_mode_fails_when_stale(self, snapshot_project: Path, monkeypatch):
        monkeypatch.setenv("PIO_RELEASE_BUILD", "1")
        data = {
            "source_date_epoch": 1700000000,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "old_commit",
        }
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text(json.dumps(data))
        fake_env = FakePioEnv()
        lockfile.snapshot_auto_manage(snapshot_project, fake_env)
        assert fake_env.exit_code == 1


class TestSnapshotCommands:
    def test_capture(self, snapshot_project: Path):
        rc = lockfile.snapshot_capture(snapshot_project)
        assert rc == 0
        assert (snapshot_project / lockfile.SNAPSHOT_NAME).exists()

    def test_check_fresh(self, snapshot_project: Path):
        lockfile.generate_snapshot(snapshot_project)
        rc = lockfile.snapshot_check(snapshot_project)
        assert rc == 0

    def test_check_stale(self, snapshot_project: Path):
        data = {
            "source_date_epoch": 1700000000,
            "build_date": "2023-11-14T22:13:20+00:00",
            "git_commit": "old_commit",
        }
        (snapshot_project / lockfile.SNAPSHOT_NAME).write_text(json.dumps(data))
        rc = lockfile.snapshot_check(snapshot_project)
        assert rc == 1

    def test_check_missing(self, snapshot_project: Path):
        rc = lockfile.snapshot_check(snapshot_project)
        assert rc == 1

    def test_clear_existing(self, snapshot_project: Path):
        lockfile.generate_snapshot(snapshot_project)
        assert (snapshot_project / lockfile.SNAPSHOT_NAME).exists()
        rc = lockfile.snapshot_clear(snapshot_project)
        assert rc == 0
        assert not (snapshot_project / lockfile.SNAPSHOT_NAME).exists()

    def test_clear_missing(self, snapshot_project: Path):
        rc = lockfile.snapshot_clear(snapshot_project)
        assert rc == 0

    def test_print_existing(self, snapshot_project: Path, capsys):
        lockfile.generate_snapshot(snapshot_project)
        rc = lockfile.snapshot_print(snapshot_project)
        assert rc == 0
        captured = capsys.readouterr()
        assert "source_date_epoch" in captured.out
