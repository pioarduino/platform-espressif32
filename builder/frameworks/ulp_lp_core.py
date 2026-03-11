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

import os
import re
import sys
from pathlib import Path

from platformio import fs
from platformio.proc import exec_command

from SCons.Script import Import, Return

Import("env")

# Skip when the CMake-based ulp.py handles ULP compilation
if "espidf" in env.subst("$PIOFRAMEWORK"):
    Return()

platform = env.PioPlatform()
board = env.BoardConfig()
mcu = board.get("build.mcu", "esp32")

#
# Per-MCU LP-Core configuration
# Keep in sync with _lp_core_mcus in arduino.py and platform.py
#

LP_CORE_MCUS = ("esp32c5", "esp32c6", "esp32p4")
ULP_SOURCE_SUFFIXES = (".c", ".S", ".s")

if mcu not in LP_CORE_MCUS:
    Return()


def _has_ulp_sources(ulp_dir):
    """Check if a directory tree contains LP-Core source files."""
    return ulp_dir.is_dir() and any(
        f.suffix in ULP_SOURCE_SUFFIXES for f in ulp_dir.rglob("*") if f.is_file()
    )


#
# Path resolution
#

PROJECT_DIR = Path(env.subst("$PROJECT_DIR"))
BUILD_DIR = Path(env.subst("$BUILD_DIR"))
ULP_DIR = PROJECT_DIR / "ulp"

if not _has_ulp_sources(ULP_DIR):
    Return()

ULP_BUILD_DIR = str(BUILD_DIR / "ulp_lp_core")

FRAMEWORK_DIR = platform.get_package_dir("framework-espidf")
if not FRAMEWORK_DIR or not os.path.isdir(FRAMEWORK_DIR):
    sys.stderr.write(
        "Error: framework-espidf not found. Required for LP-Core ULP builds.\n"
    )
    env.Exit(1)

FRAMEWORK_DIR = str(FRAMEWORK_DIR)
IDF_COMPONENTS = Path(FRAMEWORK_DIR) / "components"

_fw_libs_dir = platform.get_package_dir("framework-arduinoespressif32-libs")
if not _fw_libs_dir or not os.path.isdir(_fw_libs_dir):
    sys.stderr.write("Error: framework-arduinoespressif32-libs not found.\n")
    env.Exit(1)

FW_LIBS_DIR = Path(_fw_libs_dir)

#
# Validate libs have ULP support — detect stale/reset packages early
#

MEMORY_TYPE = board.get(
    "build.arduino.memory_type",
    board.get("build.flash_mode", "dio") + "_qspi",
)

_ulp_lib_path = FW_LIBS_DIR / mcu / "lib" / "libulp.a"
_recompiled_sdkconfig = FW_LIBS_DIR / mcu / MEMORY_TYPE / "include" / "sdkconfig.h"
_libs_have_ulp = (
    _ulp_lib_path.exists()
    and _recompiled_sdkconfig.exists()
    and "CONFIG_ULP_COPROC_ENABLED" in _recompiled_sdkconfig.read_text()
)

if not _libs_have_ulp:
    sys.stderr.write(
        "Error: Arduino libs were not compiled with ULP support.\n"
        "  libulp.a exists: %s\n"
        "  The libs package may have been reset. Run a clean build to\n"
        "  trigger automatic recompilation with ULP enabled:\n"
        "    pio run -t clean && pio run\n"
        % _ulp_lib_path.exists()
    )
    env.Exit(1)

#
# sdkconfig resolution
#
# Priority: user-provided ulp/sdkconfig.h > recompiled from libs (validated above)
#

USER_SDKCONFIG_H = ULP_DIR / "sdkconfig.h"


if USER_SDKCONFIG_H.exists():
    SDKCONFIG_H = USER_SDKCONFIG_H
else:
    # The validation above already confirmed _recompiled_sdkconfig exists and
    # contains CONFIG_ULP_COPROC_ENABLED, so we can use it directly.
    SDKCONFIG_H = _recompiled_sdkconfig


def get_sdkconfig_value(key, default):
    """Read a config value, checking the selected SDKCONFIG_H first, then
    custom_sdkconfig from platformio.ini, then falling back to default."""
    # Check the actual header the ULP build will use
    try:
        for line in SDKCONFIG_H.read_text().splitlines():
            line = line.strip()
            if line.startswith("#define %s " % key):
                return int(line.split(None, 2)[2])
    except Exception:
        pass
    # Fall back to platformio.ini custom_sdkconfig (Kconfig-style key=value)
    try:
        custom = env.GetProjectOption("custom_sdkconfig", "")
        for line in custom.splitlines():
            line = line.strip()
            if "://" in line:
                continue
            if line.startswith(key + "="):
                return int(line.split("=", 1)[1])
    except Exception:
        pass
    return default

#
# Generate sdkconfig.cmake from sdkconfig.h
#
# IDF's ULP CMake build does `include(${SDKCONFIG_CMAKE})` to read config
# values as CMake variables. We convert #define lines to set() calls.
#


def generate_sdkconfig_cmake():
    Path(ULP_BUILD_DIR).mkdir(parents=True, exist_ok=True)
    out = Path(ULP_BUILD_DIR) / "sdkconfig.cmake"

    lines = ["# Auto-generated from %s" % SDKCONFIG_H.name]
    try:
        for line in SDKCONFIG_H.read_text().splitlines():
            line = line.strip()
            if line.startswith("#define CONFIG_"):
                parts = line.split(None, 2)
                if len(parts) == 3:
                    value = parts[2].strip('"')
                    lines.append('set(%s "%s")' % (parts[1], value))
                elif len(parts) == 2:
                    lines.append('set(%s "1")' % parts[1])
    except Exception as e:
        sys.stderr.write("Error reading %s: %s\n" % (SDKCONFIG_H, e))
        env.Exit(1)

    content = "\n".join(lines) + "\n"
    if out.exists() and out.read_text() == content:
        return out
    out.write_text(content)
    return out


SDKCONFIG_CMAKE = generate_sdkconfig_cmake()

#
# Component include paths for ULP compilation
#
# IDF's ULP CMake build adds core ULP includes automatically. We only need
# to provide the framework-arduinoespressif32-libs paths for soc/hal headers.
# Non-existent paths are filtered for forward-compatibility.
#

FW_LIBS = FW_LIBS_DIR / mcu / "include"

COMPONENT_INCLUDES = [
    str(ULP_DIR),
    str(SDKCONFIG_H.parent),
    str(FW_LIBS / "soc" / mcu / "include"),
    str(FW_LIBS / "soc" / mcu / "register"),
    str(FW_LIBS / "soc" / "include"),
    str(FW_LIBS / "hal" / "include"),
    str(FW_LIBS / "hal" / mcu / "include"),
    str(FW_LIBS / "hal" / "platform_port" / "include"),
    str(FW_LIBS / "esp_common" / "include"),
    str(FW_LIBS / "esp_rom" / "include"),
    str(FW_LIBS / "esp_rom" / mcu),
    str(FW_LIBS / "esp_rom" / mcu / "include"),
    str(FW_LIBS / "esp_rom" / mcu / "include" / mcu),
    str(FW_LIBS / "esp_hw_support" / "include"),
    str(FW_LIBS / "esp_hw_support" / "include" / "soc"),
    str(FW_LIBS / "esp_hw_support" / "include" / "soc" / mcu),
    str(FW_LIBS / "esp_hw_support" / "port" / mcu),
    str(FW_LIBS / "esp_hw_support" / "port" / mcu / "include"),
    str(FW_LIBS / "riscv" / "include"),
    str(FW_LIBS / "log" / "include"),
    str(FW_LIBS / "esp_timer" / "include"),
    str(FW_LIBS / "esp_driver_uart" / "include"),
    str(FW_LIBS / "heap" / "include"),
]
COMPONENT_INCLUDES = [p for p in COMPONENT_INCLUDES if os.path.isdir(p)]

#
# Prepare build environment
#

ulp_env = env.Clone()


def prepare_ulp_env_vars():
    ulp_env["ENV"]["IDF_PATH"] = FRAMEWORK_DIR

    additional_packages = [
        platform.get_package_dir("toolchain-riscv32-esp"),
        platform.get_package_dir("tool-ninja"),
        str(Path(platform.get_package_dir("tool-cmake")) / "bin"),
    ]

    for package in additional_packages:
        if package and os.path.isdir(package):
            ulp_env.PrependENVPath("PATH", package)


prepare_ulp_env_vars()

CMAKE = str(Path(platform.get_package_dir("tool-cmake")) / "bin" / "cmake")

#
# Collect ULP sources
#


def collect_ulp_sources():
    return sorted(
        str(f) for f in ULP_DIR.rglob("*")
        if f.is_file() and f.suffix in ULP_SOURCE_SUFFIXES
    )

#
# CMake configure — generates build.ninja for the ULP build
#


def generate_ulp_config():
    def _action(env, target, source):
        ulp_toolchain = str(
            Path(FRAMEWORK_DIR) / "components" / "ulp" / "cmake"
            / "toolchain-lp-core-riscv.cmake"
        )

        cmd = (
            CMAKE,
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "-DCMAKE_GENERATOR=Ninja",
            "-DCMAKE_TOOLCHAIN_FILE=" + ulp_toolchain,
            "-DULP_S_SOURCES=%s" % ";".join(
                [fs.to_unix_path(s.get_abspath()) for s in source]
            ),
            "-DULP_APP_NAME=ulp_main",
            "-DULP_VAR_PREFIX=ulp_",
            "-DCOMPONENT_DIR=" + fs.to_unix_path(str(ULP_DIR)),
            "-DCOMPONENT_INCLUDES=%s" % ";".join(COMPONENT_INCLUDES),
            "-DIDF_TARGET=%s" % mcu,
            "-DIDF_PATH=" + fs.to_unix_path(FRAMEWORK_DIR),
            "-DSDKCONFIG_HEADER=" + str(SDKCONFIG_H),
            "-DPYTHON=" + env.subst("$PYTHONEXE"),
            "-DSDKCONFIG_CMAKE=" + str(SDKCONFIG_CMAKE),
            "-DCMAKE_MODULE_PATH=" + fs.to_unix_path(
                str(Path(FRAMEWORK_DIR) / "components" / "ulp" / "cmake")
            ),
            "-GNinja",
            "-B", ULP_BUILD_DIR,
            str(Path(FRAMEWORK_DIR) / "components" / "ulp" / "cmake"),
        )

        result = exec_command(cmd)
        if result["returncode"] != 0:
            sys.stderr.write("CMake ULP configure failed:\n%s\n" % result["err"])
            env.Exit(1)

    ulp_sources = collect_ulp_sources()
    return ulp_env.Command(
        str(Path(ULP_BUILD_DIR) / "build.ninja"),
        ulp_sources,
        ulp_env.VerboseAction(_action, "Configuring LP-Core ULP build"),
    )

#
# CMake build — compiles the ULP binary
#


def compile_ulp_binary():
    cmd = (CMAKE, "--build", ULP_BUILD_DIR, "--target", "build")

    # build.ninja content is stable across re-configurations, so use
    # timestamp-based decider to detect source changes
    ulp_binary_env = ulp_env.Clone()
    ulp_binary_env.Decider("timestamp-newer")

    return ulp_binary_env.Command(
        [
            str(Path(ULP_BUILD_DIR) / "ulp_main.h"),
            str(Path(ULP_BUILD_DIR) / "ulp_main.ld"),
            str(Path(ULP_BUILD_DIR) / "ulp_main.bin"),
        ],
        None,
        ulp_binary_env.VerboseAction(
            " ".join(cmd), "Building LP-Core ULP binary"
        ),
    )

#
# Generate assembly embedding of the ULP binary
#


def generate_ulp_assembly():
    cmd = (
        CMAKE,
        "-DDATA_FILE=$SOURCE",
        "-DSOURCE_FILE=$TARGET",
        "-DFILE_TYPE=BINARY",
        "-P",
        str(Path(FRAMEWORK_DIR) / "tools" / "cmake" / "scripts"
            / "data_file_embed_asm.cmake"),
    )

    return ulp_env.Command(
        str(BUILD_DIR / "ulp_main.bin.S"),
        str(Path(ULP_BUILD_DIR) / "ulp_main.bin"),
        ulp_env.VerboseAction(" ".join(cmd), "Generating ULP assembly file $TARGET"),
    )

#
# Patch memory.ld to reserve LP SRAM for the ULP binary
#

# Default matches the auto-injected value in arduino.py (_ulp_sdkconfig_entries)
ULP_RESERVE_MEM = get_sdkconfig_value("CONFIG_ULP_COPROC_RESERVE_MEM", 8192)

_LP_RAM_SEG_RE = re.compile(
    r"(lp_ram_seg\s*\(\s*RW\s*\)\s*:\s*org\s*=\s*)(.*?)"
    r"(,\s*len\s*=\s*)"
    r"([^\n]+)",
    re.DOTALL,
)


def patch_memory_ld():
    fw_ld_dir = FW_LIBS_DIR / mcu / "ld"
    src_ld = fw_ld_dir / "memory.ld"

    if not src_ld.exists():
        return

    text = src_ld.read_text()

    if "+ %d" % ULP_RESERVE_MEM in text or "+%d" % ULP_RESERVE_MEM in text:
        return

    match = _LP_RAM_SEG_RE.search(text)
    if not match:
        sys.stderr.write(
            "Error: lp_ram_seg not found in %s — cannot reserve LP SRAM.\n"
            "  The LP-Core binary will fail to load at runtime.\n" % src_ld
        )
        env.Exit(1)

    org_expr = match.group(2).rstrip()
    len_expr = match.group(4).rstrip()
    patched_seg = "%s(%s) + %d%s(%s) - %d" % (
        match.group(1), org_expr, ULP_RESERVE_MEM,
        match.group(3), len_expr, ULP_RESERVE_MEM,
    )
    patched = text[:match.start()] + patched_seg + text[match.end():]

    patched_ld_dir = Path(ULP_BUILD_DIR) / "ld"
    patched_ld_dir.mkdir(parents=True, exist_ok=True)
    (patched_ld_dir / "memory.ld").write_text(patched)
    env.Prepend(LIBPATH=[str(patched_ld_dir)])
    print(
        "Patched memory.ld: lp_ram_seg offset by %d bytes for LP-Core binary"
        % ULP_RESERVE_MEM
    )

#
# SCons build graph
#

ulp_config = generate_ulp_config()
ulp_binary = compile_ulp_binary()
ulp_assembly = generate_ulp_assembly()

ulp_env.Depends(ulp_binary, ulp_config)

# Compile the assembly file into an object with the main firmware toolchain
# and add it to the firmware's link inputs
ulp_obj = env.Object(
    str(BUILD_DIR / "ulp_main.bin.o"),
    str(BUILD_DIR / "ulp_main.bin.S"),
)
env.Depends(ulp_obj, ulp_assembly)
env.Append(PIOBUILDFILES=[ulp_obj])

# ULP build dir (ulp_main.h) + IDF ULP headers + soc/hal component includes.
# The component includes are needed for IDE IntelliSense on ULP source files
# (transitive headers like soc/gpio_num.h, hal/gpio_types.h, etc.).
env.AppendUnique(CPPPATH=[
    ULP_BUILD_DIR,
    str(IDF_COMPONENTS / "ulp" / "lp_core" / "include"),
    str(IDF_COMPONENTS / "ulp" / "lp_core" / "lp_core" / "include"),
    str(IDF_COMPONENTS / "ulp" / "ulp_common" / "include"),
] + COMPONENT_INCLUDES)
env.Append(LINKFLAGS=["-T", str(Path(ULP_BUILD_DIR) / "ulp_main.ld")])

# Link libulp.a for ulp_lp_core_load_binary / ulp_lp_core_run
ulp_lib = FW_LIBS_DIR / mcu / "lib" / "libulp.a"
if ulp_lib.exists():
    env.Append(LIBS=[env.File(str(ulp_lib))])
else:
    sys.stderr.write(
        "Error: libulp.a not found at %s\n"
        "  This library is produced by lib recompilation with ULP enabled.\n"
        "  The auto-injection should have triggered this — if you see this\n"
        "  error, the recompilation may have failed. Try a clean build:\n"
        "    pio run -t clean && pio run\n" % ulp_lib
    )
    env.Exit(1)

patch_memory_ld()

print("LP-Core ULP support enabled for %s (reserve=%d bytes)" % (mcu, ULP_RESERVE_MEM))
