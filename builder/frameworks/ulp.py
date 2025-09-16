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
import sys
from pathlib import Path

from platformio import fs
from platformio.util import get_systype
from platformio.proc import exec_command

from SCons.Script import Import

Import("env sdk_config project_config app_includes idf_variant")

ulp_env = env.Clone()
platform = ulp_env.PioPlatform()
FRAMEWORK_DIR = platform.get_package_dir("framework-espidf")
BUILD_DIR = ulp_env.subst("$BUILD_DIR")
ULP_BUILD_DIR = str(Path(BUILD_DIR) / "esp-idf" / project_config["name"].replace("__idf_", "") / "ulp_main")

is_xtensa = idf_variant in ("esp32", "esp32s2", "esp32s3")

def prepare_ulp_env_vars(env):
    ulp_env.PrependENVPath("IDF_PATH", FRAMEWORK_DIR)

    toolchain_path = platform.get_package_dir(
        "toolchain-xtensa-esp-elf"
        if is_xtensa
        else "toolchain-riscv32-esp"
    )

    toolchain_path_ulp = platform.get_package_dir(
        "toolchain-esp32ulp"
        if sdk_config.get("ULP_COPROC_TYPE_FSM", False)
        else None
    )

    additional_packages = [
        toolchain_path,
        toolchain_path_ulp,
        platform.get_package_dir("tool-ninja"),
        str(Path(platform.get_package_dir("tool-cmake")) / "bin"),
    ]

    for package in additional_packages:
        if package and os.path.isdir(package):
            ulp_env.PrependENVPath("PATH", package)


def collect_ulp_sources():
    return [
        str(Path(ulp_env.subst("$PROJECT_DIR")) / "ulp" / f)
        for f in os.listdir(str(Path(ulp_env.subst("$PROJECT_DIR")) / "ulp"))
        if f.endswith((".c", ".S", ".s"))
    ]


def get_component_includes(target_config):
    for source in target_config.get("sources", []):
        if source["path"].endswith("ulp_main.bin.S"):
            return [
                inc["path"]
                for inc in target_config["compileGroups"][source["compileGroupIndex"]][
                    "includes"
                ]
            ]

    return [str(Path(BUILD_DIR) / "config")]


def generate_ulp_config(target_config):
    def _generate_ulp_configuration_action(env, target, source):
        riscv_ulp_enabled = sdk_config.get("ULP_COPROC_TYPE_RISCV", False)
        lp_core_ulp_enabled = sdk_config.get("ULP_COPROC_TYPE_LP_CORE", False)

        if not lp_core_ulp_enabled:
            ulp_toolchain = "toolchain-%sulp%s.cmake"% (
                "" if riscv_ulp_enabled else idf_variant + "-",
                "-riscv" if riscv_ulp_enabled else "",
            )
        else:
            ulp_toolchain = "toolchain-lp-core-riscv.cmake"

        comp_includes_list = get_component_includes(target_config)
        plain_includes_list = app_includes["plain_includes"]
        comp_includes = ";".join(comp_includes_list + plain_includes_list)

        cmd = (
            str(Path(platform.get_package_dir("tool-cmake")) / "bin" / "cmake"),
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "-DCMAKE_GENERATOR=Ninja",
            "-DCMAKE_TOOLCHAIN_FILE="
            + str(Path(FRAMEWORK_DIR) / "components" / "ulp" / "cmake" / ulp_toolchain),
            "-DULP_S_SOURCES=%s" % ";".join([fs.to_unix_path(s.get_abspath()) for s in source]),
            "-DULP_APP_NAME=ulp_main",
            "-DCOMPONENT_DIR=" + str(Path(ulp_env.subst("$PROJECT_DIR")) / "ulp"),
            "-DCOMPONENT_INCLUDES=%s" % comp_includes,
            "-DIDF_TARGET=%s" % idf_variant,
            "-DIDF_PATH=" + fs.to_unix_path(FRAMEWORK_DIR),
            "-DSDKCONFIG_HEADER=" + str(Path(BUILD_DIR) / "config" / "sdkconfig.h"),
            "-DPYTHON=" + env.subst("$PYTHONEXE"),
            "-DSDKCONFIG_CMAKE=" + str(Path(BUILD_DIR) / "config" / "sdkconfig.cmake"),
            "-DCMAKE_MODULE_PATH=" + fs.to_unix_path(str(Path(FRAMEWORK_DIR) / "components" / "ulp" / "cmake")),
            "-GNinja",
            "-B",
            ULP_BUILD_DIR,
            str(Path(FRAMEWORK_DIR) / "components" / "ulp" / "cmake"),
        )

        result = exec_command(cmd)
        if result["returncode"] != 0:
            sys.stderr.write(result["err"] + "\n")
            env.Exit(1)

    ulp_sources = collect_ulp_sources()
    ulp_sources.sort()

    return ulp_env.Command(
        str(Path(ULP_BUILD_DIR) / "build.ninja"),
        ulp_sources,
        ulp_env.VerboseAction(
            _generate_ulp_configuration_action, "Generating ULP configuration"
        ),
    )


def compile_ulp_binary():
    cmd = (
        str(Path(platform.get_package_dir("tool-cmake")) / "bin" / "cmake"),
        "--build",
        ULP_BUILD_DIR,
        "--target",
        "build",
    )

    # The `build.ninja` dependency is always generated with the same content
    # so a cloned environment with a decider that depends on a timestamp is used
    ulp_binary_env = ulp_env.Clone()
    ulp_binary_env.Decider("timestamp-newer")

    return ulp_binary_env.Command(
        [
            str(Path(ULP_BUILD_DIR) / "ulp_main.h"),
            str(Path(ULP_BUILD_DIR) / "ulp_main.ld"),
            str(Path(ULP_BUILD_DIR) / "ulp_main.bin"),
        ],
        None,
        ulp_binary_env.VerboseAction(" ".join(cmd), "Generating ULP project files $TARGETS"),
    )


def generate_ulp_assembly():
    cmd = (
        str(Path(platform.get_package_dir("tool-cmake")) / "bin" / "cmake"),
        "-DDATA_FILE=$SOURCE",
        "-DSOURCE_FILE=$TARGET",
        "-DFILE_TYPE=BINARY",
        "-P",
        str(Path(FRAMEWORK_DIR) / "tools" / "cmake" / "scripts" / "data_file_embed_asm.cmake"),
    )

    return ulp_env.Command(
        str(Path(BUILD_DIR) / "ulp_main.bin.S"),
        str(Path(ULP_BUILD_DIR) / "ulp_main.bin"),
        ulp_env.VerboseAction(" ".join(cmd), "Generating ULP assembly file $TARGET"),
    )


prepare_ulp_env_vars(ulp_env)
ulp_assembly = generate_ulp_assembly()

ulp_env.Depends(compile_ulp_binary(), generate_ulp_config(project_config))
ulp_env.Depends(str(Path("$BUILD_DIR") / "${PROGNAME}.elf"), ulp_assembly)
ulp_env.Requires(str(Path("$BUILD_DIR") / "${PROGNAME}.elf"), ulp_assembly)

env.AppendUnique(CPPPATH=ULP_BUILD_DIR, LIBPATH=ULP_BUILD_DIR)
