#!/usr/bin/env python3
"""pio-lock — PIO dependency lockfile tool.

Captures resolved dependency versions into a lockfile (pio.lock.json) for
reproducible builds. Works alongside platformio.ini, which declares desired
version ranges; this tool records the exact versions that were actually installed.

License: MIT

Copyright Mat McGowan https://github.com/m-mcgowan/pio-lock
"""

from __future__ import annotations

import configparser
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from platformio.package.manager.library import LibraryPackageManager
from platformio.package.meta import PackageSpec
from platformio.project.config import ProjectConfig


LOCKFILE_NAME = "pio.lock.json"
SNAPSHOT_NAME = "build_snapshot.json"

# Global packages to record (frameworks and toolchains — the ones that matter
# for build reproducibility). Skip IDE helpers, contrib, filesystem tools.
GLOBAL_PACKAGE_PREFIXES = (
    "framework-",
    "toolchain-",
    "tool-esptoolpy",
    "tool-cmake",
    "tool-ninja",
    "tool-scons",
)


def _default_run_cmd(args: list[str], cwd: Optional[str] = None, check: bool = True) -> str:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        check=check,
    )
    return result.stdout.strip()


def run_cmd(args: list[str], cwd: Optional[str | Path] = None, check: bool = True) -> str:
    """Run a command and return stdout, stripped."""
    return _run_cmd(args, cwd=str(cwd) if cwd else None, check=check)


# ── Git helpers ──────────────────────────────────────────────────────────────


def get_git_sha(path: str | Path) -> str:
    return run_cmd(["git", "rev-parse", "HEAD"], cwd=str(path))


def get_git_remote_url(path: str | Path) -> str:
    return run_cmd(["git", "remote", "get-url", "origin"], cwd=str(path), check=False)


def get_git_commit(project_dir: Path) -> str:
    try:
        return run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=str(project_dir))
    except subprocess.CalledProcessError:
        return "unknown"


def is_git_dirty(project_dir: Path) -> bool:
    """Check if the working tree has uncommitted changes."""
    try:
        status = run_cmd(["git", "status", "--porcelain"], cwd=str(project_dir), check=False)
        return len(status) > 0
    except subprocess.CalledProcessError:
        return False


# ── Build snapshot ───────────────────────────────────────────────────────────


def load_snapshot(project_dir: Path) -> Optional[dict[str, Any]]:
    """Load an existing build snapshot, or return None."""
    path = project_dir / SNAPSHOT_NAME
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text())
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: Failed to read {SNAPSHOT_NAME}: {e}", file=sys.stderr)
        return None


def generate_snapshot(project_dir: Path, *, pinned: bool = False) -> dict[str, Any]:
    """Generate a new build snapshot from the current state."""
    epoch = int(time.time())
    commit = get_git_commit(project_dir)
    dirty = is_git_dirty(project_dir)

    snapshot: dict[str, Any] = {
        "source_date_epoch": epoch,
        "build_date": datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(),
        "git_commit": commit,
        "git_dirty": dirty,
        "pinned": pinned,
    }

    if dirty:
        print("WARNING: Working tree has uncommitted changes", file=sys.stderr)

    path = project_dir / SNAPSHOT_NAME
    path.write_text(json.dumps(snapshot, indent=2) + "\n")
    dirty_marker = "*" if dirty else ""
    print(f"Build snapshot generated: {snapshot['build_date']} (commit {commit}{dirty_marker})")
    return snapshot


def is_snapshot_stale(snapshot: dict[str, Any], project_dir: Path) -> bool:
    """Check if a snapshot's commit doesn't match HEAD."""
    head = get_git_commit(project_dir)
    return head != "unknown" and snapshot.get("git_commit") != head


def apply_snapshot(snapshot: dict[str, Any]) -> None:
    """Set SOURCE_DATE_EPOCH from the snapshot."""
    epoch = str(snapshot["source_date_epoch"])
    os.environ["SOURCE_DATE_EPOCH"] = epoch
    build_date = snapshot.get("build_date", "unknown")
    commit = snapshot.get("git_commit", "unknown")
    pinned = snapshot.get("pinned", False)
    tag = " [pinned]" if pinned else ""
    print(f"Build snapshot: SOURCE_DATE_EPOCH={epoch} ({build_date}, commit {commit}{tag})")


def snapshot_auto_manage(project_dir: Path, env: Any = None) -> None:
    """Auto-manage the snapshot during builds.

    Called from the PIO extra_script hook. Sets SOURCE_DATE_EPOCH so that
    __DATE__ and __TIME__ macros are deterministic across rebuilds.
    """
    snapshot = load_snapshot(project_dir)
    release = _is_release_mode(snapshot, env)

    if snapshot is None:
        if release:
            print(
                f"ERROR: No {SNAPSHOT_NAME} in release mode. Run: pio run -t snapshot-capture",
                file=sys.stderr,
            )
            if env:
                env.Exit(1)
            return
        snapshot = generate_snapshot(project_dir)
    elif snapshot.get("pinned", False):
        # Pinned — never auto-regenerate
        pass
    elif is_snapshot_stale(snapshot, project_dir):
        if release:
            head = get_git_commit(project_dir)
            print(
                f"ERROR: {SNAPSHOT_NAME} is stale in release mode. "
                f"Snapshot commit: {snapshot.get('git_commit')}, HEAD: {head}",
                file=sys.stderr,
            )
            if env:
                env.Exit(1)
            return
        head = get_git_commit(project_dir)
        print(
            f"Build snapshot stale (was {snapshot.get('git_commit')}, "
            f"HEAD is {head}), regenerating..."
        )
        snapshot = generate_snapshot(project_dir)

    apply_snapshot(snapshot)


def _is_release_mode(snapshot: Optional[dict[str, Any]], env: Any = None) -> bool:
    """Check if any release mode indicator is active."""
    if snapshot and snapshot.get("pinned", False):
        return True
    if os.environ.get("PIO_RELEASE_BUILD", "").strip() == "1":
        return True
    if env is not None:
        try:
            val = env.GetProjectOption("custom_reproducible_release", "false")
            if val.strip().lower() == "true":
                return True
        except Exception:
            pass
    return False


def snapshot_capture(project_dir: Path) -> int:
    """Generate/overwrite a build snapshot from current HEAD."""
    generate_snapshot(project_dir)
    return 0


def snapshot_check(project_dir: Path) -> int:
    """Verify snapshot matches HEAD. Returns non-zero if stale/missing."""
    snapshot = load_snapshot(project_dir)
    if snapshot is None:
        print("No build snapshot found.")
        return 1

    head = get_git_commit(project_dir)
    commit = snapshot.get("git_commit")
    pinned = snapshot.get("pinned", False)
    stale = head != "unknown" and commit != head

    print(f"Snapshot: {snapshot.get('build_date', 'unknown')}")
    print(f"  Commit:  {commit} {'(pinned)' if pinned else ''}")
    print(f"  HEAD:    {head}")
    print(f"  Dirty:   {snapshot.get('git_dirty', 'unknown')}")
    print(f"  Status:  {'STALE' if stale else 'FRESH'}")

    return 1 if stale else 0


def snapshot_clear(project_dir: Path) -> int:
    """Delete the build snapshot file."""
    path = project_dir / SNAPSHOT_NAME
    if path.exists():
        path.unlink()
        print(f"Build snapshot removed: {path}")
    else:
        print("No build snapshot to remove.")
    return 0


def snapshot_print(project_dir: Path) -> int:
    """Print the build snapshot contents."""
    snapshot = load_snapshot(project_dir)
    if snapshot is None:
        print("No build snapshot found.")
        return 1
    print(json.dumps(snapshot, indent=2))
    return 0


# ── PIO helpers ──────────────────────────────────────────────────────────────


def get_pio_core_version() -> str:
    output = run_cmd(["pio", "system", "info"])
    for line in output.splitlines():
        if "PlatformIO Core" in line:
            parts = line.split()
            return parts[-1]
    return "unknown"


def get_platform_url(project_dir: Path, env_name: str) -> str:
    try:
        output = run_cmd(["pio", "project", "config", "--json-output"], cwd=str(project_dir))
        sections = json.loads(output)
        for section in sections:
            if section[0] == f"env:{env_name}":
                for key, val in section[1]:
                    if key == "platform":
                        return str(val)
        for section in sections:
            if section[0] == "env":
                for key, val in section[1]:
                    if key == "platform":
                        return str(val)
    except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError):
        pass
    return "unknown"


def get_pio_home() -> Path:
    import os

    pio_home = os.environ.get("PLATFORMIO_CORE_DIR")
    if pio_home:
        return Path(pio_home)
    return Path.home() / ".platformio"


# ── Scanners ─────────────────────────────────────────────────────────────────


def scan_global_packages() -> dict[str, str]:
    packages_dir = get_pio_home() / "packages"
    packages: dict[str, str] = {}

    if not packages_dir.is_dir():
        return packages

    for pkg_dir in sorted(packages_dir.iterdir()):
        if not pkg_dir.is_dir():
            continue

        name = pkg_dir.name
        if not any(name.startswith(p) for p in GLOBAL_PACKAGE_PREFIXES):
            continue

        pkg_json = pkg_dir / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                packages[data.get("name", name)] = data.get("version", "unknown")
            except (json.JSONDecodeError, KeyError):
                packages[name] = "unknown"

    return packages


def scan_env_libraries(project_dir: Path, env_name: str) -> list[dict[str, Any]]:
    """Scan .pio/libdeps/<env>/ for installed library versions."""
    libdeps_dir = project_dir / ".pio" / "libdeps" / env_name
    libraries: list[dict[str, Any]] = []

    if not libdeps_dir.is_dir():
        print(f"  Warning: {libdeps_dir} does not exist", file=sys.stderr)
        return libraries

    for lib_dir in sorted(libdeps_dir.iterdir()):
        if not lib_dir.is_dir():
            continue

        name = lib_dir.name

        # Skip PIO shadow copies (e.g. NimBLE-Arduino@src-abc123)
        if "@src-" in name:
            continue

        entry = _scan_single_library(lib_dir, name)
        if entry is not None:
            libraries.append(entry)

    return libraries


def _scan_single_library(lib_dir: Path, name: str) -> Optional[dict[str, Any]]:
    """Scan a single library directory and return its lockfile entry."""
    piopm_path = lib_dir / ".piopm"

    if piopm_path.exists():
        try:
            meta = json.loads(piopm_path.read_text())
        except json.JSONDecodeError:
            print(f"  Warning: corrupt .piopm in {name}", file=sys.stderr)
            return None

        spec = meta.get("spec", {})
        uri = spec.get("uri") or ""

        if uri.startswith("file://"):
            return {
                "name": meta.get("name", name),
                "type": "local",
                "path": uri,
            }
        else:
            entry: dict[str, Any] = {
                "name": meta.get("name", name),
                "type": "registry",
                "version": meta.get("version", "unknown"),
            }
            owner = spec.get("owner")
            if owner:
                entry["owner"] = owner
            return entry

    elif (lib_dir / ".git").exists() or (lib_dir / ".git").is_file():
        sha = get_git_sha(lib_dir)
        url = get_git_remote_url(lib_dir)

        display_name = name
        lib_json_path = lib_dir / "library.json"
        if lib_json_path.exists():
            try:
                lib_data = json.loads(lib_json_path.read_text())
                display_name = lib_data.get("name", name)
            except json.JSONDecodeError:
                pass

        return {
            "name": display_name,
            "type": "git",
            "url": url,
            "sha": sha,
        }
    else:
        print(
            f"  Warning: {name} has no .piopm and no .git — skipping",
            file=sys.stderr,
        )
        return None


# ── Version check helpers ────────────────────────────────────────────────────


def is_installed_at_locked_version(
    project_dir: Path, env_name: str, lib_entry: dict[str, Any]
) -> bool:
    """Check if a library is already installed at the locked version."""
    libdeps_dir = project_dir / ".pio" / "libdeps" / env_name

    if not libdeps_dir.is_dir():
        return False

    if lib_entry["type"] == "registry":
        for lib_dir in libdeps_dir.iterdir():
            if not lib_dir.is_dir():
                continue
            piopm = lib_dir / ".piopm"
            if piopm.exists():
                try:
                    meta = json.loads(piopm.read_text())
                    if meta.get("name") == lib_entry["name"]:
                        return bool(meta.get("version") == lib_entry["version"])
                except json.JSONDecodeError:
                    pass
        return False

    elif lib_entry["type"] == "git":
        for lib_dir in libdeps_dir.iterdir():
            if not lib_dir.is_dir():
                continue
            if not ((lib_dir / ".git").exists() or (lib_dir / ".git").is_file()):
                continue
            try:
                url = get_git_remote_url(lib_dir)
                if url == lib_entry["url"]:
                    sha = get_git_sha(lib_dir)
                    return bool(sha == lib_entry["sha"])
            except subprocess.CalledProcessError:
                pass
        return False

    return True  # local libs are always "installed"


# ── Commands ─────────────────────────────────────────────────────────────────


def capture(
    project_dir: Path,
    envs: list[str],
    output_path: Optional[Path] = None,
) -> int:
    """Capture resolved dependency versions into a lockfile."""
    if not (project_dir / "platformio.ini").exists():
        print(f"Error: no platformio.ini in {project_dir}", file=sys.stderr)
        return 1

    print(f"Capturing dependency state for: {', '.join(envs)}")

    lockdata: dict[str, Any] = {
        "_comment": "Generated by pio-lock. Do not edit manually.",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_from_commit": get_git_commit(project_dir),
        "pio_core_version": get_pio_core_version(),
        "global_packages": scan_global_packages(),
        "envs": {},
    }

    lockdata["platform_url"] = get_platform_url(project_dir, envs[0])

    for env_name in envs:
        print(f"  Scanning {env_name}...")
        libraries = scan_env_libraries(project_dir, env_name)
        lockdata["envs"][env_name] = {"libraries": libraries}
        print(f"    Found {len(libraries)} libraries")

    dest = output_path or (project_dir / LOCKFILE_NAME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(lockdata, indent=2) + "\n")
    print(f"Wrote {dest}")
    return 0


def restore(project_dir: Path, envs: list[str]) -> int:
    """Install exact versions from the lockfile."""
    lockfile_path = project_dir / LOCKFILE_NAME
    if not lockfile_path.exists():
        print(f"Error: no {LOCKFILE_NAME} in {project_dir}", file=sys.stderr)
        return 1

    lockdata = json.loads(lockfile_path.read_text())

    for env_name in envs:
        if env_name not in lockdata.get("envs", {}):
            print(f"Error: env '{env_name}' not in lockfile", file=sys.stderr)
            return 1

        libraries = lockdata["envs"][env_name]["libraries"]
        print(f"Restoring {len(libraries)} libraries for {env_name}...")

        skip_count = 0
        install_count = 0

        for lib in libraries:
            if lib["type"] == "local":
                continue

            if is_installed_at_locked_version(project_dir, env_name, lib):
                skip_count += 1
                continue

            spec = _lib_install_spec(lib)
            if spec is None:
                continue

            print(f"  Installing: {lib['name']}")
            try:
                run_cmd(
                    [
                        "pio",
                        "pkg",
                        "install",
                        "-d",
                        str(project_dir),
                        "-e",
                        env_name,
                        "--library",
                        spec,
                        "--no-save",
                        "--skip-dependencies",
                    ],
                    cwd=str(project_dir),
                )
                install_count += 1
            except subprocess.CalledProcessError as e:
                print(f"  Error installing {lib['name']}: {e}", file=sys.stderr)
                return 1

        print(f"  Done: {install_count} installed, {skip_count} already up-to-date")

    return 0


def check(project_dir: Path, envs: list[str]) -> int:
    """Verify installed state matches the lockfile."""
    lockfile_path = project_dir / LOCKFILE_NAME
    if not lockfile_path.exists():
        print(f"Error: no {LOCKFILE_NAME} in {project_dir}", file=sys.stderr)
        return 1

    lockdata = json.loads(lockfile_path.read_text())
    drift_found = False

    for env_name in envs:
        if env_name not in lockdata.get("envs", {}):
            print(f"Error: env '{env_name}' not in lockfile", file=sys.stderr)
            return 1

        print(f"Checking {env_name}...")

        for lib in lockdata["envs"][env_name]["libraries"]:
            if lib["type"] == "local":
                continue

            if not is_installed_at_locked_version(project_dir, env_name, lib):
                drift_found = True
                if lib["type"] == "registry":
                    print(f"  DRIFT: {lib['name']} — expected {lib['version']}")
                elif lib["type"] == "git":
                    print(f"  DRIFT: {lib['name']} — expected SHA {lib['sha'][:12]}")

    if drift_found:
        print("Lockfile check FAILED — installed state differs from lockfile")
        return 1
    else:
        print("Lockfile check passed — all libraries match")
        return 0


def _lib_install_spec(lib: dict[str, Any]) -> Optional[str]:
    """Build a PIO install spec string for a locked library."""
    if lib["type"] == "registry":
        owner = lib.get("owner", "")
        name = lib["name"]
        version = lib["version"]
        return f"{owner}/{name} @ =={version}" if owner else f"{name} @ =={version}"
    elif lib["type"] == "git":
        return f"{lib['url']}#{lib['sha']}"
    return None


# ── GitHub-aware update detection ──────────────────────────────────────────


def _parse_github_url(url: str) -> Optional[tuple[str, str, Optional[str]]]:
    """Parse a GitHub URL into (owner/repo, ref).

    Returns (owner, repo, ref) or None if not a GitHub URL.
    ref is None if no #ref is specified.

    Handles:
      https://github.com/owner/repo.git#ref
      https://github.com/owner/repo#ref
      https://github.com/owner/repo
    """
    match = re.match(r"https?://github\.com/([^/]+)/([^/#.]+)(?:\.git)?(?:#(.+))?$", url)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _parse_platform_release_url(url: str) -> Optional[tuple[str, str, str]]:
    """Parse a GitHub release download URL into (owner, repo, version).

    Handles: https://github.com/owner/repo/releases/download/VERSION/filename
    """
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/", url)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_VERSION_TAG_RE = re.compile(r"^v?\d+\.\d+(?:\.\d+)?(?:[._-].+)?$")


def _classify_git_ref(ref: Optional[str]) -> str:
    """Classify a git ref as 'sha', 'tag', 'branch', or 'default'.

    Heuristic:
      - 40 hex chars (or 7+ hex-only) → sha
      - Matches v?DIGIT.DIGIT[.DIGIT] → tag (version-like)
      - None → default (tracks default branch)
      - Everything else → branch
    """
    if ref is None:
        return "default"
    if _SHA_RE.match(ref):
        return "sha"
    if _VERSION_TAG_RE.match(ref):
        return "tag"
    return "branch"


_HIGH_CONFIDENCE_BRANCHES = frozenset(
    {"main", "master", "release", "releases", "stable", "develop"}
)


class GitHubClient:
    """Thin wrapper for GitHub REST API access.

    Tries GITHUB_TOKEN env var first (urllib), then gh CLI fallback.
    """

    def __init__(self, method: str, token: Optional[str] = None):
        self._method = method  # "token" or "gh"
        self._token = token

    def get_json(self, api_path: str) -> Optional[Any]:
        """GET a GitHub API endpoint, return parsed JSON or None on error."""
        if self._method == "token":
            return self._get_via_token(api_path)
        return self._get_via_gh(api_path)

    def _get_via_token(self, api_path: str) -> Optional[Any]:
        import urllib.error
        import urllib.request

        url = f"https://api.github.com/{api_path}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "pio-lock",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return None

    def _get_via_gh(self, api_path: str) -> Optional[Any]:
        try:
            result = subprocess.run(
                ["gh", "api", api_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return None


def _create_github_client() -> Optional[GitHubClient]:
    """Create a GitHubClient using the best available method.

    Priority: GITHUB_TOKEN env var → gh CLI → None.
    """
    import os
    import shutil

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return GitHubClient("token", token)

    if shutil.which("gh"):
        return GitHubClient("gh")

    return None


def _check_git_dep(
    spec_str: str,
    name: str,
    current_version: str,
    github: GitHubClient,
) -> Optional[dict[str, Any]]:
    """Check a single git dep for updates via GitHub API.

    Returns a result dict or None if the dep can't be checked.
    """
    # Extract URL — strip git+ prefix if present
    url = spec_str.split("#")[0].rstrip()
    if url.startswith("git+"):
        url = url[4:]

    parsed = _parse_github_url(url + ("#" + spec_str.split("#")[1] if "#" in spec_str else ""))
    if not parsed:
        return None

    owner, repo, ref = parsed
    ref_type = _classify_git_ref(ref)

    if ref_type == "sha":
        assert ref is not None
        return _check_sha_dep(owner, repo, ref, name, github)
    elif ref_type == "tag":
        assert ref is not None
        return _check_tag_dep(owner, repo, ref, name, github)
    # branch and default — PIO already handles these via git ls-remote
    return None


def _check_sha_dep(
    owner: str, repo: str, sha: str, name: str, github: GitHubClient
) -> Optional[dict[str, Any]]:
    """Check a SHA-pinned dep: find which branch it's on, check for newer commits."""
    short_sha = sha[:7]

    # Find branches where this SHA is the HEAD
    branches = github.get_json(f"repos/{owner}/{repo}/commits/{sha}/branches-where-head")

    if branches and isinstance(branches, list) and len(branches) > 0:
        # SHA is HEAD of at least one branch — it's up to date on those branches
        branch_names = [b["name"] for b in branches]
        best = next(
            (b for b in branch_names if b in _HIGH_CONFIDENCE_BRANCHES),
            branch_names[0],
        )
        confidence = "high" if best in _HIGH_CONFIDENCE_BRANCHES else "medium"
        return {
            "name": name,
            "ref": short_sha,
            "ref_type": "sha",
            "status": "up_to_date",
            "branch": best,
            "confidence": confidence,
            "message": f"up to date on {best}",
        }

    # SHA is not HEAD of any branch — compare against default branch
    compare = github.get_json(f"repos/{owner}/{repo}/compare/{sha}...HEAD")
    if not compare:
        return None

    ahead = compare.get("ahead_by", 0)
    if ahead == 0:
        return {
            "name": name,
            "ref": short_sha,
            "ref_type": "sha",
            "status": "up_to_date",
            "branch": "HEAD",
            "confidence": "high",
            "message": "up to date",
        }

    # Find the default branch name
    default_branch = "HEAD"
    # The compare endpoint doesn't tell us the branch name when using HEAD,
    # but we can get it from the repo info
    repo_info = github.get_json(f"repos/{owner}/{repo}")
    if repo_info:
        default_branch = repo_info.get("default_branch", "HEAD")

    confidence = "high" if default_branch in _HIGH_CONFIDENCE_BRANCHES else "medium"
    new_sha = compare.get("commits", [{}])[-1].get("sha", "")[:7] if compare.get("commits") else ""

    return {
        "name": name,
        "ref": short_sha,
        "ref_type": "sha",
        "status": "outdated",
        "branch": default_branch,
        "confidence": confidence,
        "ahead_by": ahead,
        "latest_sha": new_sha,
        "message": f"{ahead} commit{'s' if ahead != 1 else ''} behind {default_branch}",
    }


def _parse_version_tuple(tag: str) -> Optional[tuple[int, ...]]:
    """Parse a version tag like 'v2.0.0' or '4.2.1' into a comparable tuple."""
    match = re.match(r"^v?(\d+(?:\.\d+)*)$", tag)
    if not match:
        return None
    return tuple(int(x) for x in match.group(1).split("."))


def _check_tag_dep(
    owner: str, repo: str, tag: str, name: str, github: GitHubClient
) -> Optional[dict[str, Any]]:
    """Check a tag-pinned dep: find newer tags with the same naming convention."""
    current_ver = _parse_version_tuple(tag)
    if current_ver is None:
        return None

    has_v_prefix = tag.startswith("v")

    # Fetch tags (first page, up to 100)
    tags = github.get_json(f"repos/{owner}/{repo}/tags?per_page=100")
    if not tags or not isinstance(tags, list):
        return None

    # Find newer tags with matching format
    newer = []
    for t in tags:
        tag_name = t["name"]
        ver = _parse_version_tuple(tag_name)
        if ver is None:
            continue
        # Must match prefix convention
        if has_v_prefix != tag_name.startswith("v"):
            continue
        if ver > current_ver:
            newer.append((ver, tag_name))

    if not newer:
        return {
            "name": name,
            "ref": tag,
            "ref_type": "tag",
            "status": "up_to_date",
            "message": "latest tag",
        }

    newer.sort(reverse=True)
    latest_tag = newer[0][1]

    return {
        "name": name,
        "ref": tag,
        "ref_type": "tag",
        "status": "outdated",
        "latest_tag": latest_tag,
        "message": f"{tag} → {latest_tag} available",
    }


def _check_git_deps(entries: list[dict[str, Any]], github: GitHubClient) -> list[dict[str, Any]]:
    """Check all git deps for updates via GitHub API."""
    results = []
    seen = set()
    for entry in entries:
        if entry["type"] != "git":
            continue
        name = entry["name"]
        if name in seen:
            continue
        seen.add(name)

        result = _check_git_dep(entry["spec_str"], name, entry["current"], github)
        if result:
            results.append(result)
    return results


def _check_platform(
    project_dir: Path, env_name: str, github: GitHubClient
) -> Optional[dict[str, Any]]:
    """Check if a newer platform release is available on GitHub."""
    platform_url = get_platform_url(project_dir, env_name)
    if platform_url == "unknown":
        return None

    parsed = _parse_platform_release_url(platform_url)
    if not parsed:
        return None

    owner, repo, current_version = parsed
    current_ver = _parse_version_tuple(current_version)
    if current_ver is None:
        return None

    releases = github.get_json(f"repos/{owner}/{repo}/releases?per_page=50")
    if not releases or not isinstance(releases, list):
        return None

    # Find newer releases matching the same major version prefix
    newer = []
    for rel in releases:
        tag = rel.get("tag_name", "")
        if rel.get("draft") or rel.get("prerelease"):
            continue
        ver = _parse_version_tuple(tag)
        if ver is None:
            continue
        # Match same major version prefix (e.g. 55.x.y)
        if ver and current_ver and ver[0] == current_ver[0] and ver > current_ver:
            newer.append((ver, tag))

    if not newer:
        return {
            "name": repo,
            "current": current_version,
            "status": "up_to_date",
            "message": "latest release",
        }

    newer.sort(reverse=True)
    latest_tag = newer[0][1]

    return {
        "name": repo,
        "current": current_version,
        "status": "outdated",
        "latest": latest_tag,
        "message": f"{current_version} → {latest_tag} available",
    }


# ── Outdated / update helpers ────────────────────────────────────────────────


def _get_outdated_entries(
    project_dir: Path,
    envs: list[str],
    lib_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Check all deps across envs for available updates using PIO's API."""
    lib_pkg_mgr_cls, pkg_spec_cls, proj_config_cls = _pio_import_fn()

    config = proj_config_cls.get_instance(str(project_dir / "platformio.ini"))
    entries: list[dict[str, Any]] = []

    for env_name in envs:
        lib_deps = config.get(f"env:{env_name}", "lib_deps", [])
        libdeps_dir = config.get(f"env:{env_name}", "libdeps_dir", None)
        if libdeps_dir:
            pkg_dir = Path(libdeps_dir) / env_name
        else:
            pkg_dir = project_dir / ".pio" / "libdeps" / env_name

        pm = lib_pkg_mgr_cls(str(pkg_dir))

        for dep_str in lib_deps:
            spec = pkg_spec_cls(dep_str)

            # Skip local/symlinked deps
            if spec.symlink:
                continue

            if lib_filter and lib_filter.lower() not in spec.name.lower():
                continue

            pkg = pm.get_package(spec)
            if pkg is None:
                continue

            result = pm.outdated(pkg, spec)
            name = pkg.metadata.name

            dep_type = "git" if spec.external else "registry"

            entry: dict[str, Any] = {
                "env": env_name,
                "name": name,
                "current": str(result.current),
                "wanted": str(result.wanted) if result.wanted else None,
                "latest": str(result.latest) if result.latest else None,
                "type": dep_type,
                "spec_str": dep_str,
                "is_outdated": result.is_outdated(allow_incompatible=True),
                "detached": result.detached,
            }
            entries.append(entry)

    return entries


def outdated(
    project_dir: Path,
    envs: list[str],
    output_json: bool = False,
) -> int:
    """Check for outdated dependencies. Returns 0 if up-to-date, 1 if updates available."""
    if not (project_dir / "platformio.ini").exists():
        print(f"Error: no platformio.ini in {project_dir}", file=sys.stderr)
        return 1

    entries = _get_outdated_entries(project_dir, envs)

    # GitHub-aware checks for git deps and platform
    github = _create_github_client_fn()
    git_results: list[dict[str, Any]] = []
    platform_result: Optional[dict[str, Any]] = None
    github_skipped_reason: Optional[str] = None

    if github:
        git_results = _check_git_deps(entries, github)
        platform_result = _check_platform(project_dir, envs[0], github)
    else:
        github_skipped_reason = (
            "no GITHUB_TOKEN set and gh CLI not found. "
            "Set GITHUB_TOKEN or install gh for git dependency update detection."
        )

    has_outdated = any(e["is_outdated"] for e in entries)
    has_git_outdated = any(r["status"] == "outdated" for r in git_results)
    has_platform_outdated = platform_result is not None and platform_result["status"] == "outdated"

    if output_json:
        data: dict[str, Any] = {
            "libraries": entries,
            "git_deps": git_results,
            "platform": platform_result,
        }
        if github_skipped_reason:
            data["github_skipped"] = github_skipped_reason
        print(json.dumps(data, indent=2))
        return 1 if (has_outdated or has_git_outdated or has_platform_outdated) else 0

    # Table output — registry and PIO-managed deps
    registry_entries = [e for e in entries if e["type"] == "registry"]
    if registry_entries:
        header = f"{'Library':<40} {'Current':<12} {'Wanted':<12} {'Latest':<12}"
        print(header)
        print("-" * len(header))

        for entry in registry_entries:
            if entry["detached"]:
                print(f"  {entry['name']:<38} (pinned — skipped)")
                continue

            marker = " *" if entry["is_outdated"] else "  "
            current = entry["current"]
            wanted = entry["wanted"] or "-"
            latest = entry["latest"] or "-"
            print(f"{marker}{entry['name']:<38} {current:<12} {wanted:<12} {latest:<12}")

    # Git dependencies section
    git_entries_from_pio = [e for e in entries if e["type"] == "git"]
    if git_entries_from_pio:
        print(f"\n{'Git dependencies'}")
        print("-" * 76)

        # Build a lookup from name → GitHub check result
        gh_by_name = {r["name"]: r for r in git_results}

        for entry in git_entries_from_pio:
            name = entry["name"]
            gh = gh_by_name.get(name)

            if gh:
                marker = " *" if gh["status"] == "outdated" else "  "
                ref = gh["ref"]
                msg = gh["message"]
                confidence = gh.get("confidence", "")
                conf_str = f" [{confidence}]" if confidence else ""
                print(f"{marker}{name:<38} {ref:<12} {msg}{conf_str}")
            else:
                # No GitHub result — show PIO info
                current = entry["current"][:20]
                print(f"  {name:<38} {current}")

    # Platform section
    if platform_result:
        print(f"\n{'Platform'}")
        print("-" * 76)
        marker = " *" if platform_result["status"] == "outdated" else "  "
        print(f"{marker}{platform_result['name']:<38} {platform_result['message']}")

    if github_skipped_reason:
        print(f"\nNote: GitHub checks skipped — {github_skipped_reason}")

    if has_outdated or has_git_outdated or has_platform_outdated:
        print("\n* = update available")
        return 1
    else:
        print("\nAll dependencies are up to date.")
        return 0


class ConfigSourceTracker:
    """Track which config file each option value comes from.

    PlatformIO's ProjectConfig merges all extra_configs into a flat
    configparser dict, discarding source file information. This class
    independently parses each file to build a source map.

    Works with any config object that has a ``_parsed`` attribute
    (list of file paths that were read, in order).
    """

    def __init__(self, config: Any, fallback_path: Optional[Path] = None):
        self._files: list[str] = getattr(config, "_parsed", [])
        if not self._files and fallback_path:
            self._files = [str(fallback_path)]
        # (section, option) -> filepath — last writer wins (matches configparser)
        self._source_map: dict[tuple[str, str], str] = {}
        self._build_source_map()

    def _build_source_map(self) -> None:
        for filepath in self._files:
            parser = configparser.ConfigParser()
            try:
                parser.read(filepath, encoding="utf-8")
            except configparser.Error:
                continue
            for section in parser.sections():
                for option in parser.options(section):
                    self._source_map[(section, option)] = filepath

    def get_source(self, section: str, option: str) -> Optional[Path]:
        """Return the file that defines this (section, option) pair."""
        filepath = self._source_map.get((section, option))
        return Path(filepath) if filepath else None

    def find_file_for_value(self, value: str) -> Optional[Path]:
        """Search config files for a string (e.g. a lib_deps spec).

        For multi-value options like lib_deps, individual entries may be
        on separate lines within a section. This does a text search across
        all config files, checking the last file first (since it wins on
        conflicts).
        """
        # Search in reverse order — last file wins for configparser
        for filepath in reversed(self._files):
            path = Path(filepath)
            if not path.is_file():
                continue
            if value in path.read_text():
                return path
        return None

    @property
    def files(self) -> list[Path]:
        """All config files that were parsed, in load order."""
        return [Path(f) for f in self._files]


def _build_updated_spec(spec_str: str, new_version: str) -> Optional[str]:
    """Build an updated spec string preserving the range prefix.

    E.g. "acme/Foo @ ^1.0.0" + "1.2.0" -> "acme/Foo @ ^1.2.0"
    Returns None if the spec can't be parsed.
    """
    if " @ " not in spec_str:
        return None

    prefix, version_part = spec_str.rsplit(" @ ", 1)

    # Extract range prefix (^, ~, >=, etc.)
    match = re.match(r"^([~^>=<]+)?(.+)$", version_part)
    if not match:
        return None

    range_prefix = match.group(1) or ""
    return f"{prefix} @ {range_prefix}{new_version}"


def update(
    project_dir: Path,
    envs: list[str],
    dry_run: bool = True,
    lib_filter: Optional[str] = None,
) -> int:
    """Update config files with newer dependency versions.

    Searches platformio.ini and all extra_configs files to find where
    each lib_deps entry is declared, and updates it in the correct file.
    """
    if not (project_dir / "platformio.ini").exists():
        print(f"Error: no platformio.ini in {project_dir}", file=sys.stderr)
        return 1

    _pm_cls, _spec_cls, proj_config_cls = _pio_import_fn()
    config = proj_config_cls.get_instance(str(project_dir / "platformio.ini"))
    tracker = ConfigSourceTracker(config, fallback_path=project_dir / "platformio.ini")

    entries = _get_outdated_entries(project_dir, envs, lib_filter=lib_filter)
    outdated_entries = [e for e in entries if e["is_outdated"]]

    if not outdated_entries:
        print("All dependencies are up to date.")
        return 0

    # Build replacements, locating each spec in the correct config file
    # replacements: {file_path: [(old_spec, new_spec), ...]}
    replacements: dict[Path, list[tuple[str, str]]] = {}
    for entry in outdated_entries:
        wanted = entry["wanted"] or entry["latest"]
        if not wanted:
            continue
        new_spec = _build_updated_spec(entry["spec_str"], wanted)
        if not new_spec:
            continue

        source_file = tracker.find_file_for_value(entry["spec_str"])
        if source_file is None:
            print(
                f"  Warning: could not locate {entry['spec_str']!r} in any config file",
                file=sys.stderr,
            )
            continue

        print(f"  {entry['name']}: {entry['current']} -> {wanted}")
        print(f"    {entry['spec_str']}  =>  {new_spec}")
        print(f"    in {source_file}")

        if source_file not in replacements:
            replacements[source_file] = []
        replacements[source_file].append((entry["spec_str"], new_spec))

    if not replacements:
        print("No updatable specs found in config files.")
        return 0

    if dry_run:
        print("\nDry run — no files modified.")
        return 0

    # Apply replacements to each config file
    for filepath, specs in replacements.items():
        content = filepath.read_text()

        # Create backup alongside the original
        backup_path = filepath.with_suffix(filepath.suffix + ".bak")
        backup_path.write_text(content)
        print(f"\nBackup: {backup_path}")

        for old_spec, new_spec in specs:
            content = content.replace(old_spec, new_spec)

        filepath.write_text(content)
        print(f"Updated: {filepath}")

    print("\nRun `pio pkg install` then `pio-lock capture` to lock the new versions.")
    return 0


# ── PlatformIO builder integration ───────────────────────────────────────────


def register_pio_targets(env: Any) -> None:
    """Register custom PIO targets for lockfile and snapshot management.

    Called from main.py during SCons environment setup.
    Provides targets: lock-capture, lock-check, lock-restore, snapshot-*
    Also auto-manages build snapshots on every build.
    """
    project_dir = Path(env.subst("$PROJECT_DIR"))

    # Collect environments from the PIO config
    try:
        config = env.GetProjectConfig()
        envs = config.envs()
    except Exception:
        envs = [env.subst("$PIOENV")]

    def _make_action(fn: Callable[..., int]) -> Callable[..., None]:
        def action(*_args: Any, **_kwargs: Any) -> None:
            rc = fn()
            if rc != 0:
                env.Exit(rc)

        return action

    targets = [
        (
            "lock-capture",
            lambda: capture(project_dir, envs),
            "Lock Capture",
            "Capture dependency versions into pio.lock.json",
        ),
        (
            "lock-check",
            lambda: check(project_dir, envs),
            "Lock Check",
            "Verify installed deps match pio.lock.json",
        ),
        (
            "lock-restore",
            lambda: restore(project_dir, envs),
            "Lock Restore",
            "Install exact versions from pio.lock.json",
        ),
        (
            "snapshot-capture",
            lambda: snapshot_capture(project_dir),
            "Snapshot Capture",
            "Generate build_snapshot.json from current HEAD",
        ),
        (
            "snapshot-check",
            lambda: snapshot_check(project_dir),
            "Snapshot Check",
            "Verify build_snapshot.json matches HEAD",
        ),
        (
            "snapshot-clear",
            lambda: snapshot_clear(project_dir),
            "Snapshot Clear",
            "Delete build_snapshot.json",
        ),
        (
            "snapshot-print",
            lambda: snapshot_print(project_dir),
            "Snapshot Print",
            "Display build_snapshot.json contents",
        ),
    ]

    for name, fn, title, description in targets:
        env.AddPlatformTarget(
            name,
            None,
            env.VerboseAction(_make_action(fn), description),
            title,
        )

    # Auto-manage snapshot on every build
    snapshot_auto_manage(project_dir, env)
