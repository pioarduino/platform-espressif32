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

"""
Arduino Framework for ESP32

Arduino Wiring-based Framework allows writing cross-platform software to
control devices attached to a wide range of Arduino boards to create all
kinds of creative coding, interactive objects, spaces or physical experiences.

http://arduino.cc/en/Reference/HomePage
"""

import subprocess
import json
import semantic_version
import os
import sys
import shutil
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from os.path import join, exists

from SCons.Script import COMMAND_LINE_TARGETS, DefaultEnvironment, SConscript
from platformio import fs
from platformio.package.version import pepver_to_semver
from platformio.project.config import ProjectConfig
from platformio.package.manager.tool import ToolPackageManager

# Constants
PYTHON_DEPS = {
    "wheel": ">=0.35.1",
    "rich-click": ">=1.8.6", 
    "PyYAML": ">=6.0.2",
    "intelhex": ">=2.3.0",
    "esp-idf-size": ">=1.6.1"
}

# Global environment setup
env = DefaultEnvironment()
pm = ToolPackageManager()
platform = env.PioPlatform()
config = env.GetProjectConfig()
board = env.BoardConfig()
mcu = board.get("build.mcu", "esp32")
board_sdkconfig = board.get("espidf.custom_sdkconfig", "")
IS_WINDOWS = sys.platform.startswith("win")
IS_INTEGRATION_DUMP = env.IsIntegrationDump()
pioenv = env["PIOENV"]

# Framework paths
FRAMEWORK_LIB_DIR = platform.get_package_dir("framework-arduinoespressif32-libs")
FRAMEWORK_SDK_DIR = fs.to_unix_path(join(FRAMEWORK_LIB_DIR, mcu, "include"))

# Configuration flags
if config.has_option(f"env:{pioenv}", "custom_sdkconfig"):
    entry_custom_sdkconfig = config.get(f"env:{pioenv}", "custom_sdkconfig")
else:
    entry_custom_sdkconfig = "\n"

flag_custom_sdkconfig = (
    config.has_option(f"env:{pioenv}", "custom_sdkconfig") or 
    len(str(board_sdkconfig)) > 2
)

# Process extra flags
extra_flags_raw = board.get("build.extra_flags", [])
extra_flags = (" ".join(extra_flags_raw) if isinstance(extra_flags_raw, list) 
               else str(extra_flags_raw)).replace("-D", " ")

flag_any_custom_sdkconfig = exists(join(FRAMEWORK_LIB_DIR, "sdkconfig"))

# Load embedded files
SConscript("_embed_files.py", exports="env")

def setup_esp32_solo1_config() -> None:
    """Configure ESP32-Solo1 specific settings."""
    solo1_conditions = [
        "CORE32SOLO1" in extra_flags,
        "CONFIG_FREERTOS_UNICORE=y" in entry_custom_sdkconfig,
        "CONFIG_FREERTOS_UNICORE=y" in board_sdkconfig
    ]
    
    if flag_custom_sdkconfig and any(solo1_conditions):
        if len(str(env.GetProjectOption("build_unflags"))) == 2:
            env['BUILD_UNFLAGS'] = {}
        
        build_unflags = " ".join(env['BUILD_UNFLAGS'])
        build_unflags += " -mdisable-hardware-atomics -ustart_app_other_cores"
        env.Replace(BUILD_UNFLAGS=build_unflags.split())

@lru_cache(maxsize=1)
def get_installed_pip_packages() -> Dict[str, str]:
    """Get list of installed pip packages with caching."""
    try:
        pip_output = subprocess.check_output([
            env.subst("$PYTHONEXE"), "-m", "pip", "list", 
            "--format=json", "--disable-pip-version-check"
        ], timeout=30)
        packages = json.loads(pip_output)
        return {p["name"]: pepver_to_semver(p["version"]) for p in packages}
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError):
        print("Warning! Couldn't extract the list of installed Python packages.")
        return {}

def install_python_deps() -> None:
    """Install required Python dependencies efficiently."""
    installed_packages = get_installed_pip_packages()
    packages_to_install = []
    
    for package, spec in PYTHON_DEPS.items():
        if package not in installed_packages:
            packages_to_install.append(f"{package}{spec}")
        else:
            version_spec = semantic_version.Spec(spec)
            if not version_spec.match(installed_packages[package]):
                packages_to_install.append(f"{package}{spec}")

    if packages_to_install:
        env.Execute(env.VerboseAction(
            f'"$PYTHONEXE" -m pip install -U -q -q -q {" ".join(packages_to_install)}',
            "Installing Arduino Python dependencies"
        ))

def get_md5_hash(phrase: str) -> str:
    """Generate MD5 hash for given phrase."""
    return hashlib.md5(phrase.encode('utf-8')).hexdigest()[:16]

@lru_cache(maxsize=32)
def matching_custom_sdkconfig() -> Tuple[bool, bool]:
    """Check if custom sdkconfig matches current configuration."""
    cust_sdk_is_present = False
    matching_sdkconfig = False
    last_sdkconfig_path = Path(env.subst("$PROJECT_DIR")) / "sdkconfig.defaults"
    
    if not flag_any_custom_sdkconfig:
        return True, cust_sdk_is_present
        
    if not last_sdkconfig_path.exists():
        return matching_sdkconfig, cust_sdk_is_present
        
    if not flag_custom_sdkconfig:
        return False, cust_sdk_is_present
    
    try:
        with open(last_sdkconfig_path, 'r') as src:
            line = src.readline()
            if line.startswith("# TASMOTA__"):
                cust_sdk_is_present = True
                expected_hash = get_md5_hash(f"{entry_custom_sdkconfig.strip()}{mcu}")
                if line.split("__")[1].strip() == expected_hash:
                    matching_sdkconfig = True
    except (IOError, IndexError):
        pass
    
    return matching_sdkconfig, cust_sdk_is_present

def check_reinstall_framework() -> bool:
    """Determine if framework needs reinstallation."""
    if not flag_custom_sdkconfig and flag_any_custom_sdkconfig:
        return True
    
    if flag_custom_sdkconfig:
        matching_sdkconfig, _ = matching_custom_sdkconfig()
        return not matching_sdkconfig
    
    return False

def shorthen_includes(env, node):
    """Optimize include paths for Windows builds."""
    if IS_INTEGRATION_DUMP:
        return node

    includes = [fs.to_unix_path(inc) for inc in env.get("CPPPATH", [])]
    shortened_includes = []
    generic_includes = []
    
    for inc in includes:
        if is_framework_subfolder(inc):
            rel_path = fs.to_unix_path(os.path.relpath(inc, FRAMEWORK_SDK_DIR))
            shortened_includes.append(f"-iwithprefix/{rel_path}")
        else:
            generic_includes.append(inc)

    common_flags = ["-iprefix", FRAMEWORK_SDK_DIR] + shortened_includes
    return env.Object(
        node,
        CPPPATH=generic_includes,
        CCFLAGS=env["CCFLAGS"] + common_flags,
        ASFLAGS=env["ASFLAGS"] + common_flags,
    )

def is_framework_subfolder(potential_subfolder: str) -> bool:
    """Check if path is a framework subfolder."""
    if not os.path.isabs(potential_subfolder):
        return False
    
    framework_drive = os.path.splitdrive(FRAMEWORK_SDK_DIR)[0]
    potential_drive = os.path.splitdrive(potential_subfolder)[0]
    
    if framework_drive != potential_drive:
        return False
    
    try:
        return (os.path.commonpath([FRAMEWORK_SDK_DIR]) == 
                os.path.commonpath([FRAMEWORK_SDK_DIR, potential_subfolder]))
    except ValueError:
        return False

@lru_cache(maxsize=1)
def get_frameworks_in_current_env() -> List[str]:
    """Get frameworks configured for current environment."""
    current_env_section = f"env:{pioenv}"
    if "framework" in config.options(current_env_section):
        frameworks = config.get(current_env_section, "framework", "")
        return frameworks.split(",") if isinstance(frameworks, str) else frameworks
    return []

def call_compile_libs() -> None:
    """Compile Arduino IDF libraries."""
    if mcu == "esp32c2":
        arduino_frmwrk_c2_lib_dir = Path(FRAMEWORK_LIB_DIR) / mcu
        if not arduino_frmwrk_c2_lib_dir.exists():
            arduino_c2_dir = Path(
                platform.get_package_dir("framework-arduino-c2-skeleton-lib")
            ) / mcu
            shutil.copytree(arduino_c2_dir, arduino_frmwrk_c2_lib_dir, dirs_exist_ok=True)
    
    print(f"*** Compile Arduino IDF libs for {pioenv} ***")
    SConscript("espidf.py")

def reinstall_framework() -> None:
    """Reinstall Arduino framework packages."""
    # Clean up existing sdkconfig files
    envs = [section.replace("env:", "") for section in config.sections() 
            if section.startswith("env:")]
    
    project_dir = Path(env.subst("$PROJECT_DIR"))
    for env_name in envs:
        sdkconfig_file = project_dir / f"sdkconfig.{env_name}"
        if sdkconfig_file.exists():
            sdkconfig_file.unlink()
    
    print("*** Reinstall Arduino framework ***")
    
    # Remove framework directories
    framework_dirs = [
        platform.get_package_dir("framework-arduinoespressif32"),
        platform.get_package_dir("framework-arduinoespressif32-libs")
    ]
    
    for dir_path in framework_dirs:
        if Path(dir_path).exists():
            shutil.rmtree(dir_path)
    
    # Extract URLs and install packages
    arduino_specs = [
        platform.get_package_spec("framework-arduinoespressif32"),
        platform.get_package_spec("framework-arduinoespressif32-libs")
    ]
    
    for spec in arduino_specs:
        url = str(spec).split("uri=", 1)[1][:-1]
        pm.install(url)

# Setup ESP32-Solo1 configuration
setup_esp32_solo1_config()

# Install Python dependencies
install_python_deps()

# Handle framework configuration
current_env_frameworks = get_frameworks_in_current_env()
if "arduino" in current_env_frameworks and "espidf" in current_env_frameworks:
    flag_custom_sdkconfig = False

# Check if framework reinstallation is needed
if check_reinstall_framework():
    reinstall_framework()
    if flag_custom_sdkconfig:
        call_compile_libs()
        flag_custom_sdkconfig = False

# Compile libs if needed
if flag_custom_sdkconfig and not flag_any_custom_sdkconfig:
    call_compile_libs()

# Final framework setup
pioframework = env.subst("$PIOFRAMEWORK")
arduino_lib_compile_flag = env.subst("$ARDUINO_LIB_COMPILE_FLAG")

if ("arduino" in pioframework and 
    "espidf" not in pioframework and 
    arduino_lib_compile_flag in ("Inactive", "True")):
    
    if IS_WINDOWS:
        env.AddBuildMiddleware(shorthen_includes)
    
    framework_dir = platform.get_package_dir("framework-arduinoespressif32")
    pio_build_path = Path(framework_dir) / "tools" / "platformio-build.py"
    
    build_script = "platformio-build.py" if pio_build_path.exists() else "pioarduino-build.py"
    SConscript(join(framework_dir, "tools", build_script))

