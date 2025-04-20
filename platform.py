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

import os
import subprocess
import sys
import requests
import shutil
from os.path import isfile, join

from platformio.public import PlatformBase, to_unix_path
from platformio.proc import get_pythonexe_path
from platformio.project.config import ProjectConfig
from platformio.package.manager.tool import ToolPackageManager

IS_WINDOWS = sys.platform.startswith("win")
# Set Platformio env var to use windows_amd64 for all windows architectures
# only windows_amd64 native espressif toolchains are available
# needs platformio core >= 6.1.16b2 or pioarduino core 6.1.16+test
if IS_WINDOWS:
    os.environ["PLATFORMIO_SYSTEM_TYPE"] = "windows_amd64"

python_exe = get_pythonexe_path()
pm = ToolPackageManager()

IDF_TOOLS_PATH_DEFAULT = os.path.join(os.path.expanduser("~"), ".espressif")
IDF_TOOLS = os.path.join(ProjectConfig.get_instance().get("platformio", "packages_dir"), "tl-install", "tools", "idf_tools.py")
IDF_TOOLS_CMD = (
    python_exe,
    IDF_TOOLS,
    "install",
)

# IDF Install is needed only one time
tl_flag = bool(os.path.exists(IDF_TOOLS))
if (tl_flag and not bool(os.path.exists(join(IDF_TOOLS_PATH_DEFAULT, "tools")))):
    rc = subprocess.call(IDF_TOOLS_CMD)
    if rc != 0:
        sys.stderr.write("Error: Couldn't execute 'idf_tools.py install'\n")
    else:
        shutil.copytree(join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-packages"), join(IDF_TOOLS_PATH_DEFAULT, "tools"), symlinks=False, ignore=None, ignore_dangling_symlinks=False, dirs_exist_ok=True)
        for p in ("tool-mklittlefs", "tool-mkfatfs", "tool-mkspiffs", "tool-dfuutil", "tool-openocd", "tool-cmake", "tool-ninja", "tool-cppcheck", "tool-clangtidy", "tool-pvs-studio", "tc-xt-esp32", "tc-ulp", "tc-rv32", "tl-xt-gdb", "tl-rv-gdb", "contrib-piohome", "contrib-pioremote"):
            tl_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", p)
            pm.install(tl_path)
            pm.install("tool-scons")

class Espressif32Platform(PlatformBase):
    def configure_default_packages(self, variables, targets):
        if not variables.get("board"):
            return super().configure_default_packages(variables, targets)

        board_config = self.board_config(variables.get("board"))
        mcu = variables.get("board_build.mcu", board_config.get("build.mcu", "esp32"))
        board_sdkconfig = variables.get("board_espidf.custom_sdkconfig", board_config.get("espidf.custom_sdkconfig", ""))
        core_variant_board = ''.join(variables.get("board_build.extra_flags", board_config.get("build.extra_flags", "")))
        core_variant_board = core_variant_board.replace("-D", " ")
        core_variant_build = (''.join(variables.get("build_flags", []))).replace("-D", " ")
        frameworks = variables.get("pioframework", [])

        # Enable debug tool gdb only when build debug is enabled
        if (variables.get("build_type") or "debug" in "".join(targets)) and tl_flag:
            self.packages["riscv32-esp-elf-gdb"]["optional"] = False if mcu in ["esp32c2", "esp32c3", "esp32c5", "esp32c6", "esp32h2", "esp32p4"] else True
            self.packages["riscv32-esp-elf-gdb"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tl-rv-gdb")
            self.packages["xtensa-esp-elf-gdb"]["optional"] = False if not mcu in ["esp32c2", "esp32c3", "esp32c5", "esp32c6", "esp32h2", "esp32p4"] else True
            self.packages["xtensa-esp-elf-gdb"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tl-xt-gdb")
        else:
            self.packages["riscv32-esp-elf-gdb"]["optional"] = True
            self.packages["xtensa-esp-elf-gdb"]["optional"] = True

        if tl_flag:
            # Install tool is not needed anymore
            del self.packages["tl-install"]
            # Enable check tools only when "check_tool" is enabled
            for p in self.packages:
                if p in ("tool-cppcheck", "tool-clangtidy", "tool-pvs-studio"):
                    self.packages[p]["optional"] = False if str(variables.get("check_tool")).strip("['']") in p else True

        if "arduino" in frameworks:
            self.packages["framework-arduinoespressif32"]["optional"] = False
            self.packages["framework-arduinoespressif32-libs"]["optional"] = False
            # use matching espressif Arduino libs
            #URL = "https://raw.githubusercontent.com/espressif/arduino-esp32/master/package/package_esp32_index.template.json"
            #packjdata = requests.get(URL).json()
            #dyn_lib_url = packjdata['packages'][0]['tools'][0]['systems'][0]['url']
            # use newer libs as linked in package_esp32_index.template.json is too old
            dyn_lib_url = "https://github.com/espressif/esp32-arduino-lib-builder/releases/download/idf-release_v5.4/esp32-arduino-libs-idf-release_v5.4-6897a7bf-v1.zip"
            self.packages["framework-arduinoespressif32-libs"]["version"] = dyn_lib_url

        if variables.get("custom_sdkconfig") is not None or len(str(board_sdkconfig)) > 3:
            if mcu == "esp32c2":
                self.packages["framework-arduino-c2-skeleton-lib"]["optional"] = False
            frameworks.append("espidf")
            self.packages["framework-espidf"]["optional"] = False

        # packages for IDF and mixed Arduino+IDF projects
        if tl_flag and "espidf" in frameworks:
            for p in self.packages:
                if p in (
                    "tool-scons",
                    "tool-cmake",
                    "tool-ninja",
                    "tool-esp-rom-elfs",
                 ):
                    self.packages[p]["optional"] = False

        if tl_flag and ("".join(targets) in ("upload", "buildfs", "uploadfs") or variables.get("custom_files_upload") is not None):
            filesystem = variables.get("board_build.filesystem", "littlefs")
            if filesystem == "littlefs":
                # Use mklittlefs v3.2.0 to generate FS
                self.packages["tool-mklittlefs"]["optional"] = False
                self.packages["tool-mklittlefs"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-mklittlefs")
                del self.packages["tool-mkfatfs"]
                del self.packages["tool-mkspiffs"]
            elif filesystem == "fatfs":
                self.packages["tool-mkfatfs"]["optional"] = False
                self.packages["tool-mkfatfs"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-mkfatfs")
                del self.packages["tool-mklittlefs"]
                del self.packages["tool-mkspiffs"]
            elif filesystem == "spiffs":
                self.packages["tool-mkspiffs"]["optional"] = False
                self.packages["tool-mkspiffs"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-mkspiffs")
                del self.packages["tool-mkfatfs"]
                del self.packages["tool-mklittlefs"]
        else:
            del self.packages["tool-mklittlefs"]
            del self.packages["tool-mkfatfs"]
            del self.packages["tool-mkspiffs"]

        if variables.get("upload_protocol"):
            self.packages["tool-openocd"]["optional"] = False
            self.packages["tool-openocd"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-openocd")
        else:
            del self.packages["tool-openocd"]

        if "downloadfs" in targets:
            filesystem = variables.get("board_build.filesystem", "littlefs")
            if filesystem == "littlefs":
                # Use mklittlefs v4.0.0 to unpack, older version is incompatible
                self.packages["tool-mklittlefs"]["optional"] = False
                self.packages["tool-mklittlefs"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-mklittlefs400")

        # Currently only Arduino Nano ESP32 uses the dfuutil tool as uploader
        if variables.get("board") == "arduino_nano_esp32":
            self.packages["tool-dfuutil"]["optional"] = False
            self.packages["tool-dfuutil"]["version"] = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-dfuutil")
        else:
            del self.packages["tool-dfuutil"]

        # Enable needed toolchain for MCU
        if tl_flag and mcu in ("esp32", "esp32s2", "esp32s3"):
            tc_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tc-xt-esp32")
            self.packages["xtensa-esp-elf"]["optional"] = False
            self.packages["xtensa-esp-elf"]["version"] = tc_path
        else:
            if tl_flag:
                tc_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tc-rv32")
                self.packages["riscv32-esp-elf"]["optional"] = False
                self.packages["riscv32-esp-elf"]["version"] = tc_path
                
        # Enable FSM ULP toolchain for ESP32, ESP32S2, ESP32S3 when IDF is selected
        if tl_flag and "espidf" in frameworks and mcu in ("esp32", "esp32s2", "esp32s3"):
            tc_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tc-ulp")
            self.packages["esp32ulp-elf"]["optional"] = False
            self.packages["esp32ulp-elf"]["version"] = tc_path
        # Enable RISC-V ULP toolchain for ESP32C6, ESP32S2, ESP32S3 when IDF is selected
        if tl_flag and "espidf" in frameworks and mcu in ("esp32s2", "esp32s3", "esp32c5", "esp32c6", "esp32p4"):
            tc_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tc-rv32")
            self.packages["riscv32-esp-elf"]["optional"] = False
            self.packages["riscv32-esp-elf"]["version"] = tc_path

        return super().configure_default_packages(variables, targets)

    def get_boards(self, id_=None):
        result = super().get_boards(id_)
        if not result:
            return result
        if id_:
            return self._add_dynamic_options(result)
        else:
            for key, value in result.items():
                result[key] = self._add_dynamic_options(result[key])
        return result

    def _add_dynamic_options(self, board):
        # upload protocols
        if not board.get("upload.protocols", []):
            board.manifest["upload"]["protocols"] = ["esptool", "espota"]
        if not board.get("upload.protocol", ""):
            board.manifest["upload"]["protocol"] = "esptool"

        # debug tools
        debug = board.manifest.get("debug", {})
        non_debug_protocols = ["esptool", "espota"]
        supported_debug_tools = [
            "cmsis-dap",
            "esp-prog",
            "esp-bridge",
            "iot-bus-jtag",
            "jlink",
            "minimodule",
            "olimex-arm-usb-tiny-h",
            "olimex-arm-usb-ocd-h",
            "olimex-arm-usb-ocd",
            "olimex-jtag-tiny",
            "tumpa",
        ]

        # A special case for the Kaluga board that has a separate interface config
        if board.id == "esp32-s2-kaluga-1":
            supported_debug_tools.append("ftdi")
        if board.get("build.mcu", "") in ("esp32c3", "esp32c5", "esp32c6", "esp32s3", "esp32h2", "esp32p4"):
            supported_debug_tools.append("esp-builtin")

        upload_protocol = board.manifest.get("upload", {}).get("protocol")
        upload_protocols = board.manifest.get("upload", {}).get("protocols", [])
        if debug:
            upload_protocols.extend(supported_debug_tools)
        if upload_protocol and upload_protocol not in upload_protocols:
            upload_protocols.append(upload_protocol)
        board.manifest["upload"]["protocols"] = upload_protocols

        if "tools" not in debug:
            debug["tools"] = {}

        for link in upload_protocols:
            if link in non_debug_protocols or link in debug["tools"]:
                continue

            if link in ("jlink", "cmsis-dap"):
                openocd_interface = link
            elif link in ("esp-prog", "ftdi"):
                if board.id == "esp32-s2-kaluga-1":
                    openocd_interface = "ftdi/esp32s2_kaluga_v1"
                else:
                    openocd_interface = "ftdi/esp32_devkitj_v1"
            elif link == "esp-bridge":
                openocd_interface = "esp_usb_bridge"
            elif link == "esp-builtin":
                openocd_interface = "esp_usb_jtag"
            else:
                openocd_interface = "ftdi/" + link

            server_args = [
                "-s",
                "$PACKAGE_DIR/share/openocd/scripts",
                "-f",
                "interface/%s.cfg" % openocd_interface,
                "-f",
                "%s/%s"
                % (
                    ("target", debug.get("openocd_target"))
                    if "openocd_target" in debug
                    else ("board", debug.get("openocd_board"))
                ),
            ]

            debug["tools"][link] = {
                "server": {
                    "package": "tool-openocd",
                    "executable": "bin/openocd",
                    "arguments": server_args,
                },
                "init_break": "thb app_main",
                "init_cmds": [
                    "define pio_reset_halt_target",
                    "   monitor reset halt",
                    "   flushregs",
                    "end",
                    "define pio_reset_run_target",
                    "   monitor reset",
                    "end",
                    "target extended-remote $DEBUG_PORT",
                    "$LOAD_CMDS",
                    "pio_reset_halt_target",
                    "$INIT_BREAK",
                ],
                "onboard": link in debug.get("onboard_tools", []),
                "default": link == debug.get("default_tool"),
            }

            # Avoid erasing Arduino Nano bootloader by preloading app binary
            if board.id == "arduino_nano_esp32":
                debug["tools"][link]["load_cmds"] = "preload"
        board.manifest["debug"] = debug
        return board

    def configure_debug_session(self, debug_config):
        build_extra_data = debug_config.build_data.get("extra", {})
        flash_images = build_extra_data.get("flash_images", [])

        if "openocd" in (debug_config.server or {}).get("executable", ""):
            debug_config.server["arguments"].extend(
                ["-c", "adapter speed %s" % (debug_config.speed or "5000")]
            )

        ignore_conds = [
            debug_config.load_cmds != ["load"],
            not flash_images,
            not all([os.path.isfile(item["path"]) for item in flash_images]),
        ]

        if any(ignore_conds):
            return

        load_cmds = [
            'monitor program_esp "{{{path}}}" {offset} verify'.format(
                path=to_unix_path(item["path"]), offset=item["offset"]
            )
            for item in flash_images
        ]
        load_cmds.append(
            'monitor program_esp "{%s.bin}" %s verify'
            % (
                to_unix_path(debug_config.build_data["prog_path"][:-4]),
                build_extra_data.get("application_offset", "0x10000"),
            )
        )
        debug_config.load_cmds = load_cmds
