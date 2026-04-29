"""Tests for the outdated and update commands.

These mock PlatformIO's internal APIs so they run without PIO installed.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

import lockfile

# ── Mock PIO objects ─────────────────────────────────────────────────────────


class FakeVersion:
    """Minimal stand-in for semantic_version.Version."""

    def __init__(self, ver: str):
        self._ver = ver

    def __str__(self):
        return self._ver

    def __eq__(self, other):
        if isinstance(other, FakeVersion):
            return self._ver == other._ver
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, FakeVersion):
            return self._ver != other._ver
        return NotImplemented


class FakeOutdatedResult:
    """Stand-in for PackageOutdatedResult."""

    def __init__(
        self,
        current: str,
        latest: str | None = None,
        wanted: str | None = None,
        detached: bool = False,
    ):
        self.current = FakeVersion(current)
        self.latest = FakeVersion(latest) if latest else None
        self.wanted = FakeVersion(wanted) if wanted else None
        self.detached = detached

    def is_outdated(self, allow_incompatible: bool = False) -> bool:
        if self.detached or not self.latest or self.current == self.latest:
            return False
        if allow_incompatible:
            return self.current != self.latest
        if self.wanted:
            return self.current != self.wanted
        return True


class FakePackageMetadata:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = FakeVersion(version)
        self.spec = MagicMock()
        self.spec.external = False
        self.spec.uri = None


class FakePackageItem:
    def __init__(self, name: str, version: str, external: bool = False):
        self.metadata = FakePackageMetadata(name, version)
        if external:
            self.metadata.spec.external = True
            self.metadata.spec.uri = "git+https://example.com"
        self.path = f"/fake/libdeps/env/{name}"


class FakePackageSpec:
    """Stand-in for PackageSpec."""

    def __init__(self, raw: str):
        self.raw = raw
        name = raw.split("/")[-1].split("@")[0].split("#")[0].strip()
        if name.endswith(".git"):
            name = name[:-4]
        self.name = name
        self.external = raw.startswith("http") or raw.startswith("git+")
        self.symlink = False
        self.uri = raw if self.external else None
        if not self.external and self.uri is None and raw.startswith("file://"):
            self.uri = raw
            self.symlink = True


class FakeConfig:
    """Stand-in for ProjectConfig."""

    def __init__(self, lib_deps: dict[str, list[str]], parsed: list[str] | None = None):
        self._lib_deps = lib_deps
        self._parsed = parsed or []

    @classmethod
    def get_instance(cls, _path=None):
        raise NotImplementedError

    def get(self, section: str, option: str, default: Any = None):
        if option == "lib_deps":
            env = section.replace("env:", "")
            return self._lib_deps.get(env, default or [])
        if option == "libdeps_dir":
            return None
        return default


@pytest.fixture
def mock_pio(monkeypatch, tmp_path):
    """Set up mock PIO APIs and return a builder for configuring them."""
    packages: dict[str, FakePackageItem] = {}
    outdated_results: dict[str, FakeOutdatedResult] = {}
    lib_deps: dict[str, list[str]] = {}

    fake_pm = MagicMock()
    fake_pm.get_package = lambda spec: packages.get(spec.name)
    fake_pm.outdated = lambda pkg, spec: outdated_results.get(
        pkg.metadata.name,
        FakeOutdatedResult(str(pkg.metadata.version)),
    )

    def fake_import():
        ini_path = tmp_path / "platformio.ini"
        parsed = [str(ini_path)] if ini_path.exists() else []
        config = FakeConfig(lib_deps, parsed=parsed)

        def fake_config_get_instance(_path=None):
            return config

        pm_cls = MagicMock(return_value=fake_pm)
        return (
            pm_cls,
            FakePackageSpec,
            type(
                "FakeProjectConfig",
                (),
                {"get_instance": staticmethod(fake_config_get_instance)},
            ),
        )

    monkeypatch.setattr(lockfile, "_pio_import_fn", fake_import)
    # Disable GitHub client in unit tests — no real API calls
    monkeypatch.setattr(lockfile, "_create_github_client", lambda: None)

    class Builder:
        def add_lib(
            self,
            env: str,
            spec_str: str,
            name: str,
            version: str,
            latest: str | None = None,
            wanted: str | None = None,
            external: bool = False,
            detached: bool = False,
        ):
            if env not in lib_deps:
                lib_deps[env] = []
            lib_deps[env].append(spec_str)
            packages[name] = FakePackageItem(name, version, external=external)
            if latest or wanted or detached:
                outdated_results[name] = FakeOutdatedResult(
                    version, latest=latest, wanted=wanted, detached=detached
                )

    return Builder()


# ── Tests for outdated ───────────────────────────────────────────────────────


class TestOutdated:
    def test_all_up_to_date(self, tmp_path, mock_pio):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib("test", "acme/Foo @ ^1.0", "Foo", "1.0.0")
        rc = lockfile.outdated(tmp_path, ["test"])
        assert rc == 0

    def test_registry_outdated(self, tmp_path, mock_pio, capsys):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0",
            "Foo",
            "1.0.0",
            latest="1.2.0",
            wanted="1.2.0",
        )
        rc = lockfile.outdated(tmp_path, ["test"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "1.0.0" in out
        assert "1.2.0" in out
        assert "*" in out

    def test_git_outdated(self, tmp_path, mock_pio, capsys):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib(
            "test",
            "https://github.com/x/y.git#main",
            "y",
            "1.0.0+sha.aaa",
            latest="1.0.0+sha.bbb",
            external=True,
        )
        rc = lockfile.outdated(tmp_path, ["test"])
        assert rc == 1

    def test_detached_skipped(self, tmp_path, mock_pio, capsys):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib(
            "test",
            "acme/Bar @ 2.0",
            "Bar",
            "2.0.0",
            detached=True,
        )
        rc = lockfile.outdated(tmp_path, ["test"])
        assert rc == 0
        assert "pinned" in capsys.readouterr().out

    def test_local_skipped(self, tmp_path, mock_pio, capsys):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib("test", "file://lib/local", "local", "0.0.0")
        rc = lockfile.outdated(tmp_path, ["test"])
        assert rc == 0

    def test_json_output(self, tmp_path, mock_pio, capsys):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0",
            "Foo",
            "1.0.0",
            latest="2.0.0",
            wanted="1.5.0",
        )
        rc = lockfile.outdated(tmp_path, ["test"], output_json=True)
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert "libraries" in data
        libs = data["libraries"]
        assert len(libs) == 1
        assert libs[0]["name"] == "Foo"
        assert libs[0]["current"] == "1.0.0"
        assert libs[0]["latest"] == "2.0.0"
        assert libs[0]["wanted"] == "1.5.0"
        assert libs[0]["is_outdated"] is True
        assert "git_deps" in data
        assert "platform" in data

    def test_missing_ini(self, tmp_path):
        rc = lockfile.outdated(tmp_path, ["test"])
        assert rc == 1

    def test_multiple_envs(self, tmp_path, mock_pio, capsys):
        (tmp_path / "platformio.ini").write_text("[env:a]\n[env:b]\n")
        mock_pio.add_lib("a", "acme/LibA @ 1.0", "LibA", "1.0.0")
        mock_pio.add_lib(
            "b",
            "acme/LibB @ 1.0",
            "LibB",
            "1.0.0",
            latest="2.0.0",
            wanted="2.0.0",
        )
        rc = lockfile.outdated(tmp_path, ["a", "b"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "LibA" in out
        assert "LibB" in out


# ── Tests for update ─────────────────────────────────────────────────────────


class TestUpdate:
    def test_no_updates_available(self, tmp_path, mock_pio):
        (tmp_path / "platformio.ini").write_text("[env:test]\n")
        mock_pio.add_lib("test", "acme/Foo @ ^1.0", "Foo", "1.0.0")
        rc = lockfile.update(tmp_path, ["test"])
        assert rc == 0

    def test_dry_run_shows_changes(self, tmp_path, mock_pio, capsys):
        ini_content = "[env:test]\nlib_deps =\n    acme/Foo @ ^1.0.0\n"
        (tmp_path / "platformio.ini").write_text(ini_content)
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0.0",
            "Foo",
            "1.0.0",
            latest="1.2.0",
            wanted="1.2.0",
        )
        rc = lockfile.update(tmp_path, ["test"], dry_run=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "1.0.0" in out
        assert "1.2.0" in out
        assert "Dry run" in out
        assert (tmp_path / "platformio.ini").read_text() == ini_content

    def test_apply_creates_backup(self, tmp_path, mock_pio):
        ini_content = "[env:test]\nlib_deps =\n    acme/Foo @ ^1.0.0\n"
        (tmp_path / "platformio.ini").write_text(ini_content)
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0.0",
            "Foo",
            "1.0.0",
            latest="1.2.0",
            wanted="1.2.0",
        )
        rc = lockfile.update(tmp_path, ["test"], dry_run=False)
        assert rc == 0
        assert (tmp_path / "platformio.ini.bak").exists()
        assert (tmp_path / "platformio.ini.bak").read_text() == ini_content

    def test_apply_updates_ini(self, tmp_path, mock_pio):
        ini_content = "[env:test]\nlib_deps =\n    acme/Foo @ ^1.0.0\n"
        (tmp_path / "platformio.ini").write_text(ini_content)
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0.0",
            "Foo",
            "1.0.0",
            latest="1.2.0",
            wanted="1.2.0",
        )
        rc = lockfile.update(tmp_path, ["test"], dry_run=False)
        assert rc == 0
        new_ini = (tmp_path / "platformio.ini").read_text()
        assert "acme/Foo @ ^1.2.0" in new_ini
        assert "acme/Foo @ ^1.0.0" not in new_ini

    def test_lib_filter(self, tmp_path, mock_pio, capsys):
        ini = "[env:test]\nlib_deps =\n    acme/Foo @ ^1.0\n    acme/Bar @ ^1.0\n"
        (tmp_path / "platformio.ini").write_text(ini)
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0",
            "Foo",
            "1.0.0",
            latest="2.0.0",
            wanted="2.0.0",
        )
        mock_pio.add_lib(
            "test",
            "acme/Bar @ ^1.0",
            "Bar",
            "1.0.0",
            latest="3.0.0",
            wanted="3.0.0",
        )
        lockfile.update(tmp_path, ["test"], lib_filter="Foo")
        out = capsys.readouterr().out
        assert "Foo" in out
        assert "Bar" not in out

    def test_update_only_rewrites_lib_deps_block(self, tmp_path, mock_pio):
        """An identical string outside lib_deps must NOT be rewritten."""
        ini = (
            "[env:test]\n"
            "; the spec acme/Foo @ ^1.0.0 should NOT be touched in this comment\n"
            "lib_deps =\n"
            "    acme/Foo @ ^1.0.0\n"
        )
        (tmp_path / "platformio.ini").write_text(ini)
        mock_pio.add_lib(
            "test",
            "acme/Foo @ ^1.0.0",
            "Foo",
            "1.0.0",
            latest="1.2.0",
            wanted="1.2.0",
        )
        rc = lockfile.update(tmp_path, ["test"], dry_run=False)
        assert rc == 0
        new_ini = (tmp_path / "platformio.ini").read_text()
        # Comment line still has old spec
        assert "; the spec acme/Foo @ ^1.0.0" in new_ini
        # But the lib_deps entry has the new one
        assert "acme/Foo @ ^1.2.0" in new_ini


# ── Tests for ConfigSourceTracker ─────────────────────────────────────────────


class TestConfigSourceTracker:
    def test_tracks_option_source(self, tmp_path):
        main_ini = tmp_path / "platformio.ini"
        main_ini.write_text("[env:test]\nboard = esp32\n")

        config = MagicMock()
        config._parsed = [str(main_ini)]
        tracker = lockfile.ConfigSourceTracker(config)

        assert tracker.get_source("env:test", "board") == main_ini

    def test_last_file_wins(self, tmp_path):
        first = tmp_path / "base.ini"
        first.write_text("[env:test]\nlib_deps = acme/Old @ 1.0\n")
        second = tmp_path / "override.ini"
        second.write_text("[env:test]\nlib_deps = acme/New @ 2.0\n")

        config = MagicMock()
        config._parsed = [str(first), str(second)]
        tracker = lockfile.ConfigSourceTracker(config)

        assert tracker.get_source("env:test", "lib_deps") == second

    def test_find_file_for_value(self, tmp_path):
        main_ini = tmp_path / "platformio.ini"
        main_ini.write_text("[env:test]\nlib_deps = acme/Main @ ^1.0\n")
        extra_ini = tmp_path / "shared.ini"
        extra_ini.write_text("[env:test]\nlib_deps = acme/Shared @ ^2.0\n")

        config = MagicMock()
        config._parsed = [str(main_ini), str(extra_ini)]
        tracker = lockfile.ConfigSourceTracker(config)

        assert tracker.find_file_for_value("acme/Main @ ^1.0") == main_ini
        assert tracker.find_file_for_value("acme/Shared @ ^2.0") == extra_ini
        assert tracker.find_file_for_value("nonexistent") is None

    def test_files_property(self, tmp_path):
        main_ini = tmp_path / "platformio.ini"
        main_ini.write_text("[env:test]\n")
        extra = tmp_path / "extra.ini"
        extra.write_text("[env:prod]\n")

        config = MagicMock()
        config._parsed = [str(main_ini), str(extra)]
        tracker = lockfile.ConfigSourceTracker(config)

        assert tracker.files == [main_ini, extra]

    def test_fallback_path(self, tmp_path):
        main_ini = tmp_path / "platformio.ini"
        main_ini.write_text("[env:test]\nboard = esp32\n")

        config = MagicMock(spec=[])
        del config._parsed
        tracker = lockfile.ConfigSourceTracker(config, fallback_path=main_ini)

        assert tracker.get_source("env:test", "board") == main_ini


# ── Tests for _build_updated_spec ────────────────────────────────────────────


class TestBuildUpdatedSpec:
    def test_caret_range(self):
        result = lockfile._build_updated_spec("acme/Foo @ ^1.0.0", "1.2.0")
        assert result == "acme/Foo @ ^1.2.0"

    def test_tilde_range(self):
        result = lockfile._build_updated_spec("acme/Foo @ ~1.0.0", "1.0.5")
        assert result == "acme/Foo @ ~1.0.5"

    def test_exact_version(self):
        result = lockfile._build_updated_spec("acme/Foo @ 1.0.4", "1.0.6")
        assert result == "acme/Foo @ 1.0.6"

    def test_gte_range(self):
        result = lockfile._build_updated_spec("acme/Foo @ >=1.0", "2.0")
        assert result == "acme/Foo @ >=2.0"

    def test_no_at_sign(self):
        result = lockfile._build_updated_spec("SomeLib", "1.0.0")
        assert result is None

    def test_preserves_owner(self):
        result = lockfile._build_updated_spec(
            "blues/Blues Wireless Notecard @ ^1.8.3", "1.8.5"
        )
        assert result == "blues/Blues Wireless Notecard @ ^1.8.5"


# ── Tests for GitHub URL parsing ──────────────────────────────────────────────


class TestParseGitHubUrl:
    def test_https_with_ref(self):
        result = lockfile._parse_github_url("https://github.com/owner/repo.git#v1.0")
        assert result == ("owner", "repo", "v1.0")

    def test_https_without_ref(self):
        result = lockfile._parse_github_url("https://github.com/owner/repo.git")
        assert result == ("owner", "repo", None)

    def test_https_without_git_suffix(self):
        result = lockfile._parse_github_url("https://github.com/owner/repo#main")
        assert result == ("owner", "repo", "main")

    def test_sha_ref(self):
        result = lockfile._parse_github_url(
            "https://github.com/owner/repo#5fddfb83b13057211ca71e000529c3f23609c1d7"
        )
        assert result == ("owner", "repo", "5fddfb83b13057211ca71e000529c3f23609c1d7")

    def test_not_github(self):
        assert lockfile._parse_github_url("https://gitlab.com/owner/repo") is None

    def test_empty_string(self):
        assert lockfile._parse_github_url("") is None

    def test_registry_spec(self):
        assert lockfile._parse_github_url("acme/Foo @ ^1.0") is None


class TestParsePlatformReleaseUrl:
    def test_release_download_url(self):
        url = "https://github.com/pioarduino/platform-espressif32/releases/download/55.03.36/platform-espressif32.zip"
        result = lockfile._parse_platform_release_url(url)
        assert result == ("pioarduino", "platform-espressif32", "55.03.36")

    def test_archive_refs_tags_zip(self):
        url = "https://github.com/pioarduino/platform-espressif32/archive/refs/tags/55.03.36.zip"
        result = lockfile._parse_platform_release_url(url)
        assert result == ("pioarduino", "platform-espressif32", "55.03.36")

    def test_archive_refs_tags_tar_gz(self):
        url = "https://github.com/pioarduino/platform-espressif32/archive/refs/tags/55.03.36.tar.gz"
        result = lockfile._parse_platform_release_url(url)
        assert result == ("pioarduino", "platform-espressif32", "55.03.36")

    def test_archive_short_form(self):
        url = "https://github.com/pioarduino/platform-espressif32/archive/55.03.36.zip"
        result = lockfile._parse_platform_release_url(url)
        assert result == ("pioarduino", "platform-espressif32", "55.03.36")

    def test_git_ref_url(self):
        url = "https://github.com/pioarduino/platform-espressif32.git#55.03.36"
        result = lockfile._parse_platform_release_url(url)
        assert result == ("pioarduino", "platform-espressif32", "55.03.36")

    def test_git_plus_https(self):
        url = "git+https://github.com/pioarduino/platform-espressif32.git#55.03.36"
        result = lockfile._parse_platform_release_url(url)
        assert result == ("pioarduino", "platform-espressif32", "55.03.36")

    def test_not_github(self):
        assert lockfile._parse_platform_release_url("native") is None

    def test_bare_repo_url(self):
        # No version reference -> not parseable
        assert (
            lockfile._parse_platform_release_url("https://github.com/owner/repo") is None
        )


# ── Tests for git ref classification ──────────────────────────────────────────


class TestClassifyGitRef:
    def test_sha_40_chars(self):
        assert lockfile._classify_git_ref("5fddfb83b13057211ca71e000529c3f23609c1d7") == "sha"

    def test_sha_7_chars(self):
        assert lockfile._classify_git_ref("5fddfb8") == "sha"

    def test_version_tag_with_v(self):
        assert lockfile._classify_git_ref("v2.0.0") == "tag"

    def test_version_tag_without_v(self):
        assert lockfile._classify_git_ref("4.2.1") == "tag"

    def test_version_tag_two_parts(self):
        assert lockfile._classify_git_ref("v2.0") == "tag"

    def test_branch_name(self):
        assert lockfile._classify_git_ref("fix/notify-characteristics") == "branch"

    def test_branch_main(self):
        assert lockfile._classify_git_ref("main") == "branch"

    def test_none_is_default(self):
        assert lockfile._classify_git_ref(None) == "default"


# ── Tests for GitHub-aware dep checks ────────────────────────────────────────


class FakeGitHubClient:
    """Mock GitHubClient that returns pre-configured responses."""

    def __init__(self, responses: dict[str, Any]):
        self._responses = responses

    def get_json(self, api_path: str) -> Optional[Any]:
        return self._responses.get(api_path)


class TestCheckShaDep:
    def test_sha_is_head_of_main(self):
        sha = "5fddfb83b13057211ca71e000529c3f23609c1d7"
        github = FakeGitHubClient(
            {
                f"repos/owner/repo/commits/{sha}/branches-where-head": [{"name": "main"}],
            }
        )
        result = lockfile._check_sha_dep("owner", "repo", sha, "my-lib", github)
        assert result is not None
        assert result["status"] == "up_to_date"
        assert result["branch"] == "main"
        assert result["confidence"] == "high"

    def test_sha_is_head_of_feature_branch(self):
        sha = "abc1234567890abcdef1234567890abcdef123456"
        github = FakeGitHubClient(
            {
                f"repos/owner/repo/commits/{sha}/branches-where-head": [
                    {"name": "feature/something"}
                ],
            }
        )
        result = lockfile._check_sha_dep("owner", "repo", sha, "my-lib", github)
        assert result is not None
        assert result["status"] == "up_to_date"
        assert result["branch"] == "feature/something"
        assert result["confidence"] == "medium"

    def test_sha_behind_default_branch(self):
        sha = "oldsha00000000000000000000000000000000000"
        github = FakeGitHubClient(
            {
                f"repos/owner/repo/commits/{sha}/branches-where-head": [],
                f"repos/owner/repo/compare/{sha}...HEAD": {
                    "ahead_by": 5,
                    "commits": [
                        {},
                        {},
                        {},
                        {},
                        {"sha": "newsha99999999999999999999999999999999999"},
                    ],
                },
                "repos/owner/repo": {"default_branch": "main"},
            }
        )
        result = lockfile._check_sha_dep("owner", "repo", sha, "my-lib", github)
        assert result is not None
        assert result["status"] == "outdated"
        assert result["ahead_by"] == 5
        assert result["branch"] == "main"
        assert result["confidence"] == "high"
        assert "5 commits behind main" in result["message"]

    def test_sha_up_to_date_via_compare(self):
        sha = "currentsha0000000000000000000000000000000"
        github = FakeGitHubClient(
            {
                f"repos/owner/repo/commits/{sha}/branches-where-head": [],
                f"repos/owner/repo/compare/{sha}...HEAD": {"ahead_by": 0},
            }
        )
        result = lockfile._check_sha_dep("owner", "repo", sha, "my-lib", github)
        assert result is not None
        assert result["status"] == "up_to_date"

    def test_github_api_failure(self):
        sha = "abc1234567890abcdef1234567890abcdef123456"
        github = FakeGitHubClient({})
        result = lockfile._check_sha_dep("owner", "repo", sha, "my-lib", github)
        assert result is None


class TestCheckTagDep:
    def test_latest_tag(self):
        github = FakeGitHubClient(
            {
                "repos/owner/repo/tags?per_page=100": [
                    {"name": "v2.0.0", "commit": {"sha": "abc"}},
                    {"name": "v1.1.0", "commit": {"sha": "def"}},
                ],
            }
        )
        result = lockfile._check_tag_dep("owner", "repo", "v2.0.0", "my-lib", github)
        assert result is not None
        assert result["status"] == "up_to_date"
        assert result["message"] == "latest tag"

    def test_newer_tag_available(self):
        github = FakeGitHubClient(
            {
                "repos/owner/repo/tags?per_page=100": [
                    {"name": "v3.0.0", "commit": {"sha": "abc"}},
                    {"name": "v2.1.0", "commit": {"sha": "def"}},
                    {"name": "v2.0.0", "commit": {"sha": "ghi"}},
                    {"name": "v1.0.0", "commit": {"sha": "jkl"}},
                ],
            }
        )
        result = lockfile._check_tag_dep("owner", "repo", "v2.0.0", "my-lib", github)
        assert result is not None
        assert result["status"] == "outdated"
        assert result["latest_tag"] == "v3.0.0"
        assert "v3.0.0" in result["message"]

    def test_respects_v_prefix_convention(self):
        github = FakeGitHubClient(
            {
                "repos/owner/repo/tags?per_page=100": [
                    {"name": "5.0.0", "commit": {"sha": "abc"}},
                    {"name": "v2.0.0", "commit": {"sha": "def"}},
                ],
            }
        )
        result = lockfile._check_tag_dep("owner", "repo", "v2.0.0", "my-lib", github)
        assert result is not None
        assert result["status"] == "up_to_date"

    def test_no_v_prefix_finds_newer(self):
        github = FakeGitHubClient(
            {
                "repos/owner/repo/tags?per_page=100": [
                    {"name": "5.0.0", "commit": {"sha": "abc"}},
                    {"name": "4.2.1", "commit": {"sha": "def"}},
                    {"name": "v1.0.0", "commit": {"sha": "ghi"}},
                ],
            }
        )
        result = lockfile._check_tag_dep("owner", "repo", "4.2.1", "my-lib", github)
        assert result is not None
        assert result["status"] == "outdated"
        assert result["latest_tag"] == "5.0.0"

    def test_skips_prerelease_for_stable(self):
        """A prerelease tag should not be promoted as newer for a stable current."""
        github = FakeGitHubClient(
            {
                "repos/owner/repo/tags?per_page=100": [
                    {"name": "v3.0.0-rc1", "commit": {"sha": "abc"}},
                    {"name": "v2.0.0", "commit": {"sha": "def"}},
                ],
            }
        )
        result = lockfile._check_tag_dep("owner", "repo", "v2.0.0", "my-lib", github)
        assert result is not None
        assert result["status"] == "up_to_date"

    def test_api_failure(self):
        github = FakeGitHubClient({})
        result = lockfile._check_tag_dep("owner", "repo", "v1.0", "my-lib", github)
        assert result is None


class TestCheckPlatform:
    PIO_URL = (
        "https://github.com/pioarduino/platform-espressif32/releases/download/"
        "55.03.36/platform-espressif32.zip"
    )
    PIO_RELEASES_KEY = "repos/pioarduino/platform-espressif32/releases?per_page=50"

    def test_newer_release_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: self.PIO_URL)
        github = FakeGitHubClient(
            {
                self.PIO_RELEASES_KEY: [
                    {"tag_name": "55.03.37", "draft": False, "prerelease": False},
                    {"tag_name": "55.03.36", "draft": False, "prerelease": False},
                    {"tag_name": "55.03.35", "draft": False, "prerelease": False},
                ],
            }
        )
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is not None
        assert result["status"] == "outdated"
        assert result["latest"] == "55.03.37"
        assert "55.03.37" in result["message"]

    def test_up_to_date(self, tmp_path, monkeypatch):
        url = self.PIO_URL.replace("55.03.36", "55.03.37")
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: url)
        github = FakeGitHubClient(
            {
                self.PIO_RELEASES_KEY: [
                    {"tag_name": "55.03.37", "draft": False, "prerelease": False},
                    {"tag_name": "55.03.36", "draft": False, "prerelease": False},
                ],
            }
        )
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is not None
        assert result["status"] == "up_to_date"

    def test_skips_prerelease(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: self.PIO_URL)
        github = FakeGitHubClient(
            {
                self.PIO_RELEASES_KEY: [
                    {"tag_name": "55.03.37-rc1", "draft": False, "prerelease": True},
                    {"tag_name": "55.03.36", "draft": False, "prerelease": False},
                ],
            }
        )
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is not None
        assert result["status"] == "up_to_date"

    def test_unsupported_url_format(self, tmp_path, monkeypatch):
        """Non-GitHub platform URL → unsupported_url status (not None)."""
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: "native")
        github = FakeGitHubClient({})
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is not None
        assert result["status"] == "unsupported_url"

    def test_unknown_platform(self, tmp_path, monkeypatch):
        """get_platform_url returning 'unknown' → returns None."""
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: "unknown")
        github = FakeGitHubClient({})
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is None

    def test_cross_major_update_reported(self, tmp_path, monkeypatch):
        """A higher-major release without same-major newer → major_update_available."""
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: self.PIO_URL)
        github = FakeGitHubClient(
            {
                self.PIO_RELEASES_KEY: [
                    {"tag_name": "56.00.00", "draft": False, "prerelease": False},
                    {"tag_name": "55.03.36", "draft": False, "prerelease": False},
                ],
            }
        )
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is not None
        assert result["status"] == "major_update_available"
        assert result["latest_major"] == "56.00.00"
        assert "cross-major" in result["message"]

    def test_outdated_mentions_cross_major(self, tmp_path, monkeypatch):
        """If both same-major newer AND higher-major exist, status is outdated but
        the message mentions the cross-major tag."""
        monkeypatch.setattr(lockfile, "get_platform_url", lambda _d, _e: self.PIO_URL)
        github = FakeGitHubClient(
            {
                self.PIO_RELEASES_KEY: [
                    {"tag_name": "56.00.00", "draft": False, "prerelease": False},
                    {"tag_name": "55.03.37", "draft": False, "prerelease": False},
                    {"tag_name": "55.03.36", "draft": False, "prerelease": False},
                ],
            }
        )
        result = lockfile._check_platform(tmp_path, "test", github)
        assert result is not None
        assert result["status"] == "outdated"
        assert result["latest"] == "55.03.37"
        assert result["latest_major"] == "56.00.00"
        assert "cross-major" in result["message"]


class TestCheckGitDeps:
    def test_filters_git_deps_only(self):
        entries = [
            {
                "name": "Foo",
                "type": "registry",
                "spec_str": "acme/Foo @ ^1.0",
                "current": "1.0",
            },
            {
                "name": "bar",
                "type": "git",
                "spec_str": "https://github.com/x/bar.git#v1.0",
                "current": "1.0",
            },
        ]
        github = FakeGitHubClient(
            {
                "repos/x/bar/tags?per_page=100": [
                    {"name": "v1.0", "commit": {"sha": "abc"}},
                ],
            }
        )
        results = lockfile._check_git_deps(entries, github)
        assert len(results) == 1
        assert results[0]["name"] == "bar"

    def test_deduplicates_by_name(self):
        entries = [
            {
                "name": "bar",
                "type": "git",
                "spec_str": "https://github.com/x/bar.git#v1.0",
                "current": "1.0",
            },
            {
                "name": "bar",
                "type": "git",
                "spec_str": "https://github.com/x/bar.git#v1.0",
                "current": "1.0",
            },
        ]
        github = FakeGitHubClient(
            {
                "repos/x/bar/tags?per_page=100": [
                    {"name": "v1.0", "commit": {"sha": "abc"}},
                ],
            }
        )
        results = lockfile._check_git_deps(entries, github)
        assert len(results) == 1


class TestCreateGitHubClient:
    def test_returns_none_without_token_or_gh(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr("shutil.which", lambda _: None)
        assert lockfile._create_github_client() is None

    def test_prefers_token_over_gh(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        client = lockfile._create_github_client()
        assert client is not None
        assert client._method == "token"
        assert client._token == "test-token"

    def test_falls_back_to_gh(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(
            "shutil.which", lambda name: "/usr/local/bin/gh" if name == "gh" else None
        )
        client = lockfile._create_github_client()
        assert client is not None
        assert client._method == "gh"


class TestParseVersionTuple:
    def test_semver(self):
        assert lockfile._parse_version_tuple("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert lockfile._parse_version_tuple("v2.0.0") == (2, 0, 0)

    def test_two_parts(self):
        assert lockfile._parse_version_tuple("55.03") == (55, 3)

    def test_three_parts_with_leading_zeros(self):
        assert lockfile._parse_version_tuple("55.03.36") == (55, 3, 36)

    def test_with_rc_suffix(self):
        assert lockfile._parse_version_tuple("55.03.36-rc1") == (55, 3, 36)

    def test_with_plus_suffix(self):
        assert lockfile._parse_version_tuple("1.0.0+esp32") == (1, 0, 0)

    def test_invalid(self):
        assert lockfile._parse_version_tuple("not-a-version") is None

    def test_empty(self):
        assert lockfile._parse_version_tuple("") is None


class TestIsPrereleaseTag:
    def test_rc(self):
        assert lockfile._is_prerelease_tag("55.03.36-rc1") is True

    def test_alpha(self):
        assert lockfile._is_prerelease_tag("1.0.0-alpha") is True

    def test_beta_with_number(self):
        assert lockfile._is_prerelease_tag("1.0.0-beta2") is True

    def test_stable(self):
        assert lockfile._is_prerelease_tag("55.03.36") is False

    def test_arduino_suffix_not_prerelease(self):
        assert lockfile._is_prerelease_tag("1.0.0-arduino") is False
