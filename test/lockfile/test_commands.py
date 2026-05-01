"""Tests for capture, restore and check commands."""

from __future__ import annotations

import json

import lockfile
from conftest import write_lockfile


class TestCapture:
    def test_capture_creates_lockfile(
        self,
        tmp_project,
        make_registry_lib,
        mock_git_commands,
        make_global_packages,
    ):
        make_registry_lib("testenv", "MyLib", "1.0.0", project_dir=tmp_project)
        make_global_packages("framework-test", "2.0.0")

        rc = lockfile.capture(tmp_project, ["testenv"])
        assert rc == 0

        lock_path = tmp_project / "pio.lock.json"
        assert lock_path.exists()
        data = json.loads(lock_path.read_text())

        assert data["pio_core_version"] == "6.1.18"
        assert "testenv" in data["envs"]
        libs = data["envs"]["testenv"]["libraries"]
        assert len(libs) == 1
        assert libs[0]["name"] == "MyLib"
        assert data["global_packages"]["framework-test"] == "2.0.0"

    def test_capture_custom_output(
        self,
        tmp_project,
        make_registry_lib,
        mock_git_commands,
        make_global_packages,
    ):
        make_registry_lib("testenv", "Lib", project_dir=tmp_project)
        make_global_packages("toolchain-test", "1.0.0")

        output = tmp_project / "custom" / "lock.json"
        rc = lockfile.capture(tmp_project, ["testenv"], output_path=output)
        assert rc == 0
        assert output.exists()
        assert not (tmp_project / "pio.lock.json").exists()

    def test_capture_multiple_envs(
        self,
        tmp_project,
        make_registry_lib,
        mock_git_commands,
        make_global_packages,
    ):
        make_registry_lib("env1", "LibA", project_dir=tmp_project)
        make_registry_lib("env2", "LibB", project_dir=tmp_project)
        make_global_packages("toolchain-test", "1.0.0")

        rc = lockfile.capture(tmp_project, ["env1", "env2"])
        assert rc == 0

        data = json.loads((tmp_project / "pio.lock.json").read_text())
        assert "env1" in data["envs"]
        assert "env2" in data["envs"]

    def test_capture_fails_without_platformio_ini(self, tmp_path, mock_git_commands):
        rc = lockfile.capture(tmp_path, ["testenv"])
        assert rc == 1

    def test_capture_records_git_libs(
        self,
        tmp_project,
        make_git_lib,
        mock_git_commands,
        make_global_packages,
    ):
        make_git_lib(
            "testenv",
            "git-dep",
            sha="abc123",
            url="https://github.com/test/dep.git",
            project_dir=tmp_project,
        )
        make_global_packages("toolchain-x", "1.0")
        rc = lockfile.capture(tmp_project, ["testenv"])
        assert rc == 0

        data = json.loads((tmp_project / "pio.lock.json").read_text())
        git_lib = data["envs"]["testenv"]["libraries"][0]
        assert git_lib["type"] == "git"
        assert git_lib["sha"] == "abc123"
        assert git_lib["url"] == "https://github.com/test/dep.git"


class TestCheck:
    def test_check_passes_when_matching(
        self,
        tmp_project,
        make_registry_lib,
        mock_git_commands,
    ):
        make_registry_lib("testenv", "MyLib", "1.0.0", project_dir=tmp_project)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {
                        "name": "MyLib",
                        "type": "registry",
                        "version": "1.0.0",
                        "owner": "testowner",
                    },
                ],
            },
        )
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 0

    def test_check_detects_version_drift(
        self,
        tmp_project,
        make_registry_lib,
        mock_git_commands,
        capsys,
    ):
        make_registry_lib("testenv", "MyLib", "1.0.0", project_dir=tmp_project)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {
                        "name": "MyLib",
                        "type": "registry",
                        "version": "2.0.0",
                        "owner": "testowner",
                    },
                ],
            },
        )
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 1
        assert "DRIFT" in capsys.readouterr().out

    def test_check_detects_git_sha_drift(
        self,
        tmp_project,
        make_git_lib,
        mock_git_commands,
        capsys,
    ):
        make_git_lib("testenv", "dep", sha="aaa", url="https://x.git", project_dir=tmp_project)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {"name": "dep", "type": "git", "url": "https://x.git", "sha": "bbb"},
                ],
            },
        )
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 1

    def test_check_skips_local_libs(
        self,
        tmp_project,
        make_local_lib,
        mock_git_commands,
    ):
        make_local_lib("testenv", "Local", project_dir=tmp_project)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {"name": "Local", "type": "local", "path": "file://lib/local"},
                ],
            },
        )
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 0

    def test_check_fails_on_missing_lockfile(self, tmp_project, mock_git_commands):
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 1

    def test_check_fails_on_missing_env(
        self,
        tmp_project,
        mock_git_commands,
    ):
        write_lockfile(tmp_project, {"other": []})
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 1

    def test_check_detects_missing_library(
        self,
        tmp_project,
        mock_git_commands,
    ):
        libdeps = tmp_project / ".pio" / "libdeps" / "testenv"
        libdeps.mkdir(parents=True)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {"name": "Ghost", "type": "registry", "version": "1.0.0", "owner": "nobody"},
                ],
            },
        )
        rc = lockfile.check(tmp_project, ["testenv"])
        assert rc == 1


class TestRestore:
    def test_restore_skips_already_installed(
        self,
        tmp_project,
        make_registry_lib,
        mock_git_commands,
    ):
        make_registry_lib("testenv", "MyLib", "1.0.0", project_dir=tmp_project)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {
                        "name": "MyLib",
                        "type": "registry",
                        "version": "1.0.0",
                        "owner": "testowner",
                    },
                ],
            },
        )
        rc = lockfile.restore(tmp_project, ["testenv"])
        assert rc == 0
        install_calls = [c for c in mock_git_commands if c[:3] == ["pio", "pkg", "install"]]
        assert len(install_calls) == 0

    def test_restore_installs_missing_registry_lib(
        self,
        tmp_project,
        mock_git_commands,
    ):
        libdeps = tmp_project / ".pio" / "libdeps" / "testenv"
        libdeps.mkdir(parents=True)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {"name": "NewLib", "type": "registry", "version": "3.0.0", "owner": "acme"},
                ],
            },
        )
        rc = lockfile.restore(tmp_project, ["testenv"])
        assert rc == 0
        install_calls = [c for c in mock_git_commands if c[:3] == ["pio", "pkg", "install"]]
        assert len(install_calls) == 1
        assert "acme/NewLib @ ==3.0.0" in install_calls[0]

    def test_restore_installs_git_lib_by_sha(
        self,
        tmp_project,
        mock_git_commands,
    ):
        libdeps = tmp_project / ".pio" / "libdeps" / "testenv"
        libdeps.mkdir(parents=True)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {
                        "name": "GitDep",
                        "type": "git",
                        "url": "https://github.com/test/dep.git",
                        "sha": "deadbeef",
                    },
                ],
            },
        )
        rc = lockfile.restore(tmp_project, ["testenv"])
        assert rc == 0
        install_calls = [c for c in mock_git_commands if c[:3] == ["pio", "pkg", "install"]]
        assert len(install_calls) == 1
        assert "https://github.com/test/dep.git#deadbeef" in install_calls[0]

    def test_restore_skips_local_libs(
        self,
        tmp_project,
        make_local_lib,
        mock_git_commands,
    ):
        make_local_lib("testenv", "Local", project_dir=tmp_project)
        write_lockfile(
            tmp_project,
            {
                "testenv": [
                    {"name": "Local", "type": "local", "path": "file://lib/local"},
                ],
            },
        )
        rc = lockfile.restore(tmp_project, ["testenv"])
        assert rc == 0
        install_calls = [c for c in mock_git_commands if c[:3] == ["pio", "pkg", "install"]]
        assert len(install_calls) == 0

    def test_restore_fails_on_missing_lockfile(self, tmp_project, mock_git_commands):
        rc = lockfile.restore(tmp_project, ["testenv"])
        assert rc == 1

    def test_restore_fails_on_missing_env(self, tmp_project, mock_git_commands):
        write_lockfile(tmp_project, {"other": []})
        rc = lockfile.restore(tmp_project, ["testenv"])
        assert rc == 1


class TestLibInstallSpec:
    def test_registry_with_owner(self):
        spec = lockfile._lib_install_spec(
            {"type": "registry", "name": "Foo", "version": "1.2.3", "owner": "bar"}
        )
        assert spec == "bar/Foo @ ==1.2.3"

    def test_registry_without_owner(self):
        spec = lockfile._lib_install_spec(
            {"type": "registry", "name": "Foo", "version": "1.2.3"}
        )
        assert spec == "Foo @ ==1.2.3"

    def test_git(self):
        spec = lockfile._lib_install_spec(
            {"type": "git", "url": "https://github.com/x/y.git", "sha": "abc123"}
        )
        assert spec == "https://github.com/x/y.git#abc123"

    def test_local_returns_none(self):
        assert lockfile._lib_install_spec({"type": "local"}) is None

    def test_unknown_returns_none(self):
        assert lockfile._lib_install_spec({"type": "magic"}) is None
