# Copyright 2020-present PlatformIO <contact@platformio.org>
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
Espressif IDF

Espressif IoT Development Framework for ESP32 MCU

https://github.com/espressif/esp-idf
"""

import copy
import importlib.util
import json
import os
import platform as sys_platform
import re
import requests
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

import click
import semantic_version

from SCons.Script import (
    ARGUMENTS,
    COMMAND_LINE_TARGETS,
    DefaultEnvironment,
)

from platformio import fs
from platformio.compat import IS_WINDOWS
from platformio.proc import exec_command
from platformio.builder.tools.piolib import ProjectAsLibBuilder
from platformio.package.version import get_original_version, pepver_to_semver


env = DefaultEnvironment()
env.SConscript("_embed_files.py", exports="env")
platform = env.PioPlatform()

_component_manager_file = Path(platform.get_dir()) / "builder" / "frameworks" / "component_manager.py"
_cm_spec = importlib.util.spec_from_file_location("component_manager", _component_manager_file)
_component_manager = importlib.util.module_from_spec(_cm_spec)
_cm_spec.loader.exec_module(_component_manager)
sys.modules["component_manager"] = _component_manager

_penv_setup_file = str(Path(platform.get_dir()) / "builder" / "penv_setup.py")
_spec = importlib.util.spec_from_file_location("penv_setup", _penv_setup_file)
_penv_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_penv_setup)  # type: ignore[attr-defined]
sys.modules["penv_setup"] = _penv_setup
get_executable_path = _penv_setup.get_executable_path

# remove maybe existing old map file in project root
map_file = str(Path(env.subst("$PROJECT_DIR")) / (env.subst("$PROGNAME") + ".map"))
if os.path.exists(map_file):
    os.remove(map_file)

# Allow changes in folders of managed components
os.environ["IDF_COMPONENT_OVERWRITE_MANAGED_COMPONENTS"] = "1"

config = env.GetProjectConfig()
board = env.BoardConfig()
pio_orig_frwrk = env.GetProjectOption("framework")
mcu = board.get("build.mcu", "esp32")
chip_variant = board.get("build.chip_variant", "").lower()
chip_variant = chip_variant if chip_variant else mcu
flash_speed = board.get("build.f_flash", "40000000L")
flash_frequency = str(flash_speed.replace("000000L", ""))
flash_mode = board.get("build.flash_mode", "dio")
boot_mode = board.get("build.boot", None)
idf_variant = mcu.lower()
flag_custom_sdkonfig = False
flag_custom_component_add = False
flag_custom_component_remove = False

IDF_ENV_VERSION = "1.0.0"
_framework_pkg_dir = platform.get_package_dir("framework-espidf")
if not _framework_pkg_dir or not os.path.isdir(_framework_pkg_dir):
    sys.stderr.write(f"Error: Missing framework directory '{_framework_pkg_dir}'\n")
    env.Exit(1)
FRAMEWORK_DIR_PATH = Path(_framework_pkg_dir).resolve()
FRAMEWORK_DIR = str(FRAMEWORK_DIR_PATH)
TOOLCHAIN_DIR = platform.get_package_dir(
    "toolchain-xtensa-esp-elf"
    if mcu in ("esp32", "esp32s2", "esp32s3")
    else "toolchain-riscv32-esp"
)
PLATFORMIO_DIR = env.subst("$PROJECT_CORE_DIR")

if not TOOLCHAIN_DIR or not os.path.isdir(TOOLCHAIN_DIR):
    sys.stderr.write(f"Error: Missing toolchain directory '{TOOLCHAIN_DIR}'\n")
    env.Exit(1)


def get_framework_version():
    def _extract_from_cmake_version_file():
        version_cmake_file = str(Path(FRAMEWORK_DIR) / "tools" / "cmake" / "version.cmake")
        if not os.path.isfile(version_cmake_file):
            return

        with open(version_cmake_file, encoding="utf8") as fp:
            pattern = r"set\(IDF_VERSION_(MAJOR|MINOR|PATCH) (\d+)\)"
            matches = re.findall(pattern, fp.read())
            if len(matches) != 3:
                return
            # If found all three parts of the version
            return ".".join([match[1] for match in matches])

    pkg = platform.get_package("framework-espidf")
    version = get_original_version(str(pkg.metadata.version.truncate()))
    if not version:
        # Fallback value extracted directly from the cmake version file
        version = _extract_from_cmake_version_file()
        if not version:
            version = "0.0.0"

    # Normalize to semver (handles "6.0.0-rc1", VCS metadata, etc.)
    try:
        coerced = semantic_version.Version.coerce(version, partial=True)
        major = coerced.major or 0
        minor = coerced.minor or 0
        patch = coerced.patch or 0
        return f"{major}.{minor}.{patch}"
    except (ValueError, TypeError):
        m = re.match(r"(\d+)\.(\d+)\.(\d+)", str(version))
        return ".".join(m.groups()) if m else "0.0.0"


# Configure ESP-IDF version environment variables
framework_version = get_framework_version()
_mv = framework_version.split(".")
major_version = f"{_mv[0]}.{_mv[1] if len(_mv) > 1 else '0'}"
os.environ["ESP_IDF_VERSION"] = major_version


def create_silent_action(action_func):
    """Create a silent SCons action that suppresses output"""
    silent_action = env.Action(action_func)
    silent_action.strfunction = lambda target, source, env: ''
    return silent_action

if "arduino" in env.subst("$PIOFRAMEWORK"):
    _arduino_pkg_dir = platform.get_package_dir("framework-arduinoespressif32")
    if not _arduino_pkg_dir or not os.path.isdir(_arduino_pkg_dir):
        sys.stderr.write(f"Error: Missing Arduino framework directory '{_arduino_pkg_dir}'\n")
        env.Exit(1)
    arduino_pkg_dir = Path(_arduino_pkg_dir)
    if "@" in arduino_pkg_dir.name:
        new_dir = arduino_pkg_dir.with_name(arduino_pkg_dir.name.replace("@", "-"))
        if new_dir.exists():
            arduino_pkg_dir = new_dir
        else:
            os.rename(str(arduino_pkg_dir), str(new_dir))
            arduino_pkg_dir = new_dir
    ARDUINO_FRAMEWORK_DIR_PATH = arduino_pkg_dir.resolve()
    ARDUINO_FRAMEWORK_DIR = str(ARDUINO_FRAMEWORK_DIR_PATH)
    if not ARDUINO_FRAMEWORK_DIR or not os.path.isdir(ARDUINO_FRAMEWORK_DIR):
        sys.stderr.write(f"Error: Arduino framework directory not found: {ARDUINO_FRAMEWORK_DIR}\n")
        env.Exit(1)

    _arduino_lib_dir = platform.get_package_dir("framework-arduinoespressif32-libs")
    if not _arduino_lib_dir:
        sys.stderr.write("Error: Missing framework-arduinoespressif32-libs package\n")
        env.Exit(1)
    arduino_lib_dir = Path(_arduino_lib_dir)
    ARDUINO_FRMWRK_LIB_DIR_PATH = arduino_lib_dir.resolve()
    ARDUINO_FRMWRK_LIB_DIR = str(ARDUINO_FRMWRK_LIB_DIR_PATH)

    if mcu == "esp32c2" and "espidf" not in pio_orig_frwrk:
        ARDUINO_FRMWRK_C2_LIB_DIR = str(ARDUINO_FRMWRK_LIB_DIR_PATH / chip_variant)
        if not os.path.exists(ARDUINO_FRMWRK_C2_LIB_DIR):
            _arduino_c2_dir = platform.get_package_dir("framework-arduino-c2-skeleton-lib")
            if not _arduino_c2_dir:
                sys.stderr.write("Error: Missing framework-arduino-c2-skeleton-lib package\n")
                env.Exit(1)
            arduino_c2_dir = Path(_arduino_c2_dir)
            ARDUINO_C2_DIR = str(arduino_c2_dir / chip_variant)
            shutil.copytree(ARDUINO_C2_DIR, ARDUINO_FRMWRK_C2_LIB_DIR, dirs_exist_ok=True)

    if mcu == "esp32c61" and "espidf" not in pio_orig_frwrk:
        ARDUINO_FRMWRK_C61_LIB_DIR = str(ARDUINO_FRMWRK_LIB_DIR_PATH / chip_variant)
        if not os.path.exists(ARDUINO_FRMWRK_C61_LIB_DIR):
            _arduino_c61_dir = platform.get_package_dir("framework-arduino-c61-skeleton-lib")
            if not _arduino_c61_dir:
                sys.stderr.write("Error: Missing framework-arduino-c61-skeleton-lib package\n")
                env.Exit(1)
            arduino_c61_dir = Path(_arduino_c61_dir)
            ARDUINO_C61_DIR = str(arduino_c61_dir / chip_variant)
            shutil.copytree(ARDUINO_C61_DIR, ARDUINO_FRMWRK_C61_LIB_DIR, dirs_exist_ok=True)

    arduino_libs_mcu = str(ARDUINO_FRMWRK_LIB_DIR_PATH / chip_variant)

BUILD_DIR = env.subst("$BUILD_DIR")
PROJECT_DIR = env.subst("$PROJECT_DIR")
PROJECT_SRC_DIR = env.subst("$PROJECT_SRC_DIR")
CMAKE_API_REPLY_PATH = str(Path(".cmake") / "api" / "v1" / "reply")
SDKCONFIG_PATH = os.path.expandvars(board.get(
        "build.esp-idf.sdkconfig_path",
        str(Path(PROJECT_DIR) / ("sdkconfig.%s" % env.subst("$PIOENV"))),
))

def contains_path_traversal(url):
    """Best-effort detection of path traversal sequences."""
    path = unquote(unquote(urlsplit(url).path)).replace("\\", "/")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    return any(p == ".." for p in parts)

#
# generate modified Arduino IDF sdkconfig, applying settings from "custom_sdkconfig"
#
if config.has_option("env:"+env["PIOENV"], "custom_component_add"):
    flag_custom_component_add = True
if config.has_option("env:"+env["PIOENV"], "custom_component_remove"):
    flag_custom_component_remove = True

if config.has_option("env:"+env["PIOENV"], "custom_sdkconfig"):
    flag_custom_sdkonfig = True
if "espidf.custom_sdkconfig" in board:
    flag_custom_sdkonfig = True

# Disable HybridCompile for espidf and arduino, espidf projects
# HybridCompile is always "framework = arduino" !
if "espidf" in pio_orig_frwrk:
    flag_custom_sdkonfig = False

# Check for board-specific configurations that require sdkconfig generation
def has_board_specific_config():
    """Check if board has configuration that needs to be applied to sdkconfig."""
    # Check for PSRAM support
    extra_flags = board.get("build.extra_flags", [])
    has_psram = any("-DBOARD_HAS_PSRAM" in flag for flag in extra_flags)
    
    # Check for special memory types  
    memory_type = None
    build_section = board.get("build", {})
    arduino_section = build_section.get("arduino", {})
    if "memory_type" in arduino_section:
        memory_type = arduino_section["memory_type"]
    elif "memory_type" in build_section:
        memory_type = build_section["memory_type"]
    has_special_memory = memory_type and ("opi" in memory_type.lower())
    
    return has_psram or has_special_memory

def HandleArduinoIDFsettings(env):
    """
    Handles Arduino IDF settings configuration with custom sdkconfig support.
    """
    
    def get_MD5_hash(phrase):
        """Generate MD5 hash for checksum validation."""
        import hashlib
        return hashlib.md5(phrase.encode('utf-8')).hexdigest()[:16]

    def load_custom_sdkconfig_file():
        """Load custom sdkconfig from file or URL if specified."""
        if not config.has_option("env:" + env["PIOENV"], "custom_sdkconfig"):
            return ""
        
        sdkconfig_entries = env.GetProjectOption("custom_sdkconfig").splitlines()
        
        for file_entry in sdkconfig_entries:
            # Handle HTTP/HTTPS URLs
            if "http" in file_entry and "://" in file_entry:
                url = file_entry.split(" ")[0]
                # Path Traversal protection
                if contains_path_traversal(url):
                    print(f"Path Traversal detected: {url} check your URL path")
                else:
                    try:
                        response = requests.get(file_entry.split(" ")[0], timeout=10)
                        if response.ok:
                            return response.content.decode('utf-8')
                    except requests.RequestException as e:
                        print(f"Error downloading {file_entry}: {e}")
                    except UnicodeDecodeError as e:
                        print(f"Error decoding response from {file_entry}: {e}")
                        return ""
            
            # Handle local files
            if "file://" in file_entry:
                file_ref = file_entry[7:] if file_entry.startswith("file://") else file_entry

                if os.path.isabs(file_ref):
                    file_path = file_ref
                else:
                    # if it's a relative path, try relative to PROJECT_DIR
                    file_path = str(Path(PROJECT_DIR) / file_ref)
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r') as f:
                            return f.read()
                    except IOError as e:
                        print(f"Error reading file {file_path}: {e}")
                        return ""
                else:
                    print("File not found, check path:", file_path)
                    return ""
        
        return ""

    def extract_flag_name(line):
        """Extract flag name from sdkconfig line."""
        line = line.strip()
        if line.startswith("#") and "is not set" in line:
            return line.split(" ")[1]
        elif not line.startswith("#") and "=" in line:
            return line.split("=")[0]
        return None

    def generate_board_specific_config():
        """Generate board-specific sdkconfig settings from board.json manifest."""
        board_config_flags = []

        # Handle memory type configuration with platformio.ini override support
        # Priority: platformio.ini > board.json manifest
        memory_type = None
        
        # Check for memory_type override in platformio.ini
        if hasattr(env, 'GetProjectOption'):
            try:
                memory_type = env.GetProjectOption("board_build.memory_type", None)
            except:
                pass
        
        # Fallback to board.json manifest
        if not memory_type:
            build_section = board.get("build", {})
            arduino_section = build_section.get("arduino", {})
            if "memory_type" in arduino_section:
                memory_type = arduino_section["memory_type"]
            elif "memory_type" in build_section:
                memory_type = build_section["memory_type"]

        flash_memory_type = None
        psram_memory_type = None
        if memory_type:
            parts = memory_type.split("_")
            if len(parts) == 2:
                flash_memory_type, psram_memory_type = parts
            else:
                flash_memory_type = memory_type

        # Add flash mode to sdkconfig
        if flash_mode:
            flash_mode_lower = flash_mode.lower()
            board_config_flags.append(f"CONFIG_ESPTOOLPY_FLASHMODE_{flash_mode.upper()}=y")

            # Disable other flash mode options
            flash_modes = ["qio", "qout", "dio", "dout"]
            for mode in flash_modes:
                if mode != flash_mode_lower:
                    board_config_flags.append(f"# CONFIG_ESPTOOLPY_FLASHMODE_{mode.upper()} is not set")

        # Override flash_memory_type if boot mode indicates OPI
        if boot_mode == "opi" or flash_mode in ["dout", "opi"]:
            if not flash_memory_type or flash_memory_type.lower() != "opi":
                flash_memory_type = "opi"
                print(f"Info: Detected OPI Flash via boot_mode='{boot_mode}' or flash_mode='{flash_mode}'")

        # Set CPU frequency with platformio.ini override support
        # Priority: platformio.ini > board.json manifest
        f_cpu = None
        if hasattr(env, 'GetProjectOption'):
            # Check for board_build.f_cpu override in platformio.ini
            try:
                f_cpu = env.GetProjectOption("board_build.f_cpu", None)
            except:
                pass
        
        # Fallback to board.json manifest
        if not f_cpu:
            f_cpu = board.get("build.f_cpu", None)
        
        if f_cpu:
            cpu_freq = str(f_cpu).replace("000000L", "")
            board_config_flags.append(f"CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ={cpu_freq}")
            
            # MCU name mapping for config flags (uppercase MCU name)
            mcu_upper = mcu.upper().replace("-", "")
            
            # Disable other CPU frequency options and enable the specific one
            common_cpu_freqs = ["80", "160", "240"]
            for freq in common_cpu_freqs:
                if freq != cpu_freq:
                    board_config_flags.append(f"# CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_{freq} is not set")
                    board_config_flags.append(f"# CONFIG_{mcu_upper}_DEFAULT_CPU_FREQ_{freq} is not set")
            
            # Enable the specific CPU frequency (both generic and MCU-specific)
            board_config_flags.append(f"CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_{cpu_freq}=y")
            board_config_flags.append(f"CONFIG_{mcu_upper}_DEFAULT_CPU_FREQ_{cpu_freq}=y")

        # Set flash size with platformio.ini override support
        # Priority: platformio.ini > board.json manifest
        flash_size = None
        if hasattr(env, 'GetProjectOption'):
            # Check for board_upload.flash_size override in platformio.ini
            try:
                flash_size = env.GetProjectOption("board_upload.flash_size", None)
            except:
                pass
        
        # Fallback to board.json manifest
        if not flash_size:
            flash_size = board.get("upload", {}).get("flash_size", None)
        
        if flash_size:
            # Configure both string and boolean flash size formats
            # Disable other flash size options first
            flash_sizes = ["4MB", "8MB", "16MB", "32MB", "64MB", "128MB"]
            for size in flash_sizes:
                if size != flash_size:
                    board_config_flags.append(f"# CONFIG_ESPTOOLPY_FLASHSIZE_{size} is not set")
            
            # Set the specific flash size configs
            board_config_flags.append(f"CONFIG_ESPTOOLPY_FLASHSIZE=\"{flash_size}\"")
            board_config_flags.append(f"CONFIG_ESPTOOLPY_FLASHSIZE_{flash_size}=y")

        # Handle Flash and PSRAM frequency configuration with platformio.ini override support
        # Priority: platformio.ini > board.json manifest
        # From 80MHz onwards, Flash and PSRAM frequencies must be identical
        
        # Get f_flash with override support
        f_flash = None
        if hasattr(env, 'GetProjectOption'):
            try:
                f_flash = env.GetProjectOption("board_build.f_flash", None)
            except:
                pass
        if not f_flash:
            f_flash = board.get("build.f_flash", None)
        
        # Get f_boot with override support
        f_boot = None
        if hasattr(env, 'GetProjectOption'):
            try:
                f_boot = env.GetProjectOption("board_build.f_boot", None)
            except:
                pass
        if not f_boot:
            f_boot = board.get("build.f_boot", None)
        
        # Get f_psram with override support (ESP32-P4 specific)
        f_psram = None
        if hasattr(env, 'GetProjectOption'):
            try:
                f_psram = env.GetProjectOption("board_build.f_psram", None)
            except:
                pass
        if not f_psram:
            f_psram = board.get("build.f_psram", None)
        
        # Determine the frequencies to use
        # ESP32-P4: f_flash for Flash, f_psram for PSRAM (doesn't affect bootloader name)
        
        if mcu == "esp32p4":
            # ESP32-P4: f_flash is always used for Flash frequency
            # f_psram is used for PSRAM frequency (if set), otherwise use f_flash
            # Note: f_boot is NOT used for P4 as it affects bootloader filename
            flash_compile_freq = f_flash
            psram_compile_freq = f_psram if f_psram else f_flash

            if chip_variant == "esp32p4_es":
                print(f"Info: Detected ESP32-P4 ES variant, applying revision-based compatibility flags")
                board_config_flags.append("CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y")
                board_config_flags.append("# CONFIG_ESP32P4_REV_MIN_0 is not set")
                board_config_flags.append("CONFIG_ESP32P4_REV_MIN_1=y")
                board_config_flags.append("# CONFIG_ESP32P4_REV_MIN_100 is not set")
                board_config_flags.append("CONFIG_ESP32P4_REV_MIN_FULL=1")
                board_config_flags.append("CONFIG_ESP_REV_MIN_FULL=1")

        else:
            # Other chips: f_boot overrides f_flash for compile-time (both Flash and PSRAM)
            compile_freq = f_boot if f_boot else f_flash
            flash_compile_freq = compile_freq
            psram_compile_freq = compile_freq

        if f_flash and flash_compile_freq and psram_compile_freq:
            # Validate and parse frequency values
            try:
                flash_freq_val = int(str(flash_compile_freq).replace("000000L", ""))
                psram_freq_val = int(str(psram_compile_freq).replace("000000L", ""))
            except (ValueError, AttributeError):
                print("Warning: Invalid frequency values, skipping frequency configuration")
                flash_freq_val = None
                psram_freq_val = None
            
            if flash_freq_val and psram_freq_val:
                # Determine frequency strings
                flash_freq_str = f"{flash_freq_val}m"
                psram_freq_str = str(psram_freq_val)
                
                # Info message
                if mcu == "esp32p4":
                    print(f"Info: ESP32-P4 frequency mode: Flash={flash_freq_val}MHz, PSRAM={psram_freq_val}MHz")
                elif flash_freq_val >= 80:
                    print(f"Info: Unified frequency mode (>= 80MHz): {flash_freq_val}MHz for both Flash and PSRAM")
                else:
                    print(f"Info: Independent frequency mode (< 80MHz): Flash={flash_freq_str}, PSRAM={psram_freq_str}")
                
                # Configure Flash frequency
                # Disable other flash frequency options first
                flash_freqs = ["20m", "26m", "40m", "80m", "120m"]
                for freq in flash_freqs:
                    if freq != flash_freq_str:
                        board_config_flags.append(f"# CONFIG_ESPTOOLPY_FLASHFREQ_{freq.upper()} is not set")
                # Then set the specific frequency configs
                board_config_flags.append(f"CONFIG_ESPTOOLPY_FLASHFREQ=\"{flash_freq_str}\"")
                board_config_flags.append(f"CONFIG_ESPTOOLPY_FLASHFREQ_{flash_freq_str.upper()}=y")
                
                # ESP32-P4 requires additional FLASHFREQ_VAL setting
                if mcu == "esp32p4":
                    board_config_flags.append(f"CONFIG_ESPTOOLPY_FLASHFREQ_VAL={flash_freq_val}")
                
                # Configure PSRAM frequency
                # Disable other SPIRAM speed options first
                psram_freqs = ["20", "40", "80", "120", "200"]
                for freq in psram_freqs:
                    if freq != psram_freq_str:
                        board_config_flags.append(f"# CONFIG_SPIRAM_SPEED_{freq}M is not set")
                # Then set the specific SPIRAM configs
                board_config_flags.append(f"CONFIG_SPIRAM_SPEED={psram_freq_str}")
                board_config_flags.append(f"CONFIG_SPIRAM_SPEED_{psram_freq_str}M=y")
                
                # Enable experimental features for Flash frequencies > 80MHz
                if flash_freq_val > 80:
                    board_config_flags.append("CONFIG_IDF_EXPERIMENTAL_FEATURES=y")
                    board_config_flags.append("CONFIG_SPI_FLASH_HPM_ENABLE=y")
                    board_config_flags.append("CONFIG_SPI_FLASH_HPM_AUTO=y")

        # Check for PSRAM support based on board flags
        extra_flags = board.get("build.extra_flags", "")
        # Handle both string and list formats
        if isinstance(extra_flags, str):
            has_psram = "-DBOARD_HAS_PSRAM" in extra_flags
        else:
            has_psram = any("-DBOARD_HAS_PSRAM" in flag for flag in extra_flags)
        
        # Additional PSRAM detection methods
        if not has_psram:
            # Check if memory_type contains psram indicators
            if memory_type and ("opi" in memory_type.lower() or "psram" in memory_type.lower()):
                has_psram = True
            # Check build.psram_type
            elif "psram_type" in board.get("build", {}):
                has_psram = True
            # Check for SPIRAM mentions in extra_flags
            elif isinstance(extra_flags, str) and "PSRAM" in extra_flags:
                has_psram = True
            elif not isinstance(extra_flags, str) and any("PSRAM" in str(flag) for flag in extra_flags):
                has_psram = True
        
        if has_psram:
            # Enable basic SPIRAM support
            board_config_flags.append("CONFIG_SPIRAM=y")
            
            # Determine PSRAM type with platformio.ini override support
            # Priority: platformio.ini > memory_type > build.psram_type > default
            psram_type = None
            
            # Priority 1: Check for platformio.ini override
            if hasattr(env, 'GetProjectOption'):
                try:
                    psram_type = env.GetProjectOption("board_build.psram_type", None)
                    if psram_type:
                        psram_type = psram_type.lower()
                except:
                    pass
            
            # Priority 2: Check psram_memory_type from memory_type field (e.g., "qio_opi")
            if not psram_type and psram_memory_type:
                psram_type = psram_memory_type.lower()
            # Priority 3: Check build.psram_type field as fallback
            elif not psram_type and "psram_type" in board.get("build", {}):
                psram_type = board.get("build.psram_type", "qio").lower()
            # Priority 4: Default based on MCU
            elif not psram_type:
                # ESP32-P4 defaults to HEX (only type available)
                if mcu == "esp32p4":
                    psram_type = "hex"
                else:
                    psram_type = "qio"
            
            # Configure PSRAM mode based on detected type
            if psram_type == "hex":
                # HEX PSRAM configuration (ESP32-P4 only)
                board_config_flags.append("CONFIG_SPIRAM_MODE_HEX=y")
                
            elif psram_type == "opi":
                # Octal PSRAM configuration (for ESP32-S3)
                if mcu == "esp32s3":
                    board_config_flags.extend([
                        "CONFIG_IDF_EXPERIMENTAL_FEATURES=y",
                        "# CONFIG_SPIRAM_MODE_QUAD is not set",
                        "CONFIG_SPIRAM_MODE_OCT=y",
                        "CONFIG_SPIRAM_TYPE_AUTO=y"
                    ])
                else:
                    # Fallback to QUAD for other chips
                    board_config_flags.extend([
                        "# CONFIG_SPIRAM_MODE_OCT is not set",
                        "CONFIG_SPIRAM_MODE_QUAD=y"
                    ])
                    
            elif psram_type in ["qio", "qspi"]:
                # Quad PSRAM configuration
                if mcu in ["esp32s2", "esp32s3"]:
                    board_config_flags.extend([
                        "# CONFIG_SPIRAM_MODE_OCT is not set",
                        "CONFIG_SPIRAM_MODE_QUAD=y"
                    ])
                elif mcu == "esp32":
                    board_config_flags.extend([
                        "# CONFIG_SPIRAM_MODE_OCT is not set",
                        "# CONFIG_SPIRAM_MODE_QUAD is not set"
                    ])
        else:
            # Explicitly disable PSRAM if not present
            board_config_flags.extend([
                "# CONFIG_SPIRAM is not set"
            ])

        # Use flash_memory_type for flash config
        if flash_memory_type and "opi" in flash_memory_type.lower():
            # OPI Flash configurations require specific settings
            # According to ESP-IDF documentation, OPI flash must use DOUT mode for bootloader
            # The bootloader starts in DOUT mode and switches to OPI at runtime
            # Reference: ESP-IDF Programming Guide - SPI Flash Configuration
            board_config_flags.extend([
                "# CONFIG_ESPTOOLPY_FLASHMODE_QIO is not set",
                "# CONFIG_ESPTOOLPY_FLASHMODE_QOUT is not set",
                "# CONFIG_ESPTOOLPY_FLASHMODE_DIO is not set",
                "CONFIG_ESPTOOLPY_FLASHMODE_DOUT=y",
                "CONFIG_ESPTOOLPY_OCT_FLASH=y",
                "# CONFIG_ESPTOOLPY_FLASH_SAMPLE_MODE_STR is not set",
                "CONFIG_ESPTOOLPY_FLASH_SAMPLE_MODE_DTR=y"
            ])

        return board_config_flags

    def build_idf_config_flags():
        """Build complete IDF configuration flags from all sources."""
        flags = []
        
        # FIRST: Add board-specific flags derived from board.json manifest
        board_flags = generate_board_specific_config()
        if board_flags:
            flags.extend(board_flags)
        
        # SECOND: Add board-specific flags from board manifest (espidf.custom_sdkconfig)
        if "espidf.custom_sdkconfig" in board:
            board_manifest_flags = board.get("espidf.custom_sdkconfig", [])
            if board_manifest_flags:
                flags.extend(board_manifest_flags)
        
        # THIRD: Add custom sdkconfig file content
        custom_file_content = load_custom_sdkconfig_file()
        if custom_file_content:
            flags.append(custom_file_content)
        
        # FOURTH: Add project-level custom sdkconfig (highest precedence for user overrides)
        if config.has_option("env:" + env["PIOENV"], "custom_sdkconfig"):
            custom_flags = env.GetProjectOption("custom_sdkconfig").rstrip("\n")
            if custom_flags:
                flags.append(custom_flags)
        
        # FIFTH: Apply ESP32-specific compatibility fixes
        all_flags_str = "\n".join(flags) + "\n" if flags else ""
        esp32_compatibility_flags = apply_esp32_compatibility_fixes(all_flags_str)
        if esp32_compatibility_flags:
            flags.extend(esp32_compatibility_flags)
        
        return "\n".join(flags) + "\n" if flags else ""

    def apply_esp32_compatibility_fixes(config_flags_str):
        """Apply ESP32-specific compatibility fixes based on final configuration."""
        compatibility_flags = []
        
        # ESP32 specific SPIRAM configuration
        # On ESP32, SPIRAM is not used with UNICORE mode
        if mcu == "esp32" and "CONFIG_FREERTOS_UNICORE=y" in config_flags_str:
            if "CONFIG_SPIRAM=y" in config_flags_str:
                compatibility_flags.append("# CONFIG_SPIRAM is not set")
                print("Info: ESP32 SPIRAM disabled since solo1 core mode is enabled")
        
        return compatibility_flags


    def write_sdkconfig_file(idf_config_flags, checksum_source):
        if "arduino" not in env.subst("$PIOFRAMEWORK"):
            print("Error: Arduino framework required for sdkconfig processing")
            return
        """Write the final sdkconfig.defaults file with checksum."""
        sdkconfig_src = str(Path(arduino_libs_mcu) / "sdkconfig")
        sdkconfig_dst = str(Path(PROJECT_DIR) / "sdkconfig.defaults")
        if not os.path.isfile(sdkconfig_src):
            sys.stderr.write(f"Error: Missing Arduino sdkconfig template at '{sdkconfig_src}'\n")
            env.Exit(1)
        
        # Generate checksum for validation (maintains original logic)
        checksum = get_MD5_hash(checksum_source.strip() + mcu)
        
        with open(sdkconfig_src, 'r', encoding='utf-8') as src, open(sdkconfig_dst, 'w', encoding='utf-8') as dst:
            # Write checksum header (critical for compilation decision logic)
            dst.write(f"# TASMOTA__{checksum}\n")
            
            # Process each line from source sdkconfig
            src_lines = src.readlines()
            
            for line in src_lines:
                flag_name = extract_flag_name(line)
                
                if flag_name is None:
                    dst.write(line)
                    continue
                
                # Check if we have a custom replacement for this flag
                flag_replaced = False
                for custom_flag in idf_config_flags[:]:  # Create copy for safe removal
                    custom_flag_name = extract_flag_name(custom_flag.replace("'", ""))
                    
                    if flag_name == custom_flag_name:
                        cleaned_flag = custom_flag.replace("'", "")
                        dst.write(cleaned_flag + "\n")
                        print(f"Replace: {line.strip()} with: {cleaned_flag}")
                        idf_config_flags.remove(custom_flag)
                        flag_replaced = True
                        break
                
                if not flag_replaced:
                    dst.write(line)
            
            # Add any remaining new flags
            for remaining_flag in idf_config_flags:
                cleaned_flag = remaining_flag.replace("'", "")
                print(f"Add: {cleaned_flag}")
                dst.write(cleaned_flag + "\n")

    
    # Main execution logic
    has_custom_config = (
        config.has_option("env:" + env["PIOENV"], "custom_sdkconfig") or
        "espidf.custom_sdkconfig" in board
    )
    
    has_board_config = has_board_specific_config()
    
    if not has_custom_config and not has_board_config:
        return
    
    if has_board_config and not has_custom_config:
        print("*** Apply board-specific settings to IDF sdkconfig.defaults ***")
    else:
        print("*** Add \"custom_sdkconfig\" settings to IDF sdkconfig.defaults ***")
    
    # Build complete configuration
    idf_config_flags = build_idf_config_flags()
    
    # Convert to list for processing
    idf_config_list = [line for line in idf_config_flags.splitlines() if line.strip()]
    
    # Write final configuration file with checksum
    custom_sdk_config_flags = ""
    if config.has_option("env:" + env["PIOENV"], "custom_sdkconfig"):
        custom_sdk_config_flags = env.GetProjectOption("custom_sdkconfig").rstrip("\n") + "\n"
    
    write_sdkconfig_file(idf_config_list, custom_sdk_config_flags)



def HandleCOMPONENTsettings(env):
    from component_manager import ComponentManager
    component_manager = ComponentManager(env)

    if flag_custom_component_add or flag_custom_component_remove:
        actions = [action for flag, action in [
            (flag_custom_component_add, "select"),
            (flag_custom_component_remove, "deselect")
        ] if flag]
        action_text = " and ".join(actions)
        print(f"*** \"custom_component\" is used to {action_text} managed idf components ***")

        component_manager.handle_component_settings(
            add_components=flag_custom_component_add,
            remove_components=flag_custom_component_remove
        )
        return
    return

if "arduino" in env.subst("$PIOFRAMEWORK"):
    HandleCOMPONENTsettings(env)

if flag_custom_sdkonfig == True and "arduino" in env.subst("$PIOFRAMEWORK") and "espidf" not in env.subst("$PIOFRAMEWORK"):
    HandleArduinoIDFsettings(env)
    LIB_SOURCE = str(Path(platform.get_dir()) / "builder" / "build_lib")
    if not bool(os.path.exists(str(Path(PROJECT_DIR) / ".dummy"))):
        shutil.copytree(LIB_SOURCE, str(Path(PROJECT_DIR) / ".dummy"))
    PROJECT_SRC_DIR = str(Path(PROJECT_DIR) / ".dummy")
    env.Replace(
        PROJECT_SRC_DIR=PROJECT_SRC_DIR,
        BUILD_FLAGS="",
        BUILD_UNFLAGS="",
        LINKFLAGS="",
        PIOFRAMEWORK="arduino",
        ARDUINO_LIB_COMPILE_FLAG="Build",
    )
    env["INTEGRATION_EXTRA_DATA"].update({"arduino_lib_compile_flag": env.subst("$ARDUINO_LIB_COMPILE_FLAG")})

def get_project_lib_includes(env):
    project = ProjectAsLibBuilder(env, "$PROJECT_DIR")
    project.install_dependencies()
    project.search_deps_recursive()

    paths = []
    for lb in env.GetLibBuilders():
        if not lb.dependent:
            continue
        lb.env.PrependUnique(CPPPATH=lb.get_include_dirs())
        paths.extend(lb.env["CPPPATH"])

    DefaultEnvironment().Replace(__PIO_LIB_BUILDERS=None)

    return paths

def is_cmake_reconfigure_required(cmake_api_reply_dir):
    cmake_cache_file = str(Path(BUILD_DIR) / "CMakeCache.txt")
    cmake_txt_files = [
        str(Path(PROJECT_DIR) / "CMakeLists.txt"),
        str(Path(PROJECT_SRC_DIR) / "CMakeLists.txt"),
    ]
    cmake_preconf_dir = str(Path(BUILD_DIR) / "config")
    default_sdk_config = str(Path(PROJECT_DIR) / "sdkconfig.defaults")
    idf_deps_lock = str(Path(PROJECT_DIR) / "dependencies.lock")
    ninja_buildfile = str(Path(BUILD_DIR) / "build.ninja")

    for d in (cmake_api_reply_dir, cmake_preconf_dir):
        if not os.path.isdir(d) or not os.listdir(d):
            return True
    if not os.path.isfile(cmake_cache_file):
        return True
    if not os.path.isfile(ninja_buildfile):
        return True
    if not os.path.isfile(SDKCONFIG_PATH) or os.path.getmtime(
        SDKCONFIG_PATH
    ) > os.path.getmtime(cmake_cache_file):
        return True
    if os.path.isfile(default_sdk_config) and os.path.getmtime(
        default_sdk_config
    ) > os.path.getmtime(cmake_cache_file):
        return True
    if os.path.isfile(idf_deps_lock) and os.path.getmtime(
        idf_deps_lock
    ) > os.path.getmtime(ninja_buildfile):
        return True
    if any(
        os.path.getmtime(f) > os.path.getmtime(cmake_cache_file)
        for f in cmake_txt_files + [cmake_preconf_dir, FRAMEWORK_DIR]
    ):
        return True

    return False


def is_proper_idf_project():
    return all(
        os.path.isfile(path)
        for path in (
            str(Path(PROJECT_DIR) / "CMakeLists.txt"),
            str(Path(PROJECT_SRC_DIR) / "CMakeLists.txt"),
        )
    )


def collect_src_files():
    return [
        f
        for f in env.MatchSourceFiles("$PROJECT_SRC_DIR", env.get("SRC_FILTER"))
        if not f.endswith((".h", ".hpp"))
    ]


def normalize_path(path):
    if PROJECT_DIR in path:
        path = path.replace(PROJECT_DIR, "${CMAKE_SOURCE_DIR}")
    return fs.to_unix_path(path)


CMK_TOOL = platform.get_package_dir("tool-cmake")
if not CMK_TOOL or not os.path.isdir(CMK_TOOL):
    sys.stderr.write(f"Error: Missing CMake package directory '{CMK_TOOL}'\n")
    env.Exit(1)
CMAKE_DIR = str(Path(CMK_TOOL) / "bin" / "cmake")


def create_default_project_files():
    root_cmake_tpl = """cmake_minimum_required(VERSION 3.16.0)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(%s)
"""
    prj_cmake_tpl = """# This file was automatically generated for projects
# without default 'CMakeLists.txt' file.

FILE(GLOB_RECURSE app_sources %s/*.*)

idf_component_register(SRCS ${app_sources})
"""

    if not os.listdir(PROJECT_SRC_DIR):
        # create a default main file to make CMake happy during first init
        with open(str(Path(PROJECT_SRC_DIR) / "main.c"), "w") as fp:
            fp.write("void app_main() {}")

    project_dir = PROJECT_DIR
    if not os.path.isfile(str(Path(project_dir) / "CMakeLists.txt")):
        with open(str(Path(project_dir) / "CMakeLists.txt"), "w") as fp:
            fp.write(root_cmake_tpl % os.path.basename(project_dir))

    project_src_dir = PROJECT_SRC_DIR
    if not os.path.isfile(str(Path(project_src_dir) / "CMakeLists.txt")):
        with open(str(Path(project_src_dir) / "CMakeLists.txt"), "w") as fp:
            fp.write(prj_cmake_tpl % normalize_path(PROJECT_SRC_DIR))


def get_cmake_code_model(src_dir, build_dir, extra_args=None):
    cmake_api_dir = str(Path(build_dir) / ".cmake" / "api" / "v1")
    cmake_api_query_dir = str(Path(cmake_api_dir) / "query")
    cmake_api_reply_dir = str(Path(cmake_api_dir) / "reply")
    query_file = str(Path(cmake_api_query_dir) / "codemodel-v2")

    if not os.path.isfile(query_file):
        Path(cmake_api_query_dir).mkdir(parents=True, exist_ok=True)
        Path(query_file).touch()

    if not is_proper_idf_project():
        create_default_project_files()

    if is_cmake_reconfigure_required(cmake_api_reply_dir):
        run_cmake(src_dir, build_dir, extra_args)

    if not os.path.isdir(cmake_api_reply_dir) or not os.listdir(cmake_api_reply_dir):
        sys.stderr.write("Error: Couldn't find CMake API response file\n")
        env.Exit(1)

    codemodel = {}
    for target in os.listdir(cmake_api_reply_dir):
        if target.startswith("codemodel-v2"):
            with open(str(Path(cmake_api_reply_dir) / target), "r") as fp:
                codemodel = json.load(fp)
            break

    if codemodel.get("version", {}).get("major") != 2:
        sys.stderr.write("Error: Unsupported CMake codemodel version (need major=2)\n")
        env.Exit(1)
    return codemodel


def populate_idf_env_vars(idf_env):
    idf_env["IDF_PATH"] = fs.to_unix_path(FRAMEWORK_DIR)
    NINJA_DIR = platform.get_package_dir("tool-ninja")
    if not NINJA_DIR or not os.path.isdir(NINJA_DIR):
        sys.stderr.write(f"Error: Missing ninja package directory '{NINJA_DIR}'\n")
        env.Exit(1)
    additional_packages = [
        str(Path(TOOLCHAIN_DIR) / "bin"),
        NINJA_DIR,
        CMAKE_DIR,
        os.path.dirname(get_python_exe()),
    ]

    idf_env["PATH"] = os.pathsep.join([*additional_packages, idf_env["PATH"]])
    idf_env["ESP_ROM_ELF_DIR"] = platform.get_package_dir("tool-esp-rom-elfs")


def get_target_config(project_configs, target_index, cmake_api_reply_dir):
    target_json = project_configs.get("targets")[target_index].get("jsonFile", "")
    target_config_file = str(Path(cmake_api_reply_dir) / target_json)
    if not os.path.isfile(target_config_file):
        sys.stderr.write("Error: Couldn't find target config %s\n" % target_json)
        env.Exit(1)

    with open(target_config_file) as fp:
        return json.load(fp)


def load_target_configurations(cmake_codemodel, cmake_api_reply_dir):
    configs = {}
    project_configs = cmake_codemodel.get("configurations")[0]
    for config in project_configs.get("projects", []):
        for target_index in config.get("targetIndexes", []):
            target_config = get_target_config(
                project_configs, target_index, cmake_api_reply_dir
            )
            configs[target_config["name"]] = target_config

    return configs


def build_library(
    default_env, lib_config, project_src_dir, prepend_dir=None, debug_allowed=True
):
    lib_name = lib_config["nameOnDisk"]
    lib_path = lib_config["paths"]["build"]
    if prepend_dir:
        lib_path = str(Path(prepend_dir) / lib_path)
    lib_objects = compile_source_files(
        lib_config, default_env, project_src_dir, prepend_dir, debug_allowed
    )
    return default_env.Library(
        target=str(Path("$BUILD_DIR") / lib_path / lib_name), source=lib_objects
    )


def get_app_includes(app_config):
    plain_includes = []
    sys_includes = []
    cg = app_config["compileGroups"][0]
    for inc in cg.get("includes", []):
        inc_path = inc["path"]
        if inc.get("isSystem", False):
            sys_includes.append(inc_path)
        else:
            plain_includes.append(inc_path)

    return {"plain_includes": plain_includes, "sys_includes": sys_includes}


def extract_defines(compile_group):
    def _normalize_define(define_string):
        define_string = define_string.strip()
        if "=" in define_string:
            define, value = define_string.split("=", maxsplit=1)
            if define == "OPENTHREAD_BUILD_DATETIME":
                return None
            if any(char in value for char in (' ', '<', '>')):
                value = f'"{value}"'
            elif '"' in value and not value.startswith("\\"):
                value = value.replace('"', '\\"')
            return (define, value)
        return define_string

    result = [
        _normalize_define(d.get("define", ""))
        for d in compile_group.get("defines", []) if d
    ]

    for f in compile_group.get("compileCommandFragments", []):
        fragment = f.get("fragment", "").strip()
        if fragment.startswith('"'):
            fragment = fragment.strip('"')
        if fragment.startswith("-D"):
            result.append(_normalize_define(fragment[2:]))

    return result


def get_app_defines(app_config):
    return extract_defines(app_config["compileGroups"][0])


def extract_link_args(target_config):
    def _add_to_libpath(lib_path, link_args):
        if lib_path not in link_args["LIBPATH"]:
            link_args["LIBPATH"].append(lib_path)

    def _add_archive(archive_path, link_args):
        archive_name = os.path.basename(archive_path)
        if archive_name not in link_args["LIBS"]:
            _add_to_libpath(os.path.dirname(archive_path), link_args)
            link_args["LIBS"].append(archive_name)

    link_args = {"LINKFLAGS": [], "LIBS": [], "LIBPATH": [], "__LIB_DEPS": []}

    for f in target_config.get("link", {}).get("commandFragments", []):
        fragment = f.get("fragment", "").strip()
        fragment_role = f.get("role", "").strip()
        if not fragment or not fragment_role:
            continue
        args = click.parser.split_arg_string(fragment)
        if fragment_role == "flags":
            link_args["LINKFLAGS"].extend(args)
        elif fragment_role in ("libraries", "libraryPath"):
            if fragment.startswith("-l"):
                link_args["LIBS"].extend(args)
            elif fragment.startswith("-L"):
                lib_path = fragment.replace("-L", "").strip(" '\"")
                _add_to_libpath(lib_path, link_args)
            elif fragment.startswith("-") and not fragment.startswith("-l"):
                # CMake mistakenly marks LINKFLAGS as libraries
                link_args["LINKFLAGS"].extend(args)
            elif fragment.endswith(".a"):
                archive_path = fragment
                # process static archives
                if os.path.isabs(archive_path):
                    # In case of precompiled archives
                    _add_archive(archive_path, link_args)
                else:
                    # In case of archives within project
                    if archive_path.startswith(".."):
                        # Precompiled archives from project component
                        _add_archive(
                            os.path.normpath(str(Path(BUILD_DIR) / archive_path)),
                            link_args,
                        )
                    else:
                        # Internally built libraries used for dependency resolution
                        link_args["__LIB_DEPS"].append(os.path.basename(archive_path))

    return link_args


def filter_args(args, allowed, ignore=None):
    if not allowed:
        return []

    ignore = ignore or []
    result = []
    i = 0
    length = len(args)
    while i < length:
        if any(args[i].startswith(f) for f in allowed) and not any(
            args[i].startswith(f) for f in ignore
        ):
            result.append(args[i])
            if i + 1 < length and not args[i + 1].startswith("-"):
                i += 1
                result.append(args[i])
        i += 1
    return result


def get_app_flags(app_config, default_config):
    def _extract_flags(config):
        flags = {}
        for cg in config["compileGroups"]:
            flags[cg["language"]] = []
            for ccfragment in cg["compileCommandFragments"]:
                fragment = ccfragment.get("fragment", "").strip("\" ")
                if not fragment or fragment.startswith("-D"):
                    continue
                flags[cg["language"]].extend(
                    click.parser.split_arg_string(fragment.strip())
                )

        return flags

    app_flags = _extract_flags(app_config)
    default_flags = _extract_flags(default_config)

    # Flags are sorted because CMake randomly populates build flags in code model
    return {
        "ASPPFLAGS": sorted(app_flags.get("ASM", default_flags.get("ASM"))),
        "CFLAGS": sorted(app_flags.get("C", default_flags.get("C"))),
        "CXXFLAGS": sorted(app_flags.get("CXX", default_flags.get("CXX"))),
    }


def get_sdk_configuration():
    config_path = str(Path(BUILD_DIR) / "config" / "sdkconfig.json")
    if not os.path.isfile(config_path):
        print('Warning: Could not find "sdkconfig.json" file\n')

    try:
        with open(config_path, "r") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}


def load_component_paths(framework_components_dir, ignored_component_prefixes=None):
    def _scan_components_from_framework():
        result = []
        for component in os.listdir(framework_components_dir):
            component_path = str(Path(framework_components_dir) / component)
            if component.startswith(ignored_component_prefixes) or not os.path.isdir(
                component_path
            ):
                continue
            result.append(component_path)

        return result

    # First of all, try to load the list of used components from the project description
    components = []
    ignored_component_prefixes = ignored_component_prefixes or []
    project_description_file = str(Path(BUILD_DIR) / "project_description.json")
    if os.path.isfile(project_description_file):
        with open(project_description_file) as fp:
            try:
                data = json.load(fp)
                for path in data.get("build_component_paths", []):
                    if not os.path.basename(path).startswith(ignored_component_prefixes):
                        components.append(path)
            except (OSError, ValueError) as e:
                print(f"Warning: Could not load components from project description: {e}\n")

    return components or _scan_components_from_framework()


def extract_linker_script_fragments_backup(framework_components_dir, sdk_config):
    # Hardware-specific components are excluded from search and added manually below
    project_components = load_component_paths(
        framework_components_dir, ignored_component_prefixes=("esp32", "riscv")
    )

    result = []
    for component_path in project_components:
        linker_fragment = str(Path(component_path) / "linker.lf")
        if os.path.isfile(linker_fragment):
            result.append(linker_fragment)

    if not result:
        sys.stderr.write("Error: Failed to extract paths to linker script fragments\n")
        env.Exit(1)

    if mcu not in ("esp32", "esp32s2", "esp32s3"):
        result.append(str(Path(framework_components_dir) / "riscv" / "linker.lf"))

    # Add extra linker fragments
    for fragment in (
        str(Path("esp_system") / "app.lf"),
        str(Path("esp_common") / "common.lf"),
        str(Path("esp_common") / "soc.lf"),
        str(Path("newlib") / "system_libs.lf"),
        str(Path("newlib") / "newlib.lf"),
    ):
        result.append(str(Path(framework_components_dir) / fragment))

    if sdk_config.get("SPIRAM_CACHE_WORKAROUND", False):
        result.append(
            str(Path(framework_components_dir) / "newlib" / "esp32-spiram-rom-functions-c.lf")
        )

    if board.get("build.esp-idf.extra_lf_files", ""):
        result.extend(
            [
                lf if os.path.isabs(lf) else str(Path(PROJECT_DIR) / lf)
                for lf in board.get("build.esp-idf.extra_lf_files").splitlines()
                if lf.strip()
            ]
        )

    return result


def extract_linker_script_fragments(
    ninja_buildfile, framework_components_dir, sdk_config
):
    def _normalize_fragment_path(base_dir, fragment_path):
        if not os.path.isabs(fragment_path):
            fragment_path = os.path.abspath(
                str(Path(base_dir) / fragment_path)
            )
        if not os.path.isfile(fragment_path):
            print("Warning! The `%s` fragment is not found!" % fragment_path)

        return fragment_path

    if not os.path.isfile(ninja_buildfile):
        sys.stderr.write(
            "Error: Missing Ninja build file '%s' for linker fragment extraction\n"
            % ninja_buildfile
        )
        env.Exit(1)

    result = []
    with open(ninja_buildfile, encoding="utf8") as fp:
        for line in fp.readlines():
            if "sections.ld: CUSTOM_COMMAND" not in line:
                continue
            for fragment_match in re.finditer(r"(\S+\.lf\b)+", line):
                result.append(_normalize_fragment_path(
                    BUILD_DIR, fragment_match.group(0).replace("$:", ":")
                ))

            break

    # Fall back option if the new algorithm didn't work
    if not result:
        result = extract_linker_script_fragments_backup(
            framework_components_dir, sdk_config
        )

    if board.get("build.esp-idf.extra_lf_files", ""):
        for fragment_path in board.get(
            "build.esp-idf.extra_lf_files"
        ).splitlines():
            if not fragment_path.strip():
                continue
            result.append(_normalize_fragment_path(PROJECT_DIR, fragment_path))

    return result


def create_custom_libraries_list(ldgen_libraries_file, ignore_targets):
    if not os.path.isfile(ldgen_libraries_file):
        sys.stderr.write("Error: Couldn't find the list of framework libraries\n")
        env.Exit(1)

    pio_libraries_file = ldgen_libraries_file + "_pio"

    if os.path.isfile(pio_libraries_file):
        return pio_libraries_file

    lib_paths = []
    with open(ldgen_libraries_file, "r") as fp:
        lib_paths = fp.readlines()

    with open(pio_libraries_file, "w") as fp:
        for lib_path in lib_paths:
            if all(
                "lib%s.a" % t.replace("__idf_", "") not in lib_path
                for t in ignore_targets
            ):
                fp.write(lib_path)

    return pio_libraries_file


def generate_project_ld_script(sdk_config, ignore_targets=None):
    ignore_targets = ignore_targets or []
    linker_script_fragments = extract_linker_script_fragments(
        str(Path(BUILD_DIR) / "build.ninja"),
        str(Path(FRAMEWORK_DIR) / "components"),
        sdk_config
    )

    # Create a new file to avoid automatically generated library entry as files
    # from this library are built internally by PlatformIO
    libraries_list = create_custom_libraries_list(
        str(Path(BUILD_DIR) / "ldgen_libraries"), ignore_targets
    )

    args = {
        "script": str(Path(FRAMEWORK_DIR) / "tools" / "ldgen" / "ldgen.py"),
        "config": SDKCONFIG_PATH,
        "fragments": " ".join(
            ['"%s"' % fs.to_unix_path(f) for f in linker_script_fragments]
        ),
        "kconfig": str(Path(FRAMEWORK_DIR) / "Kconfig"),
        "env_file": str(Path("$BUILD_DIR") / "config.env"),
        "libraries_list": libraries_list,
        "objdump": str(Path(TOOLCHAIN_DIR) / "bin" / env.subst("$CC").replace("-gcc", "-objdump")),
    }

    cmd = (
        '"$ESPIDF_PYTHONEXE" "{script}" --input $SOURCE '
        '--config "{config}" --fragments {fragments} --output $TARGET '
        '--kconfig "{kconfig}" --env-file "{env_file}" '
        '--libraries-file "{libraries_list}" '
        '--objdump "{objdump}"'
    ).format(**args)

    # Select appropriate linker script based on chip and revision
    # ESP32-P4 has different linker scripts for rev < 3 and rev >= 3
    if idf_variant == "esp32p4" and chip_variant == "esp32p4":
        # Regular ESP32-P4 (rev >= 3): use sections.rev3.ld.in
        linker_script_name = "sections.rev3.ld.in"
    else:
        # ESP32-P4 ES variant (rev < 3) or other chips: use sections.ld.in
        linker_script_name = "sections.ld.in"
    
    initial_ld_script = str(Path(FRAMEWORK_DIR) / "components" / "esp_system" / "ld" / idf_variant / linker_script_name)

    framework_version_list = [int(v) for v in get_framework_version().split(".")]
    if framework_version_list[:2] > [5, 2]:
        initial_ld_script = preprocess_linker_file(
            initial_ld_script,
            str(Path(BUILD_DIR) / "esp-idf" / "esp_system" / "ld" / linker_script_name),
        )

    return env.Command(
        str(Path("$BUILD_DIR") / "sections.ld"),
        initial_ld_script,
        env.VerboseAction(cmd, "Generating project linker script $TARGET"),
    )


# A temporary workaround to avoid modifying CMake mainly for the "heap" library.
# The "tlsf.c" source file in this library has an include flag relative
# to CMAKE_CURRENT_SOURCE_DIR which breaks PlatformIO builds that have a
# different working directory
def _fix_component_relative_include(config, build_flags, source_index):
    source_file_path = config["sources"][source_index]["path"]
    build_flags = build_flags.replace("..", os.path.dirname(source_file_path) + "/..")
    return build_flags


def prepare_build_envs(config, default_env, debug_allowed=True):
    build_envs = []
    target_compile_groups = config.get("compileGroups", [])
    if not target_compile_groups:
        print("Warning! The `%s` component doesn't register any source files. "
            "Check if sources are set in component's CMakeLists.txt!" % config["name"]
        )

    is_build_type_debug = "debug" in env.GetBuildType() and debug_allowed
    for cg in target_compile_groups:
        includes = []
        sys_includes = []
        for inc in cg.get("includes", []):
            inc_path = inc["path"]
            if inc.get("isSystem", False):
                sys_includes.append(inc_path)
            else:
                includes.append(inc_path)

        defines = extract_defines(cg)
        compile_commands = cg.get("compileCommandFragments", [])
        build_env = default_env.Clone()
        build_env.SetOption("implicit_cache", 1)
        for cc in compile_commands:
            build_flags = cc.get("fragment", "").strip("\" ")
            if not build_flags.startswith("-D"):
                if build_flags.startswith("-include") and ".." in build_flags:
                    source_index = cg.get("sourceIndexes")[0]
                    build_flags = _fix_component_relative_include(
                        config, build_flags, source_index)
                parsed_flags = build_env.ParseFlags(build_flags)
                build_env.AppendUnique(**parsed_flags)
                if cg.get("language", "") == "ASM":
                    build_env.AppendUnique(ASPPFLAGS=parsed_flags.get("CCFLAGS", []))
        build_env.AppendUnique(CPPDEFINES=defines, CPPPATH=includes)
        if sys_includes:
            build_env.Append(CCFLAGS=[("-isystem", inc) for inc in sys_includes])
        build_env.ProcessUnFlags(default_env.get("BUILD_UNFLAGS"))
        if is_build_type_debug:
            build_env.ConfigureDebugFlags()
        build_envs.append(build_env)

    return build_envs


def compile_source_files(
    config, default_env, project_src_dir, prepend_dir=None, debug_allowed=True
):
    build_envs = prepare_build_envs(config, default_env, debug_allowed)
    objects = []
    # Canonical, symlink-resolved absolute path of the components directory
    components_dir_path = (Path(FRAMEWORK_DIR) / "components").resolve()
    for source in config.get("sources", []):
        src_path = source["path"]
        if src_path.endswith(".rule"):
            continue
        # Always skip dummy_src.c to avoid duplicate build actions
        if os.path.basename(src_path) == "dummy_src.c":
            continue
        compile_group_idx = source.get("compileGroupIndex")
        if compile_group_idx is not None:
            if not os.path.isabs(src_path):
                # For cases when sources are located near CMakeLists.txt
                src_path = str(Path(project_src_dir) / src_path)

            obj_path = str(Path("$BUILD_DIR") / (prepend_dir or ""))
            src_path_obj = Path(src_path).resolve()
            try:
                rel = src_path_obj.relative_to(components_dir_path)
                obj_path = str(Path(obj_path) / str(rel))
            except ValueError:
                # Preserve project substructure when possible
                try:
                    rel_prj = src_path_obj.relative_to(Path(project_src_dir).resolve())
                    obj_path = str(Path(obj_path) / str(rel_prj))
                except ValueError:
                    if not os.path.isabs(source["path"]):
                        obj_path = str(Path(obj_path) / source["path"])
                    else:
                        obj_path = str(Path(obj_path) / os.path.basename(src_path))

            preserve_source_file_extension = board.get(
                "build.esp-idf.preserve_source_file_extension", "yes"
            ) == "yes"

            objects.append(
                build_envs[compile_group_idx].StaticObject(
                    target=(
                        obj_path
                        if preserve_source_file_extension
                        else os.path.splitext(obj_path)[0]
                    ) + ".o",
                    source=str(src_path_obj),
                )
            )

    return objects


def run_tool(cmd):
    idf_env = os.environ.copy()
    populate_idf_env_vars(idf_env)

    result = exec_command(cmd, env=idf_env)
    if result["returncode"] != 0:
        sys.stderr.write(result["out"] + "\n")
        sys.stderr.write(result["err"] + "\n")
        env.Exit(1)

    if int(ARGUMENTS.get("PIOVERBOSE", 0)):
        print(result["out"])
        print(result["err"])


def RunMenuconfig(target, source, env):
    idf_env = os.environ.copy()
    populate_idf_env_vars(idf_env)

    rc = subprocess.call(
        [
            CMAKE_DIR,
            "--build",
            BUILD_DIR,
            "--target",
            "menuconfig",
        ],
        env=idf_env,
    )

    if rc != 0:
        sys.stderr.write("Error: Couldn't execute 'menuconfig' target.\n")
        env.Exit(1)


def run_cmake(src_dir, build_dir, extra_args=None):
    cmd = [
        CMAKE_DIR,
        "-S",
        src_dir,
        "-B",
        build_dir,
        "-G",
        "Ninja",
    ]

    if extra_args:
        cmd.extend(extra_args)

    run_tool(cmd)


def get_lib_ignore_components():
    """
    Get components to ignore from lib_ignore project option using component_manager.
    This ensures consistency with the Arduino framework's lib_ignore handling.
    """
    try:
        # Create a LibraryIgnoreHandler instance to process lib_ignore
        config = _component_manager.ComponentManagerConfig(env)
        logger = _component_manager.ComponentLogger()
        lib_handler = _component_manager.LibraryIgnoreHandler(config, logger)
        
        # Get the processed lib_ignore entries (already converted to component names)
        get_entries = getattr(lib_handler, "get_lib_ignore_entries", None)
        lib_ignore_entries = (
            get_entries() if callable(get_entries) else lib_handler._get_lib_ignore_entries()
        )
        
        return lib_ignore_entries
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        print(f"[ESP-IDF] Warning: Could not process lib_ignore: {e}")
        return []


def find_lib_deps(components_map, elf_config, link_args, ignore_components=None):
    ignore_components = ignore_components or []
    ignore_set = set(ignore_components)
    result = []
    for d in elf_config.get("dependencies", []):
        comp = components_map.get(d["id"])
        if not comp:
            continue
        comp_name = comp["config"]["name"]
        if comp_name in ignore_set:
            continue
        result.append(comp["lib"])

    implicit_lib_deps = link_args.get("__LIB_DEPS", [])
    for component in components_map.values():
        component_config = component["config"]
        if (
            component_config["type"] not in ("STATIC_LIBRARY", "OBJECT_LIBRARY")
            or component_config["name"] in ignore_set
        ):
            continue
        if (
            component_config["nameOnDisk"] in implicit_lib_deps
            and component["lib"] not in result
        ):
            result.append(component["lib"])

    return result


def build_bootloader(sdk_config):
    bootloader_src_dir = str(Path(FRAMEWORK_DIR) / "components" / "bootloader" / "subproject")
    code_model = get_cmake_code_model(
        bootloader_src_dir,
        str(Path(BUILD_DIR) / "bootloader"),
        [
            "-DIDF_TARGET=" + idf_variant,
            "-DPYTHON_DEPS_CHECKED=1",
            "-DPYTHON=" + get_python_exe(),
            "-DIDF_PATH=" + FRAMEWORK_DIR,
            "-DSDKCONFIG=" + SDKCONFIG_PATH,
            "-DPROJECT_SOURCE_DIR=" + PROJECT_DIR,
            "-DLEGACY_INCLUDE_COMMON_HEADERS=",
            "-DEXTRA_COMPONENT_DIRS=" + str(Path(FRAMEWORK_DIR) / "components" / "bootloader"),
            f"-DESP_IDF_VERSION={major_version}",
            f"-DESP_IDF_VERSION_MAJOR={framework_version.split('.')[0]}",
            f"-DESP_IDF_VERSION_MINOR={framework_version.split('.')[1]}",
        ],
    )

    if not code_model:
        sys.stderr.write("Error: Couldn't find code model for bootloader\n")
        env.Exit(1)

    target_configs = load_target_configurations(
        code_model,
        str(Path(BUILD_DIR) / "bootloader" / ".cmake" / "api" / "v1" / "reply"),
    )

    elf_config = get_project_elf(target_configs)
    if not elf_config:
        sys.stderr.write(
            "Error: Couldn't load the main firmware target of the project\n"
        )
        env.Exit(1)

    bootloader_env = env.Clone()
    components_map = get_components_map(
        target_configs, ["STATIC_LIBRARY", "OBJECT_LIBRARY"]
    )

    # Note: By default the size of bootloader is limited to 0x2000 bytes,
    # in debug mode the footprint size can be easily grow beyond this limit
    build_components(
        bootloader_env,
        components_map,
        bootloader_src_dir,
        "bootloader",
        debug_allowed=sdk_config.get("BOOTLOADER_COMPILER_OPTIMIZATION_DEBUG", False),
    )
    link_args = extract_link_args(elf_config)
    extra_flags = filter_args(link_args["LINKFLAGS"], ["-T", "-u"])
    link_args["LINKFLAGS"] = sorted(
        list(set(link_args["LINKFLAGS"]) - set(extra_flags))
    )

    bootloader_env.MergeFlags(link_args)
    
    # Handle ESP-IDF 6.0 linker script preprocessing for .ld.in files
    # In bootloader context, only .ld.in templates exist and need preprocessing
    processed_extra_flags = []
    
    # Bootloader preprocessing configuration
    bootloader_config_dir = str(Path(BUILD_DIR) / "bootloader" / "config")
    bootloader_extra_includes = [
        str(Path(FRAMEWORK_DIR) / "components" / "bootloader" / "subproject" / "main" / "ld" / idf_variant)
    ]

    i = 0
    while i < len(extra_flags):
        if extra_flags[i] == "-T" and i + 1 < len(extra_flags):
            linker_script = extra_flags[i + 1]
            
            # Process .ld.in templates directly
            if linker_script.endswith(".ld.in"):
                script_name = os.path.basename(linker_script).replace(".ld.in", ".ld")
                target_script = str(Path(BUILD_DIR) / "bootloader" / script_name)
                
                preprocessed_script = preprocess_linker_file(
                    linker_script,
                    target_script,
                    config_dir=bootloader_config_dir,
                    extra_include_dirs=bootloader_extra_includes
                )
                
                bootloader_env.Depends("$BUILD_DIR/bootloader.elf", preprocessed_script)
                processed_extra_flags.extend(["-T", target_script])
            # Handle .ld files - prioritize using original scripts when available
            elif linker_script.endswith(".ld"):
                script_basename = os.path.basename(linker_script)
                
                # Check if the original .ld file exists in framework and use it directly
                original_script_path = str(Path(FRAMEWORK_DIR) / "components" / "bootloader" / "subproject" / "main" / "ld" / idf_variant / script_basename)
                
                if os.path.isfile(original_script_path):
                    # Use the original script directly - no preprocessing needed
                    processed_extra_flags.extend(["-T", original_script_path])
                else:
                    # Only generate from template if no original .ld file exists
                    script_name_in = script_basename.replace(".ld", ".ld.in")
                    bootloader_script_in_path = str(Path(FRAMEWORK_DIR) / "components" / "bootloader" / "subproject" / "main" / "ld" / idf_variant / script_name_in)
                    
                    # ESP32-P4 specific: Check for bootloader.rev3.ld.in
                    if idf_variant == "esp32p4" and chip_variant == "esp32p4":
                        bootloader_rev3_path = str(Path(FRAMEWORK_DIR) / "components" / "bootloader" / "subproject" / "main" / "ld" / idf_variant / "bootloader.rev3.ld.in")
                        if os.path.isfile(bootloader_rev3_path):
                            bootloader_script_in_path = bootloader_rev3_path
                    
                    # Preprocess the .ld.in template to generate the .ld file
                    if os.path.isfile(bootloader_script_in_path):
                        target_script = str(Path(BUILD_DIR) / "bootloader" / script_basename)
                        
                        preprocessed_script = preprocess_linker_file(
                            bootloader_script_in_path,
                            target_script,
                            config_dir=bootloader_config_dir,
                            extra_include_dirs=bootloader_extra_includes
                        )
                        
                        bootloader_env.Depends("$BUILD_DIR/bootloader.elf", preprocessed_script)
                        processed_extra_flags.extend(["-T", target_script])
                    else:
                        # Pass through if neither original nor template found (e.g., ROM scripts)
                        processed_extra_flags.extend(["-T", linker_script])
            else:
                # Pass through any other linker flags unchanged
                processed_extra_flags.extend(["-T", linker_script])
            i += 2
        else:
            processed_extra_flags.append(extra_flags[i])
            i += 1
    
    bootloader_env.Append(LINKFLAGS=processed_extra_flags)
    bootloader_libs = find_lib_deps(components_map, elf_config, link_args)

    bootloader_env.Prepend(__RPATH="-Wl,--start-group ")
    bootloader_env.Append(
        CPPDEFINES=["__BOOTLOADER_BUILD"], _LIBDIRFLAGS=" -Wl,--end-group"
    )

    return bootloader_env.ElfToBin(
        str(Path("$BUILD_DIR") / "bootloader"),
        bootloader_env.Program(
            str(Path("$BUILD_DIR") / "bootloader.elf"), bootloader_libs
        ),
    )


def get_targets_by_type(target_configs, target_types, ignore_targets=None):
    ignore_targets = ignore_targets or []
    result = []
    for target_config in target_configs.values():
        if (
            target_config["type"] in target_types
            and target_config["name"] not in ignore_targets
        ):
            result.append(target_config)

    return result


def get_components_map(target_configs, target_types, ignore_components=None):
    result = {}
    for config in get_targets_by_type(target_configs, target_types, ignore_components):
        if "nameOnDisk" not in config:
            config["nameOnDisk"] = "lib%s.a" % config["name"]
        result[config["id"]] = {"config": config}

    return result


def build_components(
    env, components_map, project_src_dir, prepend_dir=None, debug_allowed=True
):
    for k, v in components_map.items():
        components_map[k]["lib"] = build_library(
            env, v["config"], project_src_dir, prepend_dir, debug_allowed
        )


def get_project_elf(target_configs):
    exec_targets = get_targets_by_type(target_configs, ["EXECUTABLE"])
    if len(exec_targets) > 1:
        print(
            "Warning: Multiple elf targets found. The %s will be used!"
            % exec_targets[0]["name"]
        )

    return exec_targets[0]


def generate_default_component():
    # Used to force CMake generate build environments for all supported languages

    prj_cmake_tpl = """# Warning! Do not delete this auto-generated file.
file(GLOB component_sources *.c* *.S)
idf_component_register(SRCS ${component_sources})
"""
    dummy_component_path = str(Path(FRAMEWORK_DIR) / "components" / "__pio_env")
    if os.path.isdir(dummy_component_path):
        return

    os.makedirs(dummy_component_path, exist_ok=True)

    for ext in (".cpp", ".c", ".S"):
        dummy_file = str(Path(dummy_component_path) / ("__dummy" + ext))
        if not os.path.isfile(dummy_file):
            open(dummy_file, "a").close()

    component_cmake = str(Path(dummy_component_path) / "CMakeLists.txt")
    if not os.path.isfile(component_cmake):
        with open(component_cmake, "w") as fp:
            fp.write(prj_cmake_tpl)


def find_default_component(target_configs):
    for config in target_configs:
        if "__pio_env" in config:
            return config
    sys.stderr.write(
        "Error! Failed to find the default IDF component with build information for "
        "generic files.\nCheck that the `EXTRA_COMPONENT_DIRS` option is not overridden "
        "in your CMakeLists.txt.\nSee an example with an extra component here "
        "https://docs.platformio.org/en/latest/frameworks/espidf.html#esp-idf-components\n"
    )
    env.Exit(1)


def create_version_file():
    version_file = str(Path(FRAMEWORK_DIR) / "version.txt")
    if not os.path.isfile(version_file):
        with open(version_file, "w") as fp:
            fp.write(get_framework_version())


def generate_empty_partition_image(binary_path, image_size):
    empty_partition = env.Command(
        binary_path,
        None,
        env.VerboseAction(
            '"$ESPIDF_PYTHONEXE" "%s" %s $TARGET'
            % (
                str(Path(FRAMEWORK_DIR) / "components" / "partition_table" / "gen_empty_partition.py"),
                image_size,
            ),
            "Generating an empty partition $TARGET",
        ),
    )

    if flag_custom_sdkonfig == False:
        env.Depends("$BUILD_DIR/$PROGNAME$PROGSUFFIX", empty_partition)


def get_partition_info(pt_path, pt_offset, pt_params):
    if not os.path.isfile(pt_path):
        sys.stderr.write(
            "Missing partition table file `%s`\n" % pt_path
        )
        env.Exit(1)

    cmd = [
        get_python_exe(),
        str(Path(FRAMEWORK_DIR) / "components" / "partition_table" / "parttool.py"),
        "-q",
        "--partition-table-offset",
        hex(pt_offset),
        "--partition-table-file",
        pt_path,
        "get_partition_info",
        "--info",
        "size",
        "offset",
    ]

    if pt_params.get("name") == "boot":
        cmd.append("--partition-boot-default")
    else:
        cmd.extend(
            [
                "--partition-type",
                pt_params["type"],
                "--partition-subtype",
                pt_params["subtype"],
            ]
        )

    result = exec_command(cmd)
    if result["returncode"] != 0:
        sys.stderr.write(
            "Couldn't extract information for %s/%s from the partition table\n"
            % (pt_params["type"], pt_params["subtype"])
        )
        sys.stderr.write(result["out"] + "\n")
        sys.stderr.write(result["err"] + "\n")
        env.Exit(1)

    size = offset = 0
    if result["out"].strip():
        size, offset = result["out"].strip().split(" ", 1)

    return {"size": size, "offset": offset}


def get_app_partition_offset(pt_table, pt_offset):
    # Get the default boot partition offset
    ota_app_params = get_partition_info(pt_table, pt_offset, {"type": "app", "subtype": "ota_0"})
    if ota_app_params.get("offset"):
        return ota_app_params["offset"]
    factory_app_params = get_partition_info(pt_table, pt_offset, {"type": "app", "subtype": "factory"})
    return factory_app_params.get("offset", "0x10000")


def preprocess_linker_file(src_ld_script, target_ld_script, config_dir=None, extra_include_dirs=None):
    """
    Preprocess a linker script file (.ld.in) to generate the final .ld file.
    Supports both IDF 5.x (linker_script_generator.cmake) and IDF 6.x (linker_script_preprocessor.cmake).
    
    Args:
        src_ld_script: Source .ld.in file path
        target_ld_script: Target .ld file path
        config_dir: Configuration directory (defaults to BUILD_DIR/config for main app)
        extra_include_dirs: Additional include directories (list)
    """
    if config_dir is None:
        config_dir = str(Path(BUILD_DIR) / "config")
    
    # Convert all paths to forward slashes for CMake compatibility on Windows
    config_dir = fs.to_unix_path(config_dir)
    src_ld_script = fs.to_unix_path(src_ld_script)
    target_ld_script = fs.to_unix_path(target_ld_script)
    
    # Check IDF version to determine which CMake script to use
    framework_version_list = [int(v) for v in get_framework_version().split(".")]
    
    # IDF 6.0+ uses linker_script_preprocessor.cmake with CFLAGS approach
    if framework_version_list[0] >= 6:
        include_dirs = [f'"{config_dir}"']
        include_dirs.append(f'"{fs.to_unix_path(str(Path(FRAMEWORK_DIR) / "components" / "esp_system" / "ld"))}"')
        
        if extra_include_dirs:
            include_dirs.extend(f'"{fs.to_unix_path(dir_path)}"' for dir_path in extra_include_dirs)
        
        cflags_value = "-I" + " -I".join(include_dirs)
        
        return env.Command(
            target_ld_script,
            src_ld_script,
            env.VerboseAction(
                " ".join([
                    f'"{CMAKE_DIR}"',
                    f'-DCC="{fs.to_unix_path(str(Path(TOOLCHAIN_DIR) / "bin" / "$CC"))}"',
                    f'-DSOURCE="{src_ld_script}"',
                    f'-DTARGET="{target_ld_script}"',
                    f'-DCFLAGS="{cflags_value}"',
                    "-P",
                    f'"{fs.to_unix_path(str(Path(FRAMEWORK_DIR) / "tools" / "cmake" / "linker_script_preprocessor.cmake"))}"',
                ]),
                "Generating LD script $TARGET",
            ),
        )
    else:
        # IDF 5.x: Use legacy linker_script_generator.cmake method
        return env.Command(
            target_ld_script,
            src_ld_script,
            env.VerboseAction(
                " ".join([
                    f'"{CMAKE_DIR}"',
                    f'-DCC="{str(Path(TOOLCHAIN_DIR) / "bin" / "$CC")}"',
                    "-DSOURCE=$SOURCE",
                    "-DTARGET=$TARGET",
                    f'-DCONFIG_DIR="{config_dir}"',
                    f'-DLD_DIR="{str(Path(FRAMEWORK_DIR) / "components" / "esp_system" / "ld")}"',
                    "-P",
                    f'"{str(Path("$BUILD_DIR") / "esp-idf" / "esp_system" / "ld" / "linker_script_generator.cmake")}"',
                ]),
                "Generating LD script $TARGET",
            ),
        )


def generate_mbedtls_bundle(sdk_config):
    bundle_path = str(Path("$BUILD_DIR") / "x509_crt_bundle")
    if os.path.isfile(env.subst(bundle_path)):
        return

    default_crt_dir = str(Path(FRAMEWORK_DIR) / "components" / "mbedtls" / "esp_crt_bundle")

    cmd = [get_python_exe(), str(Path(default_crt_dir) / "gen_crt_bundle.py")]

    crt_args = ["--input"]
    if sdk_config.get("MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_FULL", False):
        crt_args.append(str(Path(default_crt_dir) / "cacrt_all.pem"))
        crt_args.append(str(Path(default_crt_dir) / "cacrt_local.pem"))
    elif sdk_config.get("MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_CMN", False):
        crt_args.append(str(Path(default_crt_dir) / "cacrt_all.pem"))
        crt_args.append(str(Path(default_crt_dir) / "cacrt_local.pem"))
        cmd.extend(
            ["--filter", str(Path(default_crt_dir) / "cmn_crt_authorities.csv")]
        )

    if sdk_config.get("MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE", False):
        cert_path = sdk_config.get("MBEDTLS_CUSTOM_CERTIFICATE_BUNDLE_PATH", "")
        if os.path.isfile(cert_path) or os.path.isdir(cert_path):
            crt_args.append(os.path.abspath(cert_path))
        else:
            print("Warning! Couldn't find custom certificate bundle %s" % cert_path)

    crt_args.append("-q")

    # Use exec_command to change working directory
    exec_command(cmd + crt_args, cwd=BUILD_DIR)
    env.Execute(
        env.VerboseAction(
            " ".join(
                [
                    f'"{CMAKE_DIR}"',
                    f'-DDATA_FILE="{bundle_path}"',
                    f'-DSOURCE_FILE="{bundle_path}.S"',
                    "-DFILE_TYPE=BINARY",
                    "-P",
                    f'"{str(Path(FRAMEWORK_DIR) / "tools" / "cmake" / "scripts" / "data_file_embed_asm.cmake")}"',
                ]
            ),
            "Generating assembly for certificate bundle...",
        )
    )


def _get_uv_exe():
    return get_executable_path(str(Path(PLATFORMIO_DIR) / "penv"), "uv")


def install_python_deps():
    UV_EXE = _get_uv_exe()

    def _get_installed_uv_packages(python_exe_path):
        result = {}
        try:
            uv_output = subprocess.check_output([
                UV_EXE, "pip", "list", "--python", python_exe_path, "--format=json"
            ])
            packages = json.loads(uv_output)
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as e:
            print(f"Warning! Couldn't extract the list of installed Python packages: {e}")
            return {}
        
        for p in packages:
            result[p["name"]] = pepver_to_semver(p["version"])

        return result

    skip_python_packages = str(Path(FRAMEWORK_DIR) / ".pio_skip_pypackages")
    if os.path.isfile(skip_python_packages):
        return

    deps = {
        # https://github.com/platformio/platformio-core/issues/4614
        "urllib3": "<2",
        # https://github.com/platformio/platform-espressif32/issues/635
        "cryptography": "~=44.0.0",
        "pyparsing": ">=3.1.0,<4",
        "idf-component-manager": "~=2.4.6",
        "esp-idf-kconfig": "~=2.5.0"
    }

    if sys_platform.system() == "Darwin" and "arm" in sys_platform.machine().lower():
        deps["chardet"] = ">=3.0.2,<4"

    python_exe_path = get_python_exe()
    installed_packages = _get_installed_uv_packages(python_exe_path)
    packages_to_install = []
    for package, spec in deps.items():
        if package not in installed_packages:
            packages_to_install.append(package)
        elif spec:
            version_spec = semantic_version.Spec(spec)
            if not version_spec.match(installed_packages[package]):
                packages_to_install.append(package)

    if packages_to_install:
        packages_str = " ".join(['"%s%s"' % (p, deps[p]) for p in packages_to_install])
        
        # Use uv to install packages in the specific Python environment
        env.Execute(
            env.VerboseAction(
                f'"{UV_EXE}" pip install --python "{python_exe_path}" {packages_str}',
                "Installing ESP-IDF's Python dependencies with uv",
            )
        )

    if IS_WINDOWS and "windows-curses" not in installed_packages:
        # Install windows-curses in the IDF Python environment
        env.Execute(
            env.VerboseAction(
                f'"{UV_EXE}" pip install --python "{python_exe_path}" windows-curses',
                "Installing windows-curses package with uv",
            )
        )


def get_idf_venv_dir():
    # The name of the IDF venv contains the IDF version to avoid possible conflicts and
    # unnecessary reinstallation of Python dependencies in cases when Arduino
    # as an IDF component requires a different version of the IDF package and
    # hence a different set of Python deps or their versions
    idf_version = get_framework_version()
    return str(Path(PLATFORMIO_DIR) / "penv" / f".espidf-{idf_version}")


def ensure_python_venv_available():

    def _get_idf_venv_python_version():
        try:
            version = subprocess.check_output(
                [
                    get_python_exe(),
                    "-c",
                    "import sys;print('{0}.{1}.{2}-{3}.{4}'.format(*list(sys.version_info)))"
                ], text=True
            )
            return version.strip()
        except subprocess.CalledProcessError as e:
            print("Failed to extract Python version from IDF virtual env!")
            return None

    def _is_venv_outdated(venv_data_file):
        try:
            with open(venv_data_file, "r", encoding="utf8") as fp:
                venv_data = json.load(fp)
                if venv_data.get("version", "") != IDF_ENV_VERSION:
                    print(
                        "Warning! IDF virtual environment version changed!"
                    )
                    return True
                if (
                    venv_data.get("python_version", "")
                    != _get_idf_venv_python_version()
                ):
                    print(
                        "Warning! Python version in the IDF virtual environment"
                        " differs from the current Python!"
                    )
                    return True
                return False
        except (OSError, ValueError):
            return True

    def _create_venv(venv_dir):
        uv_path = _get_uv_exe()

        if os.path.isdir(venv_dir):
            try:
                print("Removing an outdated IDF virtual environment")
                shutil.rmtree(venv_dir)
            except OSError:
                print(
                    "Error: Cannot remove an outdated IDF virtual environment. " \
                    "Please remove the `%s` folder manually!" % venv_dir
                )
                env.Exit(1)

        # Use uv to create a standalone IDF virtual env
        env.Execute(
            env.VerboseAction(
                '"%s" venv --clear --quiet --python "%s" "%s"' % (uv_path, env.subst("$PYTHONEXE"), venv_dir),
                "Creating a new virtual environment for IDF Python dependencies using uv",
            )
        )

        # Verify that the venv was created successfully by checking for Python executable
        python_path = get_executable_path(venv_dir, "python")
        if not os.path.isfile(python_path):
            sys.stderr.write("Error: Failed to create a proper virtual environment. Missing the Python executable!\n")
            env.Exit(1)

    venv_dir = get_idf_venv_dir()
    venv_data_file = str(Path(venv_dir) / "pio-idf-venv.json")
    if not os.path.isfile(venv_data_file) or _is_venv_outdated(venv_data_file):
        _create_venv(venv_dir)
        install_python_deps()
        with open(venv_data_file, "w", encoding="utf8") as fp:
            venv_info = {
                "version": IDF_ENV_VERSION,
                "python_version": _get_idf_venv_python_version()
            }
            json.dump(venv_info, fp, indent=2)


def get_python_exe():
    python_exe_path = get_executable_path(get_idf_venv_dir(), "python")
    if not os.path.isfile(python_exe_path):
        sys.stderr.write("Error: Missing Python executable file `%s`\n" % python_exe_path)
        env.Exit(1)

    return python_exe_path


#
# Ensure Python environment contains everything required for IDF
#

ensure_python_venv_available()

# ESP-IDF package version is determined from version.h file
# since the package distribution doesn't include .git metadata

create_version_file()

# Generate a default component with dummy C/C++/ASM source files in the framework
# folder. This component is used to force the IDF build system generate build
# information for generic C/C++/ASM sources regardless of whether such files are used in project

generate_default_component()

#
# Generate final linker script
#

if not board.get("build.ldscript", ""):
    initial_ld_script = board.get("build.esp-idf.ldscript", str(Path(FRAMEWORK_DIR) / "components" / "esp_system" / "ld" / idf_variant / "memory.ld.in"))

    framework_version_list = [int(v) for v in get_framework_version().split(".")]
    if framework_version_list[:2] > [5, 2]:
        initial_ld_script = preprocess_linker_file(
            initial_ld_script,
            str(Path(BUILD_DIR) / "esp-idf" / "esp_system" / "ld" / "memory.ld.in")
        )

    linker_script = env.Command(
        str(Path("$BUILD_DIR") / "memory.ld"),
        initial_ld_script,
        env.VerboseAction(
            '$CC -I"$BUILD_DIR/config" -I"%s" -C -P -x c -E $SOURCE -o $TARGET'
            % str(Path(FRAMEWORK_DIR) / "components" / "esp_system" / "ld"),
            "Generating LD script $TARGET",
        ),
    )

    env.Depends("$BUILD_DIR/$PROGNAME$PROGSUFFIX", linker_script)
    env.Replace(LDSCRIPT_PATH="memory.ld")


#
# Known build system limitations
#

if any(" " in p for p in (FRAMEWORK_DIR, BUILD_DIR)):
    sys.stderr.write("Error: Detected a whitespace character in project paths.\n")
    env.Exit(1)

if not os.path.isdir(PROJECT_SRC_DIR):
    sys.stderr.write(
        "Error: Missing the `%s` folder with project sources.\n"
        % os.path.basename(PROJECT_SRC_DIR)
    )
    env.Exit(1)

if env.subst("$SRC_FILTER"):
    print(
        (
            "Warning: the 'src_filter' option cannot be used with ESP-IDF. Select source "
            "files to build in the project CMakeLists.txt file.\n"
        )
    )

#
# Initial targets loading
#

# By default 'main' folder is used to store source files. In case when a user has
# default 'src' folder we need to add this as an extra component. If there is no 'main'
# folder CMake won't generate dependencies properly
extra_components = []
if PROJECT_SRC_DIR != str(Path(PROJECT_DIR) / "main"):
    extra_components.append(str(Path(PROJECT_SRC_DIR).resolve()))
if "arduino" in env.subst("$PIOFRAMEWORK"):
    extra_components.append(ARDUINO_FRAMEWORK_DIR)
    # Add path to internal Arduino libraries so that the LDF will be able to find them
    env.Append(
        LIBSOURCE_DIRS=[str(Path(ARDUINO_FRAMEWORK_DIR) / "libraries")]
    )

# Setup CMake configuration arguments
extra_cmake_args = [
    "-DIDF_TARGET=" + idf_variant,
    "-DPYTHON_DEPS_CHECKED=1",
    "-DEXTRA_COMPONENT_DIRS:PATH=" + ";".join(str(Path(p).resolve()) for p in extra_components),
    "-DPYTHON=" + get_python_exe(),
    "-DSDKCONFIG=" + SDKCONFIG_PATH,
    f"-DESP_IDF_VERSION={major_version}",
    f"-DESP_IDF_VERSION_MAJOR={framework_version.split('.')[0]}",
    f"-DESP_IDF_VERSION_MINOR={framework_version.split('.')[1]}",
]

# This will add the linker flag for the map file
extra_cmake_args.append(
    f'-DCMAKE_EXE_LINKER_FLAGS=-Wl,-Map={fs.to_unix_path(str(Path(BUILD_DIR) / (env.subst("$PROGNAME") + ".map")))}'
)

# Add any extra args from board config
extra_cmake_args += click.parser.split_arg_string(board.get("build.cmake_extra_args", ""))

print("Reading CMake configuration...")
project_codemodel = get_cmake_code_model(
    PROJECT_DIR,
    BUILD_DIR,
    extra_cmake_args
)

# At this point the sdkconfig file should be generated by the underlying build system
if not os.path.isfile(SDKCONFIG_PATH):
    sys.stderr.write("Missing auto-generated SDK configuration file `%s`\n" % SDKCONFIG_PATH)
    env.Exit(1)

if not project_codemodel:
    sys.stderr.write("Error: Couldn't find code model generated by CMake\n")
    env.Exit(1)

target_configs = load_target_configurations(
    project_codemodel, str(Path(BUILD_DIR) / CMAKE_API_REPLY_PATH)
)

sdk_config = get_sdk_configuration()

project_target_name = "__idf_%s" % os.path.basename(PROJECT_SRC_DIR)
if project_target_name not in target_configs:
    sys.stderr.write("Error: Couldn't find the main target of the project!\n")
    env.Exit(1)

if project_target_name != "__idf_main" and "__idf_main" in target_configs:
    sys.stderr.write(
        (
            "Warning! Detected two different targets with project sources. Please use "
            "either %s or specify 'main' folder in 'platformio.ini' file.\n"
            % project_target_name
        )
    )
    env.Exit(1)

project_ld_script = generate_project_ld_script(
    sdk_config, [project_target_name, "__pio_env"]
)
env.Depends("$BUILD_DIR/$PROGNAME$PROGSUFFIX", project_ld_script)

elf_config = get_project_elf(target_configs)
default_config_name = find_default_component(target_configs)
framework_components_map = get_components_map(
    target_configs,
    ["STATIC_LIBRARY", "OBJECT_LIBRARY"],
    [project_target_name, default_config_name],
)

build_components(env, framework_components_map, PROJECT_DIR)

if not elf_config:
    sys.stderr.write("Error: Couldn't load the main firmware target of the project\n")
    env.Exit(1)

for component_config in framework_components_map.values():
    env.Depends(project_ld_script, component_config["lib"])

project_config = target_configs.get(project_target_name, {})
default_config = target_configs.get(default_config_name, {})
project_defines = get_app_defines(project_config)
project_flags = get_app_flags(project_config, default_config)
link_args = extract_link_args(elf_config)
app_includes = get_app_includes(elf_config)

#
# Compile bootloader
#

if flag_custom_sdkonfig == False:
    env.Depends("$BUILD_DIR/$PROGNAME$PROGSUFFIX", build_bootloader(sdk_config))

#
# ESP-IDF menuconfig target implementation
#

env.AddPlatformTarget(
    "menuconfig",
    None,
    [env.VerboseAction(RunMenuconfig, "Running menuconfig...")],
    "Run Menuconfig",
)

#
# Process main parts of the framework
#

# Get components to ignore from lib_ignore option
lib_ignore_components = get_lib_ignore_components()
if lib_ignore_components:
    print(f"[ESP-IDF] Ignoring components based on lib_ignore: {', '.join(lib_ignore_components)}")
ignore_components_list = [project_target_name, *lib_ignore_components]

libs = find_lib_deps(
    framework_components_map, elf_config, link_args, ignore_components_list
)

# Extra flags which need to be explicitly specified in LINKFLAGS section because SCons
# cannot merge them correctly
extra_flags = filter_args(
    link_args["LINKFLAGS"],
    [
        "-T",
        "-u",
        "-Wl,--start-group",
        "-Wl,--end-group",
        "-Wl,--whole-archive",
        "-Wl,--no-whole-archive",
    ],
)
link_args["LINKFLAGS"] = sorted(list(set(link_args["LINKFLAGS"]) - set(extra_flags)))

# remove the main linker script flags '-T memory.ld'
try:
    ld_index = extra_flags.index("memory.ld")
    extra_flags.pop(ld_index)
    extra_flags.pop(ld_index - 1)
except (ValueError, IndexError):
    print("Warning! Couldn't find the main linker script in the CMake code model.")

#
# Process project sources
#


# Remove project source files from following build stages as they're
# built as part of the framework
def _skip_prj_source_files(node):
    project_src_resolved = Path(PROJECT_SRC_DIR).resolve()
    node_path_resolved = Path(node.srcnode().get_path()).resolve()
    try:
        node_path_resolved.relative_to(project_src_resolved)
    except ValueError:
        return node
    else:
        return None


env.AddBuildMiddleware(_skip_prj_source_files)

#
# Generate partition table
#

fwpartitions_dir = str(Path(FRAMEWORK_DIR) / "components" / "partition_table")
partitions_csv = board.get("build.partitions", "partitions_singleapp.csv")
partition_table_offset = sdk_config.get("PARTITION_TABLE_OFFSET", 0x8000)

env.Replace(
    PARTITIONS_TABLE_CSV=os.path.abspath(
        str(Path(fwpartitions_dir) / partitions_csv)
        if os.path.isfile(str(Path(fwpartitions_dir) / partitions_csv))
        else partitions_csv
    )
)

partition_table = env.Command(
    str(Path("$BUILD_DIR") / "partitions.bin"),
    "$PARTITIONS_TABLE_CSV",
    env.VerboseAction(
        '"$ESPIDF_PYTHONEXE" "%s" -q --offset "%s" --flash-size "%s" $SOURCE $TARGET'
        % (
            str(Path(FRAMEWORK_DIR) / "components" / "partition_table" / "gen_esp32part.py"),
            partition_table_offset,
            board.get("upload.flash_size", "4MB"),
        ),
        "Generating partitions $TARGET",
    ),
)

env.Depends("$BUILD_DIR/$PROGNAME$PROGSUFFIX", partition_table)

#
# Main environment configuration
#

project_flags.update(link_args)
env.MergeFlags(project_flags)
env.Prepend(
    CPPPATH=app_includes["plain_includes"],
    CPPDEFINES=project_defines,
    ESPIDF_PYTHONEXE=get_python_exe(),
    LINKFLAGS=extra_flags,
    LIBS=libs,
    FLASH_EXTRA_IMAGES=[
        (
            board.get(
                "upload.bootloader_offset",
                "0x1000" if mcu in ["esp32", "esp32s2"] else ("0x2000" if mcu in ["esp32c5", "esp32p4"] else "0x0"),
            ),
            str(Path("$BUILD_DIR") / "bootloader.bin"),
        ),
        (
            board.get("upload.partition_table_offset", hex(partition_table_offset)),
            str(Path("$BUILD_DIR") / "partitions.bin"),
        ),
    ],
)

#
# Propagate Arduino defines to the main build environment
#

if "arduino" in env.subst("$PIOFRAMEWORK"):
    arduino_candidates = [n for n in target_configs if n.startswith("__idf_framework-arduinoespressif32")]
    if arduino_candidates:
        arduino_cfg = target_configs.get(arduino_candidates[0], {})
        cg_list = arduino_cfg.get("compileGroups", [])
        if cg_list:
            env.AppendUnique(CPPDEFINES=extract_defines(cg_list[0]))

# Project files should be compiled only when a special
# option is enabled when running 'test' command
if "__test" not in COMMAND_LINE_TARGETS or env.GetProjectOption(
    "test_build_project_src"
):
    project_env = env.Clone()
    if project_target_name != "__idf_main":
        # Add dependencies to CPPPATH for non-main source directories
        # ESP-IDF build system requires manual dependency handling for custom source folders
        # https://docs.espressif.com/projects/esp-idf/en/latest/api-guides/build-system.html#rename-main
        project_env.AppendUnique(CPPPATH=app_includes["plain_includes"])

    # Add include dirs from PlatformIO build system to project CPPPATH so
    # they're visible to PIOBUILDFILES
    project_env.AppendUnique(
        CPPPATH=["$PROJECT_INCLUDE_DIR", "$PROJECT_SRC_DIR", "$PROJECT_DIR"]
        + get_project_lib_includes(env)
    )

    project_env.ProcessFlags(env.get("SRC_BUILD_FLAGS"))
    env.Append(
        PIOBUILDFILES=compile_source_files(
            target_configs.get(project_target_name),
            project_env,
            project_env.subst("$PROJECT_DIR"),
        )
    )

#
# Generate mbedtls bundle
#

if sdk_config.get("MBEDTLS_CERTIFICATE_BUNDLE", False):
    generate_mbedtls_bundle(sdk_config)

#
# Check if flash size is set correctly in the IDF configuration file
#

board_flash_size = board.get("upload.flash_size", "4MB")
idf_flash_size = sdk_config.get("ESPTOOLPY_FLASHSIZE", "4MB")
if board_flash_size != idf_flash_size:
    print(
        "Warning! Flash memory size mismatch detected. Expected %s, found %s!"
        % (board_flash_size, idf_flash_size)
    )
    print(
        "Please select a proper value in your `sdkconfig.defaults` "
        "or via the `menuconfig` target!"
    )

#
# To embed firmware checksum a special argument for esptool.py is required
#

extra_elf2bin_flags = "--elf-sha256-offset 0xb0"
# Reference: ESP-IDF esptool_py component configuration
# For chips that support configurable MMU page size feature
# If page size is configured to values other than the default "64KB" in menuconfig,
mmu_page_size = "64KB"
if sdk_config.get("MMU_PAGE_SIZE_8KB", False):
    mmu_page_size = "8KB"
elif sdk_config.get("MMU_PAGE_SIZE_16KB", False):
    mmu_page_size = "16KB"
elif sdk_config.get("MMU_PAGE_SIZE_32KB", False):
    mmu_page_size = "32KB"
else:
    mmu_page_size = "64KB"

if sdk_config.get("SOC_MMU_PAGE_SIZE_CONFIGURABLE", False):
    if board_flash_size == "2MB":
        mmu_page_size = "32KB"
    elif board_flash_size == "1MB":
        mmu_page_size = "16KB"

if mmu_page_size != "64KB":
    extra_elf2bin_flags += " --flash-mmu-page-size %s" % mmu_page_size

action = copy.deepcopy(env["BUILDERS"]["ElfToBin"].action)

action.cmd_list = env["BUILDERS"]["ElfToBin"].action.cmd_list.replace(
    "-o", extra_elf2bin_flags + " -o"
)
env["BUILDERS"]["ElfToBin"].action = action

#
# Compile ULP sources in 'ulp' folder
#

ulp_dir = str(Path(PROJECT_DIR) / "ulp")
# ULP support: ESP32, ESP32-S2, ESP32-S3, ESP32-C6, ESP32-P4
# No ULP: ESP32-C2, ESP32-C3, ESP32-C5, ESP32-H2
if os.path.isdir(ulp_dir) and os.listdir(ulp_dir) and mcu not in ("esp32c2", "esp32c3", "esp32c5", "esp32h2"):
    env.SConscript("ulp.py", exports="env sdk_config project_config app_includes idf_variant")

#
# Compile Arduino IDF sources
#

if ("arduino" in env.subst("$PIOFRAMEWORK")) and ("espidf" not in env.subst("$PIOFRAMEWORK")):
    def idf_lib_copy(source, target, env):
        def _replace_copy(src, dst):
            dst_p = Path(dst)
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except (OSError, IOError):
                # Gracefully handle missing source files (e.g., PSRAM libs in non-PSRAM builds)
                # This is expected when copying variant-specific libraries
                pass
            except Exception as e:
                print(f"Warning: Failed to copy {src} to {dst}: {e}")
        env_build = str(Path(env["PROJECT_BUILD_DIR"]) / env["PIOENV"])
        sdkconfig_h_path = str(Path(env_build) / "config" / "sdkconfig.h")
        arduino_libs = str(Path(ARDUINO_FRMWRK_LIB_DIR))
        lib_src = str(Path(env_build) / "esp-idf")
        lib_dst = str(Path(arduino_libs) / chip_variant / "lib")
        ld_dst = str(Path(arduino_libs) / chip_variant / "ld")
        mem_var = str(Path(arduino_libs) / chip_variant / board.get("build.arduino.memory_type", (board.get("build.flash_mode", "dio") + "_qspi")))
        # Ensure destinations exist
        for d in (lib_dst, ld_dst, mem_var, str(Path(mem_var) / "include")):
            Path(d).mkdir(parents=True, exist_ok=True)
        src = [str(Path(lib_src) / x) for x in os.listdir(lib_src)]
        src = [folder for folder in src if not os.path.isfile(folder)] # folders only
        for folder in src:
            files = [str(Path(folder) / x) for x in os.listdir(folder)]
            for file in files:
                if file.strip().endswith(".a"):
                    shutil.copyfile(file, str(Path(lib_dst) / file.split(os.path.sep)[-1]))

        _replace_copy(str(Path(lib_dst) / "libspi_flash.a"), str(Path(mem_var) / "libspi_flash.a"))
        _replace_copy(str(Path(env_build) / "memory.ld"), str(Path(ld_dst) / "memory.ld"))
        if mcu == "esp32s3":
            _replace_copy(str(Path(lib_dst) / "libesp_psram.a"), str(Path(mem_var) / "libesp_psram.a"))
            _replace_copy(str(Path(lib_dst) / "libesp_system.a"), str(Path(mem_var) / "libesp_system.a"))
            _replace_copy(str(Path(lib_dst) / "libfreertos.a"), str(Path(mem_var) / "libfreertos.a"))
            _replace_copy(str(Path(lib_dst) / "libbootloader_support.a"), str(Path(mem_var) / "libbootloader_support.a"))
            _replace_copy(str(Path(lib_dst) / "libesp_hw_support.a"), str(Path(mem_var) / "libesp_hw_support.a"))
            _replace_copy(str(Path(lib_dst) / "libesp_lcd.a"), str(Path(mem_var) / "libesp_lcd.a"))

        shutil.copyfile(sdkconfig_h_path, str(Path(mem_var) / "include" / "sdkconfig.h"))
        if not bool(os.path.isfile(str(Path(arduino_libs) / chip_variant / "sdkconfig.orig"))):
            shutil.move(str(Path(arduino_libs) / chip_variant / "sdkconfig"), str(Path(arduino_libs) / chip_variant / "sdkconfig.orig"))
        shutil.copyfile(str(Path(env.subst("$PROJECT_DIR")) / ("sdkconfig." + env["PIOENV"])), str(Path(arduino_libs) / chip_variant / "sdkconfig"))
        shutil.copyfile(str(Path(env.subst("$PROJECT_DIR")) / ("sdkconfig." + env["PIOENV"])), str(Path(arduino_libs) / "sdkconfig"))
        try:
            # clean env build folder to avoid issues with following Arduino build
            shutil.rmtree(env_build)
            Path(env_build).mkdir(parents=True, exist_ok=True)
            os.remove(str(Path(env.subst("$PROJECT_DIR")) / "dependencies.lock"))
            os.remove(str(Path(env.subst("$PROJECT_DIR")) / "CMakeLists.txt"))
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"Warning: cleanup failed: {e}")
        print("*** Copied compiled %s IDF libraries to Arduino framework ***" % idf_variant)

        PYTHON_EXE = env.subst("$PYTHONEXE")
        pio_exe_path = str(Path(os.path.dirname(PYTHON_EXE)) / ("pio" + (".exe" if IS_WINDOWS else "")))
        pio_cmd = env["PIOENV"]
        env.Execute(
            env.VerboseAction(
                (
                    '"%s" run -e ' % pio_exe_path
                    + " ".join(['"%s"' % pio_cmd])
                ),
                "*** Starting Arduino compile %s with custom libraries ***" % pio_cmd,
            )
        )
        if flag_custom_component_add == True or flag_custom_component_remove == True:
            try:
                shutil.copy(str(Path(ARDUINO_FRAMEWORK_DIR) / "idf_component.yml.orig"), str(Path(ARDUINO_FRAMEWORK_DIR) / "idf_component.yml"))
                print("*** Original Arduino \"idf_component.yml\" restored ***")
            except (FileNotFoundError, PermissionError, OSError):
                print("*** Original Arduino \"idf_component.yml\" couldnt be restored ***")
            # Restore original pioarduino-build.py
            from component_manager import ComponentManager
            component_manager = ComponentManager(env)
            component_manager.restore_pioarduino_build_py()
    silent_action = create_silent_action(idf_lib_copy)
    env.AddPostAction("checkprogsize", silent_action)

if "espidf" in env.subst("$PIOFRAMEWORK") and (flag_custom_component_add == True or flag_custom_component_remove == True):
    def idf_custom_component(source, target, env):
        try:
            if "arduino" in env.subst("$PIOFRAMEWORK"):
                shutil.copy(str(Path(ARDUINO_FRAMEWORK_DIR) / "idf_component.yml.orig"),
                            str(Path(ARDUINO_FRAMEWORK_DIR) / "idf_component.yml"))
                print("*** Original Arduino \"idf_component.yml\" restored ***")
        except (FileNotFoundError, PermissionError, OSError):
            try:
                shutil.copy(str(Path(PROJECT_SRC_DIR) / "idf_component.yml.orig"), str(Path(PROJECT_SRC_DIR) / "idf_component.yml"))
                print("*** Original \"idf_component.yml\" restored ***")
            except (FileNotFoundError, PermissionError, OSError):
                # Only remove idf_component.yml if a .orig backup exists
                # This indicates the file was created/modified by pioarduino
                orig_file = Path(PROJECT_SRC_DIR) / "idf_component.yml.orig"
                yml_file = Path(PROJECT_SRC_DIR) / "idf_component.yml"
                if orig_file.exists() and yml_file.exists():
                    try:
                        os.remove(str(yml_file))
                        print("*** pioarduino generated \"idf_component.yml\" removed ***")
                    except (FileNotFoundError, PermissionError, OSError):
                        print("*** Failed to remove pioarduino generated \"idf_component.yml\" ***")
                elif yml_file.exists():
                    print("*** User-created \"idf_component.yml\" preserved (no .orig backup found) ***")
        if "arduino" in env.subst("$PIOFRAMEWORK"):
            # Restore original pioarduino-build.py, only used with Arduino
            from component_manager import ComponentManager
            component_manager = ComponentManager(env)
            component_manager.restore_pioarduino_build_py()
    silent_action = create_silent_action(idf_custom_component)
    env.AddPostAction("checkprogsize", silent_action)

#
# Process OTA partition and image
#

ota_partition_params = get_partition_info(
    env.subst("$PARTITIONS_TABLE_CSV"),
    partition_table_offset,
    {"name": "ota", "type": "data", "subtype": "ota"},
)

if ota_partition_params["size"] and ota_partition_params["offset"]:
    # Generate an empty image if OTA is enabled in partition table
    ota_partition_image = str(Path("$BUILD_DIR") / "ota_data_initial.bin")
    if "arduino" in env.subst("$PIOFRAMEWORK"):
        ota_partition_image = str(Path(ARDUINO_FRAMEWORK_DIR) / "tools" / "partitions" / "boot_app0.bin")
    else:
        generate_empty_partition_image(ota_partition_image, ota_partition_params["size"])

    env.Append(
        FLASH_EXTRA_IMAGES=[
            (
                board.get(
                    "upload.ota_partition_offset", ota_partition_params["offset"]
                ),
                ota_partition_image,
            )
        ]
    )
    extra_imgs = board.get("upload.arduino.flash_extra_images", [])
    if extra_imgs:
        extra_img_dir = Path(env.subst("$PROJECT_DIR")) / "variants" / "tasmota"
        env.Append(
             FLASH_EXTRA_IMAGES=[(offset, str(extra_img_dir / img)) for offset, img in extra_imgs]
        )

def _parse_size(value):
    if isinstance(value, int):
        return value
    elif value.isdigit():
        return int(value)
    elif value.startswith("0x"):
        return int(value, 16)
    elif value[-1].upper() in ("K", "M"):
        base = 1024 if value[-1].upper() == "K" else 1024 * 1024
        return int(value[:-1]) * base
    return value

#
# Configure application partition offset
#

app_offset = get_app_partition_offset(
    env.subst("$PARTITIONS_TABLE_CSV"),
    partition_table_offset
)

env.Replace(ESP32_APP_OFFSET=app_offset)

#
# Propagate application offset to debug configurations
#

env["INTEGRATION_EXTRA_DATA"].update(
    {"application_offset": env.subst("$ESP32_APP_OFFSET")}
)
