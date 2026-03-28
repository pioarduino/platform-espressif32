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

import hashlib
import os
import shutil
import sys
import threading
from contextlib import suppress
from os.path import join, exists, isabs, splitdrive, commonpath, relpath
from pathlib import Path
from typing import Union, List

from SCons.Script import DefaultEnvironment, SConscript
from platformio import fs
from platformio.package.manager.tool import ToolPackageManager
from platformio.compat import IS_WINDOWS

# Constants for better performance
UNICORE_FLAGS = {
    "CORE32SOLO1",
    "CONFIG_FREERTOS_UNICORE=y"
}

# Thread-safe lock for one-time warning message
_WARN_LOCK = threading.Lock()
_LONG_PATH_WARNING_SHOWN = False


# Cache class for frequently used paths
class PathCache:
    def __init__(self, platform, mcu, chip_variant):
        self.platform = platform
        self.mcu = mcu
        self.chip_variant = chip_variant
        self._framework_dir = None
        self._framework_lib_dir = None
        self._sdk_dir = None

    @property
    def framework_dir(self):
        if self._framework_dir is None:
            self._framework_dir = self.platform.get_package_dir(
                "framework-arduinoespressif32")
        return self._framework_dir

    @property
    def framework_lib_dir(self):
        if self._framework_lib_dir is None:
            self._framework_lib_dir = self.platform.get_package_dir(
                "framework-arduinoespressif32-libs")
        return self._framework_lib_dir

    @property
    def sdk_dir(self):
        if self._sdk_dir is None:
            if not self.framework_lib_dir:
                return None
            self._sdk_dir = fs.to_unix_path(
                str(Path(self.framework_lib_dir) / self.chip_variant / "include")
            )
        return self._sdk_dir


def check_and_warn_long_path_support():
    """Checks Windows long path support and issues warning if disabled"""
    global _LONG_PATH_WARNING_SHOWN
    with _WARN_LOCK:
        if not IS_WINDOWS or _LONG_PATH_WARNING_SHOWN:
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\FileSystem"
            )
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            winreg.CloseKey(key)
            if value != 1:
                print("*** WARNING: Windows Long Path Support is disabled ***")
                print("*** Enable it for better performance: ***")
                print("*** 1. Run as Administrator: gpedit.msc ***")
                print("*** 2. Navigate to: Computer Configuration > "
                      "Administrative Templates > System > Filesystem ***")
                print("*** 3. Enable 'Enable Win32 long paths' ***")
                print("*** OR run PowerShell as Admin: ***")
                print("*** New-ItemProperty -Path "
                      "'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' "
                      "-Name 'LongPathsEnabled' -Value 1 -PropertyType DWORD "
                      "-Force ***")
                print("*** Restart required after enabling ***")
        except Exception:
            print("*** WARNING: Could not check Long Path Support status ***")
            print("*** Consider enabling Windows Long Path Support for "
                  "better performance ***")
        _LONG_PATH_WARNING_SHOWN = True


# Secure deletion functions
def safe_delete_file(file_path: Union[str, Path],
                     force: bool = False) -> bool:
    """
    Secure file deletion

    Args:
        file_path: Path to file to be deleted
        force: Forces deletion even for write-protected files

    Returns:
        bool: True if successfully deleted
    """
    file_path = Path(file_path)
    try:
        if not file_path.exists():
            return False
        if force and not os.access(file_path, os.W_OK):
            file_path.chmod(0o666)
        file_path.unlink()
        return True
    except PermissionError:
        return False
    except Exception:
        return False


def safe_delete_directory(dir_path: Union[str, Path]) -> bool:
    """
    Secure directory deletion
    """
    dir_path = Path(dir_path)
    try:
        if not dir_path.exists():
            return False
        shutil.rmtree(dir_path)
        return True
    except Exception:
        return False


def validate_platformio_path(path: Union[str, Path]) -> bool:
    """
    Enhanced validation for PlatformIO package paths
    """
    try:
        path = Path(path).resolve()
        path_str = str(path)
        if ".platformio" not in path_str:
            return False
        if "packages" not in path_str:
            return False
        framework_indicators = [
            "framework-arduinoespressif32",
            "framework-arduinoespressif32-libs"
        ]
        if not any(indicator in path_str for indicator in framework_indicators):
            return False
        critical_paths = ["/usr", "/bin", "/sbin", "/etc", "/boot",
                          "C:\\Windows", "C:\\Program Files"]
        return not any(critical in path_str for critical in critical_paths)
    except Exception:
        return False


def validate_deletion_path(path: Union[str, Path],
                           allowed_patterns: List[str]) -> bool:
    """
    Validates if a path can be safely deleted

    Args:
        path: Path to be checked
        allowed_patterns: Allowed path patterns

    Returns:
        bool: True if deletion is safe
    """
    path = Path(path).resolve()
    critical_paths = [
        Path.home(),
        Path("/"),
        Path("C:\\") if IS_WINDOWS else None,
        Path("/usr"),
        Path("/etc"),
        Path("/bin"),
        Path("/sbin")
    ]
    for critical in filter(None, critical_paths):
        try:
            normalized_path = path.resolve()
            normalized_critical = critical.resolve()
            if (normalized_path == normalized_critical or
                    normalized_critical in normalized_path.parents):
                return False
        except (OSError, ValueError):
            return False
    path_str = str(path)
    return any(pattern in path_str for pattern in allowed_patterns)


def safe_framework_cleanup():
    """Secure cleanup of Arduino Framework with enhanced error handling"""
    success = True
    if exists(FRAMEWORK_DIR):
        if validate_platformio_path(FRAMEWORK_DIR):
            if not safe_delete_directory(FRAMEWORK_DIR):
                print("Error removing framework")
                success = False
    if exists(FRAMEWORK_LIB_DIR):
        if validate_platformio_path(FRAMEWORK_LIB_DIR):
            if not safe_delete_directory(FRAMEWORK_LIB_DIR):
                print("Error removing framework libs")
                success = False
    return success


def safe_remove_sdkconfig_files():
    """Secure removal of SDKConfig files"""
    envs = [section.replace("env:", "") for section in config.sections()
            if section.startswith("env:")]
    for env_name in envs:
        file_path = str(Path(project_dir) / f"sdkconfig.{env_name}")
        if exists(file_path):
            safe_delete_file(file_path)


# Initialization
env = DefaultEnvironment()
pm = ToolPackageManager()
platform = env.PioPlatform()
config = env.GetProjectConfig()
board = env.BoardConfig()

# Cached values
mcu = board.get("build.mcu", "esp32")
chip_variant = env.BoardConfig().get("build.chip_variant", "").lower()
chip_variant = chip_variant if chip_variant else mcu
pioenv = env["PIOENV"]
project_dir = env.subst("$PROJECT_DIR")
path_cache = PathCache(platform, mcu, chip_variant)
current_env_section = f"env:{pioenv}"

# Board configuration
board_sdkconfig = board.get("espidf.custom_sdkconfig", "")
entry_custom_sdkconfig = "\n"
flag_custom_sdkconfig = False
flag_custom_component_remove = False
flag_custom_component_add = False
flag_lib_ignore = False
flag_lto = False

# pio lib_ignore check
if config.has_option(current_env_section, "lib_ignore"):
    flag_lib_ignore = True

# Custom Component remove check
if config.has_option(current_env_section, "custom_component_remove"):
    flag_custom_component_remove = True

# Custom SDKConfig check
if config.has_option(current_env_section, "custom_sdkconfig"):
    entry_custom_sdkconfig = env.GetProjectOption("custom_sdkconfig")
    # When custom_sdkconfig references a file, include its mtime in the
    # value used for hash computation. A changed mtime means a new hash
    # and triggers the existing Reinstall path.
    for line in entry_custom_sdkconfig.splitlines():
        line = line.strip()
        if line.startswith("file://"):
            file_ref = line[7:]
            file_path = file_ref if isabs(file_ref) else join(project_dir, file_ref)
            try:
                mtime = str(os.path.getmtime(file_path))
                entry_custom_sdkconfig = mtime + "\n" + entry_custom_sdkconfig
            except OSError:
                pass
            break
    flag_custom_sdkconfig = True

if board_sdkconfig:
    flag_custom_sdkconfig = True

extra_flags_raw = board.get("build.extra_flags", [])
if isinstance(extra_flags_raw, list):
    extra_flags = " ".join(extra_flags_raw).replace("-D", " ")
else:
    extra_flags = str(extra_flags_raw).replace("-D", " ")

framework_reinstall = False

FRAMEWORK_DIR = path_cache.framework_dir
FRAMEWORK_LIB_DIR = path_cache.framework_lib_dir

SConscript("_embed_files.py", exports="env")

flag_any_custom_sdkconfig = (FRAMEWORK_LIB_DIR is not None and
                            exists(str(Path(FRAMEWORK_LIB_DIR) / "sdkconfig")))


def has_unicore_flags():
    """Check if any UNICORE flags are present in configuration"""
    return any(flag in extra_flags or flag in entry_custom_sdkconfig
               or flag in board_sdkconfig for flag in UNICORE_FLAGS)


def has_psram_config():
    """Check if PSRAM is configured in extra_flags, entry_custom_sdkconfig or board_sdkconfig"""
    return ("PSRAM" in extra_flags or "PSRAM" in entry_custom_sdkconfig
            or "PSRAM" in board_sdkconfig or "CONFIG_SPIRAM=y" in extra_flags
            or "CONFIG_SPIRAM=y" in entry_custom_sdkconfig
            or "CONFIG_SPIRAM=y" in board_sdkconfig)


def has_picolibc_config():
    """Check if picolibc is configured in custom_sdkconfig"""
    return ("CONFIG_LIBC_PICOLIBC=y" in entry_custom_sdkconfig or
            "CONFIG_LIBC_PICOLIBC=y" in board_sdkconfig)


# Esp32 settings for solo1 and PSRAM
if flag_custom_sdkconfig:
    if not env.get('BUILD_UNFLAGS'):  # Initialize if not set
        env['BUILD_UNFLAGS'] = []

    build_unflags = " ".join(env['BUILD_UNFLAGS'])

    # -mdisable-hardware-atomics: always for solo1, or when PSRAM is NOT configured
    if has_unicore_flags() or not has_psram_config():
        build_unflags += " -mdisable-hardware-atomics"

    # -ustart_app_other_cores only and always for solo1
    if has_unicore_flags():
        build_unflags += " -ustart_app_other_cores"

    # Check for enabling LTO for Arduino HybridCompile part by unflagging -fno-lto
    if '-fno-lto' in build_unflags:
        flag_lto = True

    new_build_unflags = build_unflags.split()
    env.Replace(BUILD_UNFLAGS=new_build_unflags)


def get_MD5_hash(phrase):
    return hashlib.md5(phrase.encode('utf-8')).hexdigest()[:16]


def matching_custom_sdkconfig():
    """Checks if current environment matches existing sdkconfig"""
    cust_sdk_is_present = False

    if not flag_any_custom_sdkconfig:
        return True, cust_sdk_is_present

    last_sdkconfig_path = str(Path(project_dir) / "sdkconfig.defaults")
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
    print(f"*** Compile Arduino IDF libs for {pioenv} ***")
    SConscript("espidf.py")


FRAMEWORK_SDK_DIR = path_cache.sdk_dir
IS_INTEGRATION_DUMP = env.IsIntegrationDump()


def is_framework_subfolder(potential_subfolder):
    """Check if a path is a subfolder of the framework SDK directory"""
    # carefully check before change this function
    if FRAMEWORK_SDK_DIR is None:
        return False
    if not isabs(potential_subfolder):
        return False
    if (splitdrive(FRAMEWORK_SDK_DIR)[0] !=
            splitdrive(potential_subfolder)[0]):
        return False
    return (commonpath([FRAMEWORK_SDK_DIR]) ==
            commonpath([FRAMEWORK_SDK_DIR, potential_subfolder]))


def get_frameworks_in_current_env():
    """Determines the frameworks of the current environment"""
    if "framework" in config.options(current_env_section):
        return config.get(current_env_section, "framework", "")
    return []


# Framework check
current_env_frameworks = get_frameworks_in_current_env()
if "arduino" in current_env_frameworks and "espidf" in current_env_frameworks:
    # Arduino as component is set, switch off Hybrid compile
    flag_custom_sdkconfig = False

# Framework reinstallation if required
if check_reinstall_frwrk():
    safe_remove_sdkconfig_files()

    print("*** Reinstall Arduino framework ***")

    if safe_framework_cleanup():
        arduino_frmwrk_url = str(platform.get_package_spec(
            "framework-arduinoespressif32")).split("uri=", 1)[1][:-1]
        arduino_frmwrk_lib_url = str(platform.get_package_spec(
            "framework-arduinoespressif32-libs")).split("uri=", 1)[1][:-1]
        pm.install(arduino_frmwrk_url)
        pm.install(arduino_frmwrk_lib_url)

        if flag_custom_sdkconfig:
            call_compile_libs()
            flag_custom_sdkconfig = False
    else:
        print("Framework cleanup failed - installation aborted")
        sys.exit(1)

if flag_custom_sdkconfig and not flag_any_custom_sdkconfig:
    call_compile_libs()

# Arduino framework configuration and build logic
pioframework = env.subst("$PIOFRAMEWORK")
arduino_lib_compile_flag = env.subst("$ARDUINO_LIB_COMPILE_FLAG")

if ("arduino" in pioframework and "espidf" not in pioframework and
        arduino_lib_compile_flag in ("Inactive", "True")):

    # try to remove not needed include path if an lib_ignore entry exists
    from component_manager import ComponentManager
    component_manager = ComponentManager(env)
    component_manager.handle_component_settings()

    # Create backup once if any build script patches are needed
    needs_build_script_patch = flag_lto or has_picolibc_config()
    if needs_build_script_patch:
        component_manager.backup_manager.backup_pioarduino_build_py()

    # Handle LTO flags if flag_lto is set
    if flag_lto:
        # First remove existing -fno-lto flags, then add LTO flags
        component_manager.remove_no_lto_flags()
        component_manager.add_lto_flags()

    # Handle picolibc flags if picolibc is configured
    if has_picolibc_config():
        component_manager.apply_picolibc_flags()

    silent_action = env.Action(component_manager.restore_pioarduino_build_py)
    # silence scons command output
    silent_action.strfunction = lambda target, source, env: ''
    env.AddPostAction("checkprogsize", silent_action)

    if IS_WINDOWS and not IS_INTEGRATION_DUMP:
        from SCons.Platform import TempFileMunge

        check_and_warn_long_path_support()

        # TempFileMunge for *COM-variables - set before SCons script
        # env.Append in MCU-Script does not overwrite the wrapper
        env["TEMPFILE"]       = TempFileMunge
        env["TEMPFILEPREFIX"] = "@"
        env["TEMPFILESUFFIX"] = ".rsp"
        env["MAXLINELENGTH"]  = 4096  # increase the conservative default value of 2048

        for _var in ["CCCOM", "CXXCOM", "ASCOM", "ASPPCOM", "LINKCOM"]:
            if _var in env and "TEMPFILE" not in str(env[_var]):
                env[_var] = "${TEMPFILE('%s')}" % env[_var]


    build_script_path = str(Path(FRAMEWORK_DIR) / "tools" / "pioarduino-build.py")
    SConscript(build_script_path)
