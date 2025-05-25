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
from os.path import join, exists, isabs, splitdrive, commonpath, relpath

from SCons.Script import DefaultEnvironment, SConscript
from platformio import fs
from platformio.package.version import pepver_to_semver
from platformio.package.manager.tool import ToolPackageManager

# Constants for better performance
UNICORE_FLAGS = {
    "CORE32SOLO1",
    "CONFIG_FREERTOS_UNICORE=y"
}

PYTHON_DEPS = {
    "wheel": ">=0.35.1",
    "rich-click": ">=1.8.6", 
    "PyYAML": ">=6.0.2",
    "intelhex": ">=2.3.0",
    "esp-idf-size": ">=1.6.1"
}

# Cache class for frequently used paths
class PathCache:
    def __init__(self, platform, mcu):
        self.platform = platform
        self.mcu = mcu
        self._framework_dir = None
        self._framework_lib_dir = None
        self._sdk_dir = None
    
    @property
    def framework_dir(self):
        if self._framework_dir is None:
            self._framework_dir = self.platform.get_package_dir("framework-arduinoespressif32")
            if not self._framework_dir or not exists(self._framework_dir):
                raise RuntimeError("Arduino framework package not found")
        return self._framework_dir
    
    @property
    def framework_lib_dir(self):
        if self._framework_lib_dir is None:
            self._framework_lib_dir = self.platform.get_package_dir("framework-arduinoespressif32-libs")
            if not self._framework_lib_dir or not exists(self._framework_lib_dir):
                raise RuntimeError("Arduino framework libs package not found")
        return self._framework_lib_dir
    
    @property 
    def sdk_dir(self):
        if self._sdk_dir is None:
            self._sdk_dir = fs.to_unix_path(
                join(self.framework_lib_dir, self.mcu, "include")
            )
        return self._sdk_dir

# Initialization
env = DefaultEnvironment()
pm = ToolPackageManager()
platform = env.PioPlatform()
config = env.GetProjectConfig()
board = env.BoardConfig()

# Cached values
mcu = board.get("build.mcu", "esp32")
pioenv = env["PIOENV"]
project_dir = env.subst("$PROJECT_DIR")
path_cache = PathCache(platform, mcu)

# Board configuration
board_sdkconfig = board.get("espidf.custom_sdkconfig", "")
entry_custom_sdkconfig = "\n"
flag_custom_sdkconfig = False
IS_WINDOWS = sys.platform.startswith("win")
IS_INTEGRATION_DUMP = env.IsIntegrationDump()

# Custom SDKConfig check
current_env_section = f"env:{pioenv}"
if config.has_option(current_env_section, "custom_sdkconfig"):
    entry_custom_sdkconfig = env.GetProjectOption("custom_sdkconfig")
    flag_custom_sdkconfig = True

if len(board_sdkconfig) > 2:
    flag_custom_sdkconfig = True

extra_flags_raw = board.get("build.extra_flags", [])
if isinstance(extra_flags_raw, list):
    extra_flags = " ".join(extra_flags_raw).replace("-D", " ")
else:
    extra_flags = str(extra_flags_raw).replace("-D", " ")

FRAMEWORK_LIB_DIR = path_cache.framework_lib_dir
FRAMEWORK_SDK_DIR = path_cache.sdk_dir

SConscript("_embed_files.py", exports="env")

flag_any_custom_sdkconfig = exists(join(FRAMEWORK_LIB_DIR, "sdkconfig"))

def has_unicore_flags():
    """Check if any UNICORE flags are present in configuration"""
    return any(flag in extra_flags or flag in entry_custom_sdkconfig 
               or flag in board_sdkconfig for flag in UNICORE_FLAGS)

# Esp32-solo1 libs settings
if flag_custom_sdkconfig and has_unicore_flags():
    build_unflags_value = env.GetProjectOption("build_unflags", default={})
    if not build_unflags_value or build_unflags_value == {}:
        env['BUILD_UNFLAGS'] = {}
    build_unflags = " ".join(env['BUILD_UNFLAGS']) + " -mdisable-hardware-atomics -ustart_app_other_cores"
    new_build_unflags = build_unflags.split()
    env.Replace(BUILD_UNFLAGS=new_build_unflags)

def get_packages_to_install(deps, installed_packages):
    """Generator for packages to install"""
    for package, spec in deps.items():
        if package not in installed_packages:
            yield package
        else:
            version_spec = semantic_version.Spec(spec)
            if not version_spec.match(installed_packages[package]):
                yield package

def install_python_deps():
    def _get_installed_pip_packages():
        result = {}
        try:
            pip_output = subprocess.check_output([
                env.subst("$PYTHONEXE"),
                "-m", "pip", "list", "--format=json", "--disable-pip-version-check"
            ], timeout=30)
            packages = json.loads(pip_output)
            for p in packages:
                result[p["name"]] = pepver_to_semver(p["version"])
        except Exception:
            print("Warning! Couldn't extract the list of installed Python packages.")
        
        return result

    installed_packages = _get_installed_pip_packages()
    packages_to_install = list(get_packages_to_install(PYTHON_DEPS, installed_packages))

    if packages_to_install:
        packages_str = " ".join(f'"{p}{PYTHON_DEPS[p]}"' for p in packages_to_install)
        env.Execute(
            env.VerboseAction(
                f'"$PYTHONEXE" -m pip install -U -q -q -q {packages_str}',
                "Installing Arduino Python dependencies",
            )
        )

install_python_deps()

def get_MD5_hash(phrase):
    return hashlib.md5(phrase.encode('utf-8')).hexdigest()[:16]

def matching_custom_sdkconfig():
    """Checks if current environment matches existing sdkconfig"""
    cust_sdk_is_present = False
    
    if not flag_any_custom_sdkconfig:
        return True, cust_sdk_is_present
        
    last_sdkconfig_path = join(project_dir, "sdkconfig.defaults")
    if not exists(last_sdkconfig_path):
        return False, cust_sdk_is_present
        
    if not flag_custom_sdkconfig:
        return False, cust_sdk_is_present
    
    try:
        with open(last_sdkconfig_path) as src:
            line = src.readline()
            if line.startswith("# TASMOTA__"):
                cust_sdk_is_present = True
                custom_options = entry_custom_sdkconfig
                expected_hash = get_MD5_hash(custom_options.strip() + mcu)
                if line.split("__")[1].strip() == expected_hash:
                    return True, cust_sdk_is_present
    except (IOError, IndexError):
        pass

    return False, cust_sdk_is_present

def check_reinstall_frwrk():
    if not flag_custom_sdkconfig and flag_any_custom_sdkconfig:
        # case custom sdkconfig exists and an env without "custom_sdkconfig"
        return True
    
    if flag_custom_sdkconfig:
        matching_sdkconfig, _ = matching_custom_sdkconfig()
        if not matching_sdkconfig:
            # check if current custom sdkconfig is different from existing
            return True
    
    return False

def call_compile_libs():
    # ESP32-C2 special handling
    if mcu == "esp32c2":
        arduino_frmwrk_c2_lib_dir = join(FRAMEWORK_LIB_DIR, mcu)
        if not exists(arduino_frmwrk_c2_lib_dir):
            arduino_c2_dir = join(
                platform.get_package_dir("framework-arduino-c2-skeleton-lib"), mcu
            )
            if exists(arduino_c2_dir):
                shutil.copytree(arduino_c2_dir, arduino_frmwrk_c2_lib_dir, dirs_exist_ok=True)
    
    print(f"*** Compile Arduino IDF libs for {pioenv} ***")
    SConscript("espidf.py")

def is_framework_subfolder(potential_subfolder):
    if not isabs(potential_subfolder):
        return False
    if splitdrive(FRAMEWORK_SDK_DIR)[0] != splitdrive(potential_subfolder)[0]:
        return False
    return commonpath([FRAMEWORK_SDK_DIR]) == commonpath([FRAMEWORK_SDK_DIR, potential_subfolder])

def shorthen_includes(env, node):
    if IS_INTEGRATION_DUMP:
        # Don't shorten include paths for IDE integrations
        return node

    # Local references for better performance
    env_get = env.get
    to_unix_path = fs.to_unix_path
    ccflags = env["CCFLAGS"]
    asflags = env["ASFLAGS"]
    
    includes = [to_unix_path(inc) for inc in env_get("CPPPATH", [])]
    shortened_includes = []
    generic_includes = []
    
    for inc in includes:
        if is_framework_subfolder(inc):
            shortened_includes.append(
                "-iwithprefix/" + to_unix_path(relpath(inc, FRAMEWORK_SDK_DIR))
            )
        else:
            generic_includes.append(inc)

    common_flags = ["-iprefix", FRAMEWORK_SDK_DIR] + shortened_includes
    
    return env.Object(
        node,
        CPPPATH=generic_includes,
        CCFLAGS=ccflags + common_flags,
        ASFLAGS=asflags + common_flags,
    )

def get_frameworks_in_current_env():
    """Determines the frameworks of the current environment"""
    if "framework" in config.options(current_env_section):
        frameworks_str = config.get(current_env_section, "framework", "")
        return frameworks_str.split(",") if isinstance(frameworks_str, str) else frameworks_str
    return []

def reinstall_framework():
    """Reinstall Arduino framework packages"""
    envs = [section.replace("env:", "") for section in config.sections() if section.startswith("env:")]
    for env_name in envs:
        file_path = join(project_dir, f"sdkconfig.{env_name}")
        if exists(file_path):
            os.remove(file_path)
    
    print("*** Reinstall Arduino framework ***")
    
    # Remove framework directories
    framework_dirs = [
        path_cache.framework_dir,
        path_cache.framework_lib_dir
    ]
    
    for dir_path in framework_dirs:
        if exists(dir_path):
            shutil.rmtree(dir_path)
    
    # Extract URLs and install packages
    arduino_specs = [
        platform.get_package_spec("framework-arduinoespressif32"),
        platform.get_package_spec("framework-arduinoespressif32-libs")
    ]
    
    for spec in arduino_specs:
        spec_str = str(spec)
        if "uri=" in spec_str:
            arduino_frmwrk_url = spec_str.split("uri=", 1)[1][:-1]
            pm.install(arduino_frmwrk_url)
        else:
            raise ValueError(f"Unable to extract framework URI from package spec: {spec}")

# Framework check
current_env_frameworks = get_frameworks_in_current_env()
if "arduino" in current_env_frameworks and "espidf" in current_env_frameworks:
    # Arduino as component is set, switch off Hybrid compile
    flag_custom_sdkconfig = False

# Framework reinstallation if required
if check_reinstall_frwrk():
    reinstall_framework()
    
    if flag_custom_sdkconfig:
        call_compile_libs()
        flag_custom_sdkconfig = False

if flag_custom_sdkconfig and not flag_any_custom_sdkconfig:
    call_compile_libs()

# Main logic for Arduino Framework
pioframework = env.subst("$PIOFRAMEWORK")
arduino_lib_compile_flag = env.subst("$ARDUINO_LIB_COMPILE_FLAG")

if ("arduino" in pioframework and "espidf" not in pioframework and 
    arduino_lib_compile_flag in ("Inactive", "True")):
    
    if IS_WINDOWS:
        env.AddBuildMiddleware(shorthen_includes)
    
    # Arduino SCons build script
    build_script_path = join(path_cache.framework_dir, "tools", "pioarduino-build.py")
    SConscript(build_script_path)

