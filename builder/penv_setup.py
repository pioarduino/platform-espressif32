# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import re
import semantic_version
import shutil
import site
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from platformio.package.version import pepver_to_semver
from platformio.compat import IS_WINDOWS

GDB_TOOL_PACKAGES = {
    "xtensa": "tool-xtensa-esp-elf-gdb",
    "riscv": "tool-riscv32-esp-elf-gdb",
}

# Check Python version requirement
if sys.version_info < (3, 10):
    sys.stderr.write(
        f"Error: Python 3.10 or higher is required. "
        f"Current version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
        f"Please update your Python installation.\n"
    )
    sys.exit(1)

github_actions = bool(os.getenv("GITHUB_ACTIONS"))

PLATFORMIO_URL_VERSION_RE = re.compile(
    r'/v?(\d+\.\d+\.\d+(?:[.-](?:alpha|beta|rc|dev|post|pre)\d*)?(?:\.\d+)?)(?:\.(?:zip|tar\.gz|tar\.bz2))?$',
    re.IGNORECASE,
)

# Python dependencies required for ESP32 platform builds
python_deps = {
    "pioarduino": ">=6.1.19",
    "littlefs-python": ">=0.16.0",
    "fatfs-ng": ">=0.1.14",
    "pyyaml": ">=6.0.2",
    "rich-click": ">=1.8.6",
    "zopfli": ">=0.2.2",
    "intelhex": ">=2.3.0",
    "rich": ">=14.0.0",
    "cryptography": ">=45.0.3",
    "certifi": ">=2025.8.3",
    "ecdsa": ">=0.19.1",
    "bitstring": ">=4.3.1",
    "reedsolo": ">=1.5.3,<1.8",
    "esp-idf-size": ">=2.0.0",
    "esp-coredump": ">=1.14.0",
    "pyelftools": ">=0.32"
}


def has_internet_connection(timeout=5):
    """
    Checks practical internet reachability for dependency installation.
    Can be overridden by setting PLATFORMIO_OFFLINE=1 environment variable.
    1) If HTTPS/HTTP proxy environment variable is set, test TCP connectivity to the proxy endpoint.
    2) Otherwise, test direct TCP connectivity to common HTTPS endpoints (port 443).
    
    Args:
        timeout (int): Timeout duration in seconds for the connection test.

    Returns:
        True if at least one path appears reachable; otherwise False.
    """
    # Check if offline mode is forced via environment variable
    if os.getenv("PLATFORMIO_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
        return False

    # 1) Test TCP connectivity to the proxy endpoint.
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    if proxy:
        try:
            u = urlparse(proxy if "://" in proxy else f"http://{proxy}")
            host = u.hostname
            port = u.port or (443 if u.scheme == "https" else 80)
            if host and port:
                socket.create_connection((host, port), timeout=timeout).close()
                return True
        except Exception:
            # If proxy connection fails, fall back to direct connection test
            pass

    # 2) Test direct TCP connectivity to common HTTPS endpoints (port 443).
    https_hosts = ("pypi.org", "files.pythonhosted.org", "github.com")
    for host in https_hosts:
        try:
            socket.create_connection((host, 443), timeout=timeout).close()
            return True
        except Exception:
            continue

    # Direct DNS:53 connection is abolished due to many false positives on enterprise networks
    # (add it at the end if necessary)
    return False


has_network = has_internet_connection() or github_actions


def get_executable_path(penv_dir, executable_name):
    """
    Get the path to an executable based on the penv_dir.
    """
    exe_suffix = ".exe" if IS_WINDOWS else ""
    scripts_dir = "Scripts" if IS_WINDOWS else "bin"
    
    return str(Path(penv_dir) / scripts_dir / f"{executable_name}{exe_suffix}")


def _get_penv_python_version(penv_dir):
    """
    Detect the Python version used to create an existing penv.

    Reads the ``version`` key from ``pyvenv.cfg`` which is always
    written by both ``python -m venv`` and ``uv venv``.  This avoids
    spawning a subprocess (which can fail when the penv Python is
    corrupted) and works identically on all platforms.

    Falls back to inspecting ``lib/pythonX.Y/`` directories on POSIX
    if ``pyvenv.cfg`` is missing or unparseable.

    Returns:
        tuple[int, int] | None: (major, minor) of the penv Python, or
        None if the penv does not exist or its version cannot be
        determined.
    """
    penv_path = Path(penv_dir)

    # Primary: parse pyvenv.cfg (cross-platform, no subprocess)
    cfg_file = penv_path / "pyvenv.cfg"
    if cfg_file.is_file():
        try:
            for line in cfg_file.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip().lower() == "version":
                    parts = value.strip().split(".")
                    if len(parts) >= 2:
                        return (int(parts[0]), int(parts[1]))
        except Exception:
            pass

    # Fallback (POSIX only): inspect lib/pythonX.Y/ directories
    if not IS_WINDOWS:
        lib_dir = penv_path / "lib"
        if lib_dir.is_dir():
            for entry in sorted(lib_dir.iterdir(), reverse=True):
                if entry.is_dir() and entry.name.startswith("python") and (entry / "site-packages").is_dir():
                    ver_str = entry.name[len("python"):]
                    try:
                        major, minor = ver_str.split(".")
                        return (int(major), int(minor))
                    except (ValueError, TypeError):
                        continue

    return None


def _penv_version_matches(penv_dir):
    """
    Check whether the existing penv was created with the same Python
    major.minor version as the currently running interpreter.

    Returns True if versions match or if the penv does not exist yet.
    """
    penv_ver = _get_penv_python_version(penv_dir)
    if penv_ver is None:
        return True  # no penv yet — nothing to mismatch
    return penv_ver == (sys.version_info.major, sys.version_info.minor)


def _get_penv_site_packages(penv_dir):
    """
    Locate the actual site-packages directory inside a penv.

    Instead of constructing the path from ``sys.version_info`` (which
    reflects the *host* interpreter and may differ from the penv's
    Python version), this function inspects the penv's directory
    structure and returns the first valid site-packages path found.

    Returns:
        str | None: Absolute path to the site-packages directory, or
        None if it cannot be found.
    """
    penv_path = Path(penv_dir)

    # Windows: Lib/site-packages (no version directory)
    if IS_WINDOWS:
        sp = penv_path / "Lib" / "site-packages"
        if sp.is_dir():
            return str(sp)
        return None

    # POSIX: lib/pythonX.Y/site-packages
    lib_dir = penv_path / "lib"
    if not lib_dir.is_dir():
        return None
    # Prefer the newest python version directory
    for entry in sorted(lib_dir.iterdir(), key=lambda e: tuple(int(x) for x in e.name[6:].split('.') if x.isdigit()), reverse=True):
        if entry.is_dir() and entry.name.startswith("python"):
            sp = entry / "site-packages"
            if sp.is_dir():
                return str(sp)
    return None


def setup_pipenv_in_package(env, penv_dir):
    """
    Checks if 'penv' folder exists in platformio dir and creates virtual environment if not.
    Recreates the penv if the Python version does not match the running interpreter.
    First tries to create with uv, falls back to python -m venv if uv is not available.
    
    Returns:
        str or None: Path to uv executable if uv was used, None if python -m venv was used
    """
    # Recreate penv when Python version changed (e.g. Homebrew upgraded 3.13→3.14)
    penv_python_path = get_executable_path(penv_dir, "python")
    if os.path.isfile(penv_python_path) and not _penv_version_matches(penv_dir):
        penv_ver = _get_penv_python_version(penv_dir)
        current_ver = (sys.version_info.major, sys.version_info.minor)
        print(
            f"Python version mismatch: penv has {penv_ver[0]}.{penv_ver[1]}, "
            f"current interpreter is {current_ver[0]}.{current_ver[1]}. "
            f"Recreating penv..."
        )
        shutil.rmtree(penv_dir, ignore_errors=True)

    if not os.path.isfile(get_executable_path(penv_dir, "python")):
        # Attempt virtual environment creation using uv package manager
        uv_success = False
        uv_cmd = None
        try:
            # Derive uv path from PYTHONEXE path
            python_exe = env.subst("$PYTHONEXE")
            python_dir = os.path.dirname(python_exe)
            uv_exe_suffix = ".exe" if IS_WINDOWS else ""
            uv_cmd = str(Path(python_dir) / f"uv{uv_exe_suffix}")
            
            # Fall back to system uv if derived path doesn't exist
            if not os.path.isfile(uv_cmd):
                uv_cmd = "uv"
                
            subprocess.check_call(
                [uv_cmd, "venv", "--clear", f"--python={python_exe}", penv_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90
            )
            uv_success = True
            print(f"Created pioarduino Python virtual environment using uv: {penv_dir}")

        except Exception:
            pass
        
        # Fallback to python -m venv if uv failed or is not available
        if not uv_success:
            uv_cmd = None
            env.Execute(
                env.VerboseAction(
                    '"$PYTHONEXE" -m venv --clear "%s"' % penv_dir,
                    "Created pioarduino Python virtual environment: %s" % penv_dir,
                )
            )
        
        # Validate virtual environment creation
        # Ensure Python executable is available
        penv_python = get_executable_path(penv_dir, "python")
        if not os.path.isfile(penv_python):
            sys.stderr.write(
                f"Error: Failed to create a proper virtual environment. "
                f"Missing the `python` binary at {penv_python}! Created with uv: {uv_success}\n"
            )
            sys.exit(1)

        return uv_cmd if uv_success else None
    
    return None


def setup_python_paths(penv_dir):
    """Setup Python module search paths using the penv_dir.

    Dynamically locates the penv's site-packages directory instead of
    deriving it from ``sys.version_info``, which reflects the *host*
    interpreter and may differ from the Python version used to create
    the penv.  The penv's site-packages is inserted at the front of
    ``sys.path`` and conflicting system site-packages entries are
    removed so that packages installed in the penv always take
    precedence.
    """
    site_packages = _get_penv_site_packages(penv_dir)
    if not site_packages:
        return

    penv_dir_resolved = os.path.realpath(penv_dir) + os.sep

    # Remove system site-packages entries that are not part of the penv
    sys.path[:] = [
        p for p in sys.path
        if "site-packages" not in p.lower()
        or os.path.realpath(p).startswith(penv_dir_resolved)
    ]

    # Add penv site-packages at the beginning
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)

    site.addsitedir(site_packages)
    # Re-ensure penv is still first after addsitedir may have appended it
    if sys.path[0] != site_packages:
        sys.path.remove(site_packages)
        sys.path.insert(0, site_packages)


def get_packages_to_install(deps, installed_packages):
    """
    Generator for Python packages that need to be installed.
    Compares package names case-insensitively.
    
    Args:
        deps (dict): Dictionary of package names and version specifications
        installed_packages (dict): Dictionary of currently installed packages (keys should be lowercase)
        
    Yields:
        str: Package name that needs to be installed
    """
    for package, spec in deps.items():
        name = package.lower()
        if name not in installed_packages:
            yield package
        elif name == "platformio":
            # Enforce the version from the direct URL if it looks like one.
            # If version can't be parsed, fall back to accepting any installed version.
            m = PLATFORMIO_URL_VERSION_RE.search(spec)
            if m:
                expected_ver = pepver_to_semver(m.group(1))
                if installed_packages.get(name) != expected_ver:
                    # Reinstall to align with the pinned URL version
                    yield package
            else:
                continue
        else:
            version_spec = semantic_version.SimpleSpec(spec)
            if not version_spec.match(installed_packages[name]):
                yield package


def install_python_deps(python_exe, external_uv_executable, uv_cache_dir=None):
    """
    Ensure uv package manager is available in penv and install required Python dependencies.
    
    Args:
        python_exe: Path to Python executable in the penv
        external_uv_executable: Path to external uv executable used to create the penv (can be None)
        uv_cache_dir: Optional path to uv cache directory
    
    Returns:
        bool: True if successful, False otherwise
    """
    # Get the penv directory to locate uv within it
    penv_dir = os.path.dirname(os.path.dirname(python_exe))
    penv_uv_executable = get_executable_path(penv_dir, "uv")

    # Build subprocess environment with UV_CACHE_DIR if specified
    uv_env = None
    if uv_cache_dir:
        uv_env = dict(os.environ)
        uv_env["UV_CACHE_DIR"] = str(uv_cache_dir)
    
    # Check if uv is available in the penv
    uv_in_penv_available = False
    try:
        result = subprocess.run(
            [penv_uv_executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        uv_in_penv_available = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        uv_in_penv_available = False
    
    # Install uv into penv if not available
    if not uv_in_penv_available:
        if external_uv_executable:
            # Try external uv first to install uv into the penv
            try:
                subprocess.check_call(
                    [external_uv_executable, "pip", "install", "uv>=0.1.0", f"--python={python_exe}", "--quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                    env=uv_env
                )
                uv_in_penv_available = True
            except Exception:
                print("Warning: uv installation via external uv failed, falling back to pip")

        if not uv_in_penv_available:
            # Fallback to pip to install uv into penv
            # uv-created venvs don't include pip, so ensure it's available first
            try:
                subprocess.run(
                    [python_exe, "-m", "ensurepip", "--default-pip"],
                    capture_output=True, timeout=60
                )
            except Exception:
                pass
            try:
                subprocess.check_call(
                    [python_exe, "-m", "pip", "install", "uv>=0.1.0", "--quiet", "--no-cache-dir"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    timeout=300
                )
            except subprocess.CalledProcessError as e:
                print(f"Error: uv installation via pip failed with exit code {e.returncode}")
                return False
            except subprocess.TimeoutExpired:
                print("Error: uv installation via pip timed out")
                return False
            except FileNotFoundError:
                print("Error: Python executable not found")
                return False
            except Exception as e:
                print(f"Error installing uv package manager via pip: {e}")
                return False

    
    def _get_installed_uv_packages():
        """
        Get list of installed packages in virtual env 'penv' using uv.
        
        Returns:
            dict: Dictionary of installed packages with versions
        """
        result = {}
        try:
            cmd = [penv_uv_executable, "pip", "list", f"--python={python_exe}", "--format=json"]
            result_obj = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=300,
                env=uv_env
            )
            
            if result_obj.returncode == 0:
                content = result_obj.stdout.strip()
                if content:
                    packages = json.loads(content)
                    for p in packages:
                        result[p["name"].lower()] = pepver_to_semver(p["version"])
            else:
                print(f"Warning: uv pip list failed with exit code {result_obj.returncode}")
                if result_obj.stderr:
                    print(f"Error output: {result_obj.stderr.strip()}")
                
        except subprocess.TimeoutExpired:
            print("Warning: uv pip list command timed out")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not parse package list: {e}")
        except FileNotFoundError:
            print("Warning: uv command not found")
        except Exception as e:
            print(f"Warning! Couldn't extract the list of installed Python packages: {e}")

        return result

    installed_packages = _get_installed_uv_packages()
    packages_to_install = list(get_packages_to_install(python_deps, installed_packages))
    
    if packages_to_install:
        packages_list = []
        for p in packages_to_install:
            spec = python_deps[p]
            if spec.startswith(('http://', 'https://', 'git+', 'file://')):
                packages_list.append(spec)
            else:
                packages_list.append(f"{p}{spec}")
        
        cmd = [
            penv_uv_executable, "pip", "install",
            f"--python={python_exe}",
            "--quiet", "--upgrade"
        ] + packages_list
        
        try:
            subprocess.check_call(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                timeout=300,
                env=uv_env
            )
                
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to install Python dependencies (exit code: {e.returncode})")
            return False
        except subprocess.TimeoutExpired:
            print("Error: Python dependencies installation timed out")
            return False
        except FileNotFoundError:
            print("Error: uv command not found")
            return False
        except Exception as e:
            print(f"Error installing Python dependencies: {e}")
            return False
    
    return True


def install_esptool(env, platform, python_exe, uv_executable, uv_cache_dir=None):
    """
    Install esptool from package folder "tool-esptoolpy" using uv package manager.
    Ensures esptool is installed from the specific tool-esptoolpy package directory.
    
    Args:
        env: SCons environment object
        platform: PlatformIO platform object  
        python_exe (str): Path to Python executable in virtual environment
        uv_executable (str): Path to uv executable
        uv_cache_dir: Optional path to uv cache directory
    
    Raises:
        SystemExit: If esptool installation fails or package directory not found
    """
    esptool_repo_path = platform.get_package_dir("tool-esptoolpy") or ""
    if not esptool_repo_path or not os.path.isdir(esptool_repo_path):
        sys.stderr.write(
            f"Error: 'tool-esptoolpy' package directory not found: {esptool_repo_path!r}\n"
        )
        sys.exit(1)

    # Build subprocess environment with UV_CACHE_DIR if specified
    uv_env = None
    if uv_cache_dir:
        uv_env = dict(os.environ)
        uv_env["UV_CACHE_DIR"] = str(uv_cache_dir)

    # Check if esptool is already installed from the correct path
    try:
        result = subprocess.run(
            [
                python_exe,
                "-c",
                (
                    "import esptool, os, sys; "
                    "expected_path = os.path.normcase(os.path.realpath(sys.argv[1])); "
                    "actual_path = os.path.normcase(os.path.realpath(os.path.dirname(esptool.__file__))); "
                    "print('MATCH' if actual_path.startswith(expected_path) else 'MISMATCH')"
                ),
                esptool_repo_path,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip() == "MATCH":
            return
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        subprocess.check_call([
            uv_executable, "pip", "install", "--quiet", "--force-reinstall",
            f"--python={python_exe}",
            "-e", esptool_repo_path
        ], timeout=60, env=uv_env)

    except subprocess.CalledProcessError as e:
        sys.stderr.write(
            f"Error: Failed to install esptool from {esptool_repo_path} (exit {e.returncode})\n"
        )
        sys.exit(1)


def setup_penv_minimal(platform, platformio_dir: str, install_esptool: bool = True):
    """
    Minimal Python virtual environment setup without SCons dependencies.
    
    Args:
        platform: PlatformIO platform object
        platformio_dir (str): Path to PlatformIO core directory
        install_esptool (bool): Whether to install esptool (default: True)
    
    Returns:
        tuple[str, str]: (Path to penv Python executable, Path to esptool script)
        
    Raises:
        SystemExit: If Python version < 3.10 or dependency installation fails
    """
    return _setup_python_environment_core(None, platform, platformio_dir, should_install_esptool=install_esptool)


def _setup_python_environment_core(env, platform, platformio_dir, should_install_esptool=True):
    """
    Core Python environment setup logic shared by both SCons and minimal versions.
    
    Args:
        env: SCons environment object (None for minimal setup)
        platform: PlatformIO platform object
        platformio_dir (str): Path to PlatformIO core directory
        should_install_esptool (bool): Whether to install esptool (default: True)
    
    Returns:
        tuple[str, str]: (Path to penv Python executable, Path to esptool script)
    """
    penv_dir = str(Path(platformio_dir) / "penv")

    # Determine uv cache directory inside .platformio/.cache
    uv_cache_dir = str(Path(platformio_dir) / ".cache" / "uv")
    
    # Create virtual environment if not present
    if env is not None:
        # SCons version
        used_uv_executable = setup_pipenv_in_package(env, penv_dir)
    else:
        # Minimal version
        used_uv_executable = _setup_pipenv_minimal(penv_dir)
    
    # Set Python executable path
    penv_python = get_executable_path(penv_dir, "python")
    
    # Update SCons environment if available
    if env is not None:
        env.Replace(PYTHONEXE=penv_python)
    
    # check for python binary, exit with error when not found
    if not os.path.isfile(penv_python):
        sys.stderr.write(f"Error: Python executable not found: {penv_python}\n")
        sys.exit(1)
    
    # Setup Python module search paths
    setup_python_paths(penv_dir)
    
    # Set executable paths from tools
    esptool_binary_path = get_executable_path(penv_dir, "esptool")
    uv_executable = get_executable_path(penv_dir, "uv")

    # Install required Python dependencies for ESP32 platform
    if has_network:
        if not install_python_deps(penv_python, used_uv_executable, uv_cache_dir):
            sys.stderr.write("Error: Failed to install Python dependencies into penv\n")
            sys.exit(1)
    else:
        print("Warning: No internet connection detected, Python dependency check will be skipped.")

    # Install esptool package if required
    if should_install_esptool:
        if env is not None:
            # SCons version
            install_esptool(env, platform, penv_python, uv_executable, uv_cache_dir)
        else:
            # Minimal setup - install esptool from tool package
            _install_esptool_from_tl_install(platform, penv_python, uv_executable, uv_cache_dir)

    # Setup certifi environment variables
    _setup_certifi_env(env, penv_python)

    return penv_python, esptool_binary_path


def _setup_pipenv_minimal(penv_dir):
    """
    Setup virtual environment without SCons dependencies.
    Recreates the penv if the Python version does not match the running interpreter.
    
    Args:
        penv_dir (str): Path to virtual environment directory
        
    Returns:
        str or None: Path to uv executable if uv was used, None if python -m venv was used
    """
    # Recreate penv when Python version changed (e.g. Homebrew upgraded 3.13→3.14)
    penv_python_path = get_executable_path(penv_dir, "python")
    if os.path.isfile(penv_python_path) and not _penv_version_matches(penv_dir):
        penv_ver = _get_penv_python_version(penv_dir)
        current_ver = (sys.version_info.major, sys.version_info.minor)
        print(
            f"Python version mismatch: penv has {penv_ver[0]}.{penv_ver[1]}, "
            f"current interpreter is {current_ver[0]}.{current_ver[1]}. "
            f"Recreating penv..."
        )
        shutil.rmtree(penv_dir, ignore_errors=True)

    if not os.path.isfile(get_executable_path(penv_dir, "python")):
        # Attempt virtual environment creation using uv package manager
        uv_success = False
        uv_cmd = None
        try:
            # Derive uv path from current Python path
            python_dir = os.path.dirname(sys.executable)
            uv_exe_suffix = ".exe" if IS_WINDOWS else ""
            uv_cmd = str(Path(python_dir) / f"uv{uv_exe_suffix}")
            
            # Fall back to system uv if derived path doesn't exist
            if not os.path.isfile(uv_cmd):
                uv_cmd = "uv"
                
            subprocess.check_call(
                [uv_cmd, "venv", "--clear", f"--python={sys.executable}", penv_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=90
            )
            uv_success = True
            print(f"Created pioarduino Python virtual environment using uv: {penv_dir}")

        except Exception:
            pass
        
        # Fallback to python -m venv if uv failed or is not available
        if not uv_success:
            uv_cmd = None
            try:
                subprocess.check_call([
                    sys.executable, "-m", "venv", "--clear", penv_dir
                ])
                print(f"Created pioarduino Python virtual environment: {penv_dir}")
            except subprocess.CalledProcessError as e:
                sys.stderr.write(f"Error: Failed to create virtual environment: {e}\n")
                sys.exit(1)
        
        # Validate virtual environment creation
        # Ensure Python executable is available
        penv_python = get_executable_path(penv_dir, "python")
        if not os.path.isfile(penv_python):
            sys.stderr.write(
                f"Error: Failed to create a proper virtual environment. "
                f"Missing the `python` binary at {penv_python}! Created with uv: {uv_success}\n"
            )
            sys.exit(1)
        
        return uv_cmd if uv_success else None
    
    return None


def _install_esptool_from_tl_install(platform, python_exe, uv_executable, uv_cache_dir=None):
    """
    Install esptool from tl-install provided path into penv.
    
    Args:
        platform: PlatformIO platform object  
        python_exe (str): Path to Python executable in virtual environment
        uv_executable (str): Path to uv executable
        uv_cache_dir: Optional path to uv cache directory
    
    Raises:
        SystemExit: If esptool installation fails or package directory not found
    """
    # Get esptool path from tool-esptoolpy package (provided by tl-install)
    esptool_repo_path = platform.get_package_dir("tool-esptoolpy") or ""
    if not esptool_repo_path or not os.path.isdir(esptool_repo_path):
        return (None, None)

    # Build subprocess environment with UV_CACHE_DIR if specified
    uv_env = None
    if uv_cache_dir:
        uv_env = dict(os.environ)
        uv_env["UV_CACHE_DIR"] = str(uv_cache_dir)

    # Check if esptool is already installed from the correct path
    try:
        result = subprocess.run(
            [
                python_exe,
                "-c",
                (
                    "import esptool, os, sys; "
                    "expected_path = os.path.normcase(os.path.realpath(sys.argv[1])); "
                    "actual_path = os.path.normcase(os.path.realpath(os.path.dirname(esptool.__file__))); "
                    "print('MATCH' if actual_path.startswith(expected_path) else 'MISMATCH')"
                ),
                esptool_repo_path,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip() == "MATCH":
            return
            
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        subprocess.check_call([
            uv_executable, "pip", "install", "--quiet", "--force-reinstall",
            f"--python={python_exe}",
            "-e", esptool_repo_path
        ], timeout=60, env=uv_env)
        print(f"Installed esptool from tl-install path: {esptool_repo_path}")

    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to install esptool from {esptool_repo_path} (exit {e.returncode})")
        # Don't exit - esptool installation is not critical for penv setup


def install_freertos_gdb(platform, uv_executable, penv_executable, uv_cache_dir=None):
    """
    Install freertos-gdb into each GDB tool's embedded Python site (share/gdb/python/).

    Iterates over all GDB tool packages known to the platform and installs
    the freertos-gdb PyPI package via uv if not already present.

    Args:
        platform: PlatformIO platform object
        uv_executable (str): Path to uv executable
        penv_executable (str): Path to penv Python executable
        uv_cache_dir: Optional path to uv cache directory
    """
    if not has_network:
        return
        
    uv_env = None
    if uv_cache_dir:
        uv_env = dict(os.environ)
        uv_env["UV_CACHE_DIR"] = str(uv_cache_dir)

    for tool_pkg in GDB_TOOL_PACKAGES.values():
        pkg_dir = platform.get_package_dir(tool_pkg)
        if not pkg_dir or not Path(pkg_dir).is_dir():
            continue
        target_dir = Path(pkg_dir, "share", "gdb", "python")
        if Path(target_dir, "freertos_gdb").is_dir():
            continue
        try:
            subprocess.check_call([
                uv_executable, "pip", "install", "--quiet",
                f"--python={penv_executable}",
                "--target", str(target_dir),
                "freertos-gdb"
            ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                timeout=60,
                env=uv_env,
            )
            print(f"Installed freertos-gdb into {target_dir}")
        except Exception as exc:
            print(f"Warning: Failed to install freertos-gdb into {target_dir}: {exc}")


def _setup_certifi_env(env, python_exe):
    """
    Setup certifi environment variables from the given python_exe virtual environment.
    Uses a subprocess call to extract certifi path from that environment to guarantee penv usage.
    """
    try:
        # Run python executable from penv to get certifi path
        out = subprocess.check_output(
            [python_exe, "-c", "import certifi; print(certifi.where())"],
            text=True,
            timeout=5
        )
        cert_path = out.strip()
    except Exception as e:
        print(f"Error: Failed to obtain certifi path from the virtual environment: {e}")
        return

    # Set environment variables for certificate bundles
    os.environ["CERTIFI_PATH"] = cert_path
    os.environ["SSL_CERT_FILE"] = cert_path
    os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    os.environ["CURL_CA_BUNDLE"] = cert_path
    os.environ["GIT_SSL_CAINFO"] = cert_path

    # Also propagate to SCons environment if available
    if env is not None:
        env_vars = dict(env.get("ENV", {}))
        env_vars.update({
            "CERTIFI_PATH": cert_path,
            "SSL_CERT_FILE": cert_path,
            "REQUESTS_CA_BUNDLE": cert_path,
            "CURL_CA_BUNDLE": cert_path,
            "GIT_SSL_CAINFO": cert_path,
        })
        env.Replace(ENV=env_vars)


def setup_python_environment(env, platform, platformio_dir):
    """
    Main function to setup the Python virtual environment and dependencies.
    
    Args:
        env: SCons environment object
        platform: PlatformIO platform object
        platformio_dir (str): Path to PlatformIO core directory
    
    Returns:
        tuple[str, str]: (Path to penv Python executable, Path to esptool script)
        
    Raises:
        SystemExit: If Python version < 3.10 or dependency installation fails
    """
    return _setup_python_environment_core(env, platform, platformio_dir, should_install_esptool=True)
