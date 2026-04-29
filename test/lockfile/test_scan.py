"""Tests for library scanning (capture's core logic)."""

from __future__ import annotations

import json

import lockfile


class TestScanEnvLibraries:
    def test_registry_library(self, tmp_project, make_registry_lib, mock_git_commands):
        make_registry_lib("testenv", "MyLib", "2.3.4", "acme", project_dir=tmp_project)
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert len(libs) == 1
        assert libs[0] == {
            "name": "MyLib",
            "type": "registry",
            "version": "2.3.4",
            "owner": "acme",
        }

    def test_registry_library_without_owner(
        self, tmp_project, make_registry_lib, mock_git_commands
    ):
        lib_dir = make_registry_lib("testenv", "NoOwner", project_dir=tmp_project)
        piopm = json.loads((lib_dir / ".piopm").read_text())
        piopm["spec"]["owner"] = None
        (lib_dir / ".piopm").write_text(json.dumps(piopm))

        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert len(libs) == 1
        assert "owner" not in libs[0]

    def test_git_library(self, tmp_project, make_git_lib, mock_git_commands):
        make_git_lib(
            "testenv",
            "git-lib",
            sha="deadbeef" * 5,
            url="https://github.com/test/git-lib.git",
            project_dir=tmp_project,
        )
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert len(libs) == 1
        assert libs[0] == {
            "name": "git-lib",
            "type": "git",
            "url": "https://github.com/test/git-lib.git",
            "sha": "deadbeef" * 5,
        }

    def test_git_library_with_library_json(
        self, tmp_project, make_git_lib, mock_git_commands
    ):
        make_git_lib(
            "testenv",
            "ugly-dirname",
            sha="aaa111",
            url="https://github.com/test/pretty.git",
            project_dir=tmp_project,
            library_json_name="Pretty Name",
        )
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert libs[0]["name"] == "Pretty Name"

    def test_local_library(self, tmp_project, make_local_lib, mock_git_commands):
        make_local_lib("testenv", "LocalLib", "file://lib/local", project_dir=tmp_project)
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert len(libs) == 1
        assert libs[0] == {
            "name": "LocalLib",
            "type": "local",
            "path": "file://lib/local",
        }

    def test_skips_shadow_copies(self, tmp_project, make_registry_lib, mock_git_commands):
        make_registry_lib("testenv", "NimBLE@src-abc123", project_dir=tmp_project)
        make_registry_lib("testenv", "RealLib", project_dir=tmp_project)
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert len(libs) == 1
        assert libs[0]["name"] == "RealLib"

    def test_skips_non_directories(self, tmp_project, mock_git_commands):
        libdeps = tmp_project / ".pio" / "libdeps" / "testenv"
        libdeps.mkdir(parents=True)
        (libdeps / "integrity.dat").write_text("some data")
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert libs == []

    def test_warns_on_unknown_library(self, tmp_project, mock_git_commands, capsys):
        libdeps = tmp_project / ".pio" / "libdeps" / "testenv"
        unknown = libdeps / "mystery"
        unknown.mkdir(parents=True)
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert libs == []
        assert "mystery" in capsys.readouterr().err

    def test_warns_on_corrupt_piopm(self, tmp_project, mock_git_commands, capsys):
        libdeps = tmp_project / ".pio" / "libdeps" / "testenv"
        lib_dir = libdeps / "BadLib"
        lib_dir.mkdir(parents=True)
        (lib_dir / ".piopm").write_text("not json{{{")
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        assert libs == []
        assert "corrupt" in capsys.readouterr().err

    def test_missing_libdeps_dir(self, tmp_project, mock_git_commands, capsys):
        libs = lockfile.scan_env_libraries(tmp_project, "noenv")
        assert libs == []
        assert "does not exist" in capsys.readouterr().err

    def test_mixed_libraries_sorted(
        self,
        tmp_project,
        make_registry_lib,
        make_git_lib,
        make_local_lib,
        mock_git_commands,
    ):
        make_local_lib("testenv", "AAA-Local", project_dir=tmp_project)
        make_git_lib("testenv", "BBB-Git", sha="111", project_dir=tmp_project)
        make_registry_lib("testenv", "CCC-Registry", project_dir=tmp_project)
        libs = lockfile.scan_env_libraries(tmp_project, "testenv")
        names = [lib["name"] for lib in libs]
        assert names == ["AAA-Local", "BBB-Git", "CCC-Registry"]


class TestScanGlobalPackages:
    def test_captures_matching_prefixes(self, make_global_packages):
        make_global_packages("framework-arduino", "3.0.0")
        make_global_packages("toolchain-xtensa", "14.2.0")
        make_global_packages("tool-cmake", "4.0.3")
        make_global_packages("contrib-piohome", "1.0.0")  # should be skipped

        pkgs = lockfile.scan_global_packages()
        assert "framework-arduino" in pkgs
        assert "toolchain-xtensa" in pkgs
        assert "tool-cmake" in pkgs
        assert "contrib-piohome" not in pkgs

    def test_empty_packages_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "empty"))
        pkgs = lockfile.scan_global_packages()
        assert pkgs == {}
