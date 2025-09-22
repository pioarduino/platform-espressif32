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
import site
import socket
import subprocess
import sys
from pathlib import Path

from platformio.package.version import pepver_to_semver
from platformio.compat import IS_WINDOWS

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
    r'/v?(\d+\.\d+\.\d+(?:[.-]\w+)?(?:\.\d+)?)(?:\.(?:zip|tar\.gz|tar\.bz2))?$',
    re.IGNORECASE,
)

# Python dependencies required for the build process
python_deps = {
    "platformio": "https://github.com/pioarduino/platformio-core/archive/refs/tags/v6.1.18.zip",
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
    "esp-idf-size": ">=1.6.1"
}


def has_internet_connection(host="1.1.1.1", port=53, timeout=2):
    """
    Checks if an internet connection is available (default: Cloudflare DNS server).
    Returns True if a connection is possible, otherwise False.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_executable_path(penv_dir, executable_name):
    """
    Get the path to an executable based on the penv_dir.
    """
    exe_suffix = ".exe" if IS_WINDOWS else ""
    scripts_dir = "Scripts" if IS_WINDOWS else "bin"
    
    return str(Path(penv_dir) / scripts_dir / f"{executable_name}{exe_suffix}")


def setup_pipenv_in_package(env, penv_dir):
    """
    Checks if 'penv' folder exists in platformio dir and creates virtual environment if not.
    First tries to create with uv, falls back to python -m venv if uv is not available.
    
    Returns:
        str or None: Path to uv executable if uv was used, None if python -m venv was used
    """
    if not os.path.exists(penv_dir):
        # First try to create virtual environment with uv
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
        
        # Verify that the virtual environment was created properly
        # Check for python executable
        assert os.path.isfile(
            get_executable_path(penv_dir, "python")
        ), f"Error: Failed to create a proper virtual environment. Missing the `python` binary! Created with uv: {uv_success}"
        
        return uv_cmd if uv_success else None
    
    return None


def setup_python_paths(penv_dir):
    """Setup Python module search paths using the penv_dir."""    
    # Add site-packages directory
    python_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = (
        str(Path(penv_dir) / "Lib" / "site-packages") if IS_WINDOWS
        else str(Path(penv_dir) / "lib" / python_ver / "site-packages")
    )
    
    if os.path.isdir(site_packages):
        site.addsitedir(site_packages)


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


def install_python_deps(python_exe, external_uv_executable):
    """
    Ensure uv package manager is available in penv and install required Python dependencies.
    
    Args:
        python_exe: Path to Python executable in the penv
        external_uv_executable: Path to external uv executable used to create the penv (can be None)
    
    Returns:
        bool: True if successful, False otherwise
    """
    # Get the penv directory to locate uv within it
    penv_dir = os.path.dirname(os.path.dirname(python_exe))
    penv_uv_executable = get_executable_path(penv_dir, "uv")
    
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
            # Use external uv to install uv into the penv
            try:
                subprocess.check_call(
                    [external_uv_executable, "pip", "install", "uv>=0.1.0", f"--python={python_exe}", "--quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    timeout=120
                )
            except subprocess.CalledProcessError as e:
                print(f"Error: uv installation failed with exit code {e.returncode}")
                return False
            except subprocess.TimeoutExpired:
                print("Error: uv installation timed out")
                return False
            except FileNotFoundError:
                print("Error: External uv executable not found")
                return False
            except Exception as e:
                print(f"Error installing uv package manager into penv: {e}")
                return False
        else:
            # No external uv available, use pip to install uv into penv
            try:
                subprocess.check_call(
                    [python_exe, "-m", "pip", "install", "uv>=0.1.0", "--quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    timeout=120
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
                timeout=120
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
                timeout=120
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


def install_esptool(env, platform, python_exe, uv_executable):
    """
    Install esptool from package folder "tool-esptoolpy" using uv package manager.
    Ensures esptool is installed from the specific tool-esptoolpy package directory.
    
    Args:
        env: SCons environment object
        platform: PlatformIO platform object  
        python_exe (str): Path to Python executable in virtual environment
        uv_executable (str): Path to uv executable
    
    Raises:
        SystemExit: If esptool installation fails or package directory not found
    """
    esptool_repo_path = env.subst(platform.get_package_dir("tool-esptoolpy") or "")
    if not esptool_repo_path or not os.path.isdir(esptool_repo_path):
        sys.stderr.write(
            f"Error: 'tool-esptoolpy' package directory not found: {esptool_repo_path!r}\n"
        )
        sys.exit(1)

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
        ], timeout=60)

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
    # Check Python version requirement
    if sys.version_info < (3, 10):
        sys.stderr.write(
            f"Error: Python 3.10 or higher is required. "
            f"Current version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
            f"Please update your Python installation.\n"
        )
        sys.exit(1)

    penv_dir = str(Path(platformio_dir) / "penv")
    
    # Setup virtual environment if needed
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
    assert os.path.isfile(penv_python), f"Python executable not found: {penv_python}"
    
    # Setup Python module search paths
    setup_python_paths(penv_dir)
    
    # Set executable paths from tools
    esptool_binary_path = get_executable_path(penv_dir, "esptool")
    uv_executable = get_executable_path(penv_dir, "uv")

    # Install espressif32 Python dependencies
    if has_internet_connection() or github_actions:
        if not install_python_deps(penv_python, used_uv_executable):
            sys.stderr.write("Error: Failed to install Python dependencies into penv\n")
            sys.exit(1)
    else:
        print("Warning: No internet connection detected, Python dependency check will be skipped.")

    # Install esptool after dependencies (if requested)
    if should_install_esptool:
        if env is not None:
            # SCons version
            install_esptool(env, platform, penv_python, uv_executable)
        else:
            # Minimal version - install esptool from tl-install provided path
            _install_esptool_from_tl_install(platform, penv_python, uv_executable)

    # Setup certifi environment variables
    _setup_certifi_env(env)

    return penv_python, esptool_binary_path


def _setup_pipenv_minimal(penv_dir):
    """
    Setup virtual environment without SCons dependencies.
    
    Args:
        penv_dir (str): Path to virtual environment directory
        
    Returns:
        str or None: Path to uv executable if uv was used, None if python -m venv was used
    """
    if not os.path.exists(penv_dir):
        # First try to create virtual environment with uv
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
        
        # Verify that the virtual environment was created properly
        # Check for python executable
        assert os.path.isfile(
            get_executable_path(penv_dir, "python")
        ), f"Error: Failed to create a proper virtual environment. Missing the `python` binary! Created with uv: {uv_success}"
        
        return uv_cmd if uv_success else None
    
    return None


def _install_esptool_from_tl_install(platform, python_exe, uv_executable):
    """
    Install esptool from tl-install provided path into penv.
    
    Args:
        platform: PlatformIO platform object  
        python_exe (str): Path to Python executable in virtual environment
        uv_executable (str): Path to uv executable
    
    Raises:
        SystemExit: If esptool installation fails or package directory not found
    """
    # Get esptool path from tool-esptoolpy package (provided by tl-install)
    esptool_repo_path = platform.get_package_dir("tool-esptoolpy") or ""
    if not esptool_repo_path or not os.path.isdir(esptool_repo_path):
        return

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
        ], timeout=60)
        print(f"Installed esptool from tl-install path: {esptool_repo_path}")

    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to install esptool from {esptool_repo_path} (exit {e.returncode})")
        # Don't exit - esptool installation is not critical for penv setup





def _setup_certifi_env(env):
    """Setup certifi environment variables with optional SCons integration."""
    try:
        import certifi
    except ImportError:
        print("Info: certifi not available; skipping CA environment setup.")
        return
    
    cert_path = certifi.where()
    os.environ["CERTIFI_PATH"] = cert_path
    os.environ["SSL_CERT_FILE"] = cert_path
    os.environ["REQUESTS_CA_BUNDLE"] = cert_path
    os.environ["CURL_CA_BUNDLE"] = cert_path
    
    # Also propagate to SCons environment if available
    if env is not None:
        env_vars = dict(env.get("ENV", {}))
        env_vars.update({
            "CERTIFI_PATH": cert_path,
            "SSL_CERT_FILE": cert_path,
            "REQUESTS_CA_BUNDLE": cert_path,
            "CURL_CA_BUNDLE": cert_path,
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
