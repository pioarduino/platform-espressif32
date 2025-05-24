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
Arduino

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
from os.path import join, exists

from SCons.Script import COMMAND_LINE_TARGETS, DefaultEnvironment, SConscript
from platformio import fs
from platformio.package.version import pepver_to_semver
from platformio.project.config import ProjectConfig
from platformio.package.manager.tool import ToolPackageManager

# Global variables for better performance
env = DefaultEnvironment()
pm = ToolPackageManager()
platform = env.PioPlatform()
config = env.GetProjectConfig()
board = env.BoardConfig()
mcu = board.get("build.mcu", "esp32")
board_sdkconfig = board.get("espidf.custom_sdkconfig", "")
IS_WINDOWS = sys.platform.startswith("win")
IS_INTEGRATION_DUMP = env.IsIntegrationDump()

# Cache for frequently used values
FRAMEWORK_LIB_DIR = platform.get_package_dir("framework-arduinoespressif32-libs")
FRAMEWORK_SDK_DIR = fs.to_unix_path(join(FRAMEWORK_LIB_DIR, mcu, "include"))

# Optimized configuration detection
entry_custom_sdkconfig = "\n"
flag_custom_sdkconfig = False
pioenv = env["PIOENV"]

if config.has_option(f"env:{pioenv}", "custom_sdkconfig"):
    entry_custom_sdkconfig = env.GetProjectOption("custom_sdkconfig")
    flag_custom_sdkconfig = True

if len(str(board_sdkconfig)) > 2:
    flag_custom_sdkconfig = True

extra_flags_raw = board.get("build.extra_flags", [])
if isinstance(extra_flags_raw, list):
    extra_flags = " ".join(extra_flags_raw).replace("-D", " ")
else:
    extra_flags = str(extra_flags_raw).replace("-D", " ")
flag_any_custom_sdkconfig = exists(join(FRAMEWORK_LIB_DIR, "sdkconfig"))

SConscript("_embed_files.py", exports="env")

# Optimized ESP32-Solo1 configuration
if (flag_custom_sdkconfig and 
    ("CORE32SOLO1" in extra_flags or 
     "CONFIG_FREERTOS_UNICORE=y" in entry_custom_sdkconfig or 
     "CONFIG_FREERTOS_UNICORE=y" in board_sdkconfig)):
    
    if len(str(env.GetProjectOption("build_unflags"))) == 2:
        env['BUILD_UNFLAGS'] = {}
    
    build_unflags = " ".join(env['BUILD_UNFLAGS'])
    build_unflags += " -mdisable-hardware-atomics -ustart_app_other_cores"
    env.Replace(BUILD_UNFLAGS=build_unflags.split())

# Cache for installed packages
_installed_packages_cache = None

def install_python_deps():
    global _installed_packages_cache
    
    def _get_installed_pip_packages():
        global _installed_packages_cache
        if _installed_packages_cache is not None:
            return _installed_packages_cache
            
        try:
            pip_output = subprocess.check_output([
                env.subst("$PYTHONEXE"), "-m", "pip", "list", 
                "--format=json", "--disable-pip-version-check"
            ])
            packages = json.loads(pip_output)
            _installed_packages_cache = {
                p["name"]: pepver_to_semver(p["version"]) 
                for p in packages
            }
        except:
            print("Warning! Couldn't extract the list of installed Python packages.")
            _installed_packages_cache = {}
        
        return _installed_packages_cache

    deps = {
        "wheel": ">=0.35.1",
        "rich-click": ">=1.8.6", 
        "PyYAML": ">=6.0.2",
        "intelhex": ">=2.3.0",
        "esp-idf-size": ">=1.6.1"
    }

    installed_packages = _get_installed_pip_packages()
    packages_to_install = []
    
    for package, spec in deps.items():
        if package not in installed_packages:
            packages_to_install.append(package)
        else:
            version_spec = semantic_version.Spec(spec)
            if not version_spec.match(installed_packages[package]):
                packages_to_install.append(package)

    if packages_to_install:
        env.Execute(env.VerboseAction(
            f'"$PYTHONEXE" -m pip install -U -q -q -q {" ".join(f"{p}{deps[p]}" for p in packages_to_install)}',
            "Installing Arduino Python dependencies"
        ))

install_python_deps()

# Optimized MD5 hash function
def get_MD5_hash(phrase):
    return hashlib.md5(phrase.encode('utf-8')).hexdigest()[:16]

# Cache for sdkconfig matching
_sdkconfig_cache = {}

def matching_custom_sdkconfig():
    global _sdkconfig_cache
    
    cache_key = f"{pioenv}_{mcu}_{flag_custom_sdkconfig}_{flag_any_custom_sdkconfig}"
    if cache_key in _sdkconfig_cache:
        return _sdkconfig_cache[cache_key]
    
    cust_sdk_is_present = False
    matching_sdkconfig = False
    last_sdkconfig_path = join(env.subst("$PROJECT_DIR"), "sdkconfig.defaults")
    
    if not flag_any_custom_sdkconfig:
        matching_sdkconfig = True
        result = (matching_sdkconfig, cust_sdk_is_present)
        _sdkconfig_cache[cache_key] = result
        return result
        
    if not exists(last_sdkconfig_path):
        result = (matching_sdkconfig, cust_sdk_is_present)
        _sdkconfig_cache[cache_key] = result
        return result
        
    if not flag_custom_sdkconfig:
        matching_sdkconfig = False
        result = (matching_sdkconfig, cust_sdk_is_present)
        _sdkconfig_cache[cache_key] = result
        return result
    
    try:
        with open(last_sdkconfig_path, 'r') as src:
            line = src.readline()
            if line.startswith("# TASMOTA__"):
                cust_sdk_is_present = True
                costum_options = entry_custom_sdkconfig
                expected_hash = get_MD5_hash(f"{costum_options.strip()}{mcu}")
                if line.split("__")[1].strip() == expected_hash:
                    matching_sdkconfig = True
    except IOError:
        pass
    
    result = (matching_sdkconfig, cust_sdk_is_present)
    _sdkconfig_cache[cache_key] = result
    return result

def check_reinstall_frwrk():
    if not flag_custom_sdkconfig and flag_any_custom_sdkconfig:
        return True
    
    if flag_custom_sdkconfig:
        matching_sdkconfig, _ = matching_custom_sdkconfig()
        if not matching_sdkconfig:
            return True
    
    return False

# Optimized include path shortening
def shorthen_includes(env, node):
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

def is_framework_subfolder(potential_subfolder):
    if not os.path.isabs(potential_subfolder):
        return False
    if (os.path.splitdrive(FRAMEWORK_SDK_DIR)[0] != 
        os.path.splitdrive(potential_subfolder)[0]):
        return False
    return (os.path.commonpath([FRAMEWORK_SDK_DIR]) == 
            os.path.commonpath([FRAMEWORK_SDK_DIR, potential_subfolder]))

# Cache for framework detection
_current_env_frameworks = None

def get_frameworks_in_current_env():
    global _current_env_frameworks
    if _current_env_frameworks is not None:
        return _current_env_frameworks
        
    current_env_section = f"env:{pioenv}"
    if "framework" in config.options(current_env_section):
        _current_env_frameworks = config.get(current_env_section, "framework", "")
    else:
        _current_env_frameworks = []
    return _current_env_frameworks

current_env_frameworks = get_frameworks_in_current_env()
if "arduino" in current_env_frameworks and "espidf" in current_env_frameworks:
    flag_custom_sdkconfig = False

def call_compile_libs():
    if mcu == "esp32c2":
        arduino_frmwrk_c2_lib_dir = join(FRAMEWORK_LIB_DIR, mcu)
        if not exists(arduino_frmwrk_c2_lib_dir):
            arduino_c2_dir = join(
                platform.get_package_dir("framework-arduino-c2-skeleton-lib"), mcu
            )
            shutil.copytree(arduino_c2_dir, arduino_frmwrk_c2_lib_dir, dirs_exist_ok=True)
    
    print(f"*** Compile Arduino IDF libs for {pioenv} ***")
    SConscript("espidf.py")

# Main logic for framework reinstallation
if check_reinstall_frwrk():
    envs = [section.replace("env:", "") for section in config.sections() 
            if section.startswith("env:")]
    
    project_dir = env.subst("$PROJECT_DIR")
    for env_name in envs:
        file_path = join(project_dir, f"sdkconfig.{env_name}")
        if exists(file_path):
            os.remove(file_path)
    
    print("*** Reinstall Arduino framework ***")
    
    # Prepare parallel deletion
    dirs_to_remove = [
        platform.get_package_dir("framework-arduinoespressif32"),
        platform.get_package_dir("framework-arduinoespressif32-libs")
    ]
    
    for dir_path in dirs_to_remove:
        if exists(dir_path):
            shutil.rmtree(dir_path)
    
    # Extract URLs and install
    arduino_frmwrk_url = str(platform.get_package_spec("framework-arduinoespressif32")).split("uri=", 1)[1][:-1]
    arduino_frmwrk_lib_url = str(platform.get_package_spec("framework-arduinoespressif32-libs")).split("uri=", 1)[1][:-1]
    
    pm.install(arduino_frmwrk_url)
    pm.install(arduino_frmwrk_lib_url)
    
    if flag_custom_sdkconfig:
        call_compile_libs()
        flag_custom_sdkconfig = False

if flag_custom_sdkconfig and not flag_any_custom_sdkconfig:
    call_compile_libs()

# Final execution
pioframework = env.subst("$PIOFRAMEWORK")
arduino_lib_compile_flag = env.subst("$ARDUINO_LIB_COMPILE_FLAG")

if ("arduino" in pioframework and 
    "espidf" not in pioframework and 
    arduino_lib_compile_flag in ("Inactive", "True")):
    
    if IS_WINDOWS:
        env.AddBuildMiddleware(shorthen_includes)
    
    framework_dir = platform.get_package_dir("framework-arduinoespressif32")
    pio_build_path = join(framework_dir, "tools", "platformio-build.py")
    
    if exists(pio_build_path):
        pio_build = "platformio-build.py"
    else:
        pio_build = "pioarduino-build.py"
    
    SConscript(join(framework_dir, "tools", pio_build))

