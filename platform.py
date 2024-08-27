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
import shutil
from os.path import isfile, join

from platformio.public import PlatformBase, to_unix_path
from platformio.proc import get_pythonexe_path
#from platformio.package.manager.tool import ToolPackageManager
from platformio.project.config import ProjectConfig

python_exe = get_pythonexe_path()
#pm = ToolPackageManager()

IDF_TOOLS_PATH_DEFAULT = os.path.join(os.path.expanduser("~"), ".espressif")
IDF_TOOLS = os.path.join(ProjectConfig.get_instance().get("platformio", "packages_dir"), "tl-install", "tools", "idf_tools.py")
IDF_TOOLS_FLAG = ["install"]
IDF_TOOLS_CMD = [python_exe, IDF_TOOLS] + IDF_TOOLS_FLAG

class Espressif32Platform(PlatformBase):
    def configure_default_packages(self, variables, targets):
        if not variables.get("board"):
            return super().configure_default_packages(variables, targets)

        board_config = self.board_config(variables.get("board"))
        mcu = variables.get("board_build.mcu", board_config.get("build.mcu", "esp32"))
        frameworks = variables.get("pioframework", [])
        tl_flag = bool(os.path.exists(IDF_TOOLS))

        # IDF Install is needed only one time
        if not os.path.exists(join(IDF_TOOLS_PATH_DEFAULT, "tools")) and tl_flag:
            rc = subprocess.call(IDF_TOOLS_CMD)
            if rc != 0:
                sys.stderr.write("Error: Couldn't execute 'idf_tools.py install'\n")
            else:
                shutil.copytree(join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-packages"), join(IDF_TOOLS_PATH_DEFAULT, "tools"), symlinks=False, ignore=None, ignore_dangling_symlinks=False, dirs_exist_ok=True)

        if tl_flag:
            # Install all tools and toolchains
            self.packages["tl-install"]["optional"] = True
            for p in self.packages:
                if p in ("tool-mklittlefs", "tool-mkfatfs", "tool-mkspiffs", "tool-dfuutil", "tool-openocd", "tool-cmake", "tool-ninja", "tool-cppcheck", "tool-clangtidy", "tool-pvs-studio", "contrib-piohome", "contrib-pioremote", "tc-ulp", "tc-rv32", "tl-xt-gdb", "tl-rv-gdb"):
                    tl_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", p)
                    self.packages[p]["optional"] = False
                    self.packages[p]["version"] = tl_path
            # Enable common packages for IDF and mixed Arduino+IDF projects
            for p in self.packages:
                if p in ("tool-cmake", "tool-ninja", "tc-ulp"):
                    self.packages[p]["optional"] = False if "espidf" in frameworks else True
            # Enabling of following tools is not needed, installing is enough
            for p in self.packages:
                if p in ("contrib-pioremote", "contrib-piohome", "tool-scons"):
                    try:
                        pkg_dir = pm.get_package(p).path
                        # When package is not found an execption happens -> install is forced
                        # else the are removed from current env
                        self.packages[p]["optional"] = True
                    except:
                        pass


        # Enable debug tool gdb only when build debug is enabled
        if variables.get("build_type") or  "debug" in "".join(targets):
            self.packages["tl-rv-gdb"]["optional"] = False if mcu in ["esp32c2", "esp32c3", "esp32c6", "esp32h2"] else True
            self.packages["tl-xt-gdb"]["optional"] = False if not mcu in ["esp32c2", "esp32c3", "esp32c6", "esp32h2"] else True
        else:
            self.packages["tl-rv-gdb"]["optional"] = True
            self.packages["tl-xt-gdb"]["optional"] = True

        # Enable check tools only when "check_tool" is enabled
        for p in self.packages:
            if p in ("tool-cppcheck", "tool-clangtidy", "tool-pvs-studio"):
                self.packages[p]["optional"] = False if str(variables.get("check_tool")).strip("['']") in p else True

        if "arduino" in frameworks:
            self.packages["framework-arduinoespressif32"]["optional"] = False
            self.packages["framework-arduinoespressif32-libs"]["optional"] = False

        if "".join(targets) in ("upload", "buildfs", "uploadfs"):
            filesystem = variables.get("board_build.filesystem", "littlefs")
            if filesystem == "littlefs":
                # Use mklittlefs v3.2.0 to generate FS
                tl_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-mklittlefs")
                self.packages["tool-mklittlefs"]["optional"] = False
                self.packages["tool-mklittlefs"]["version"] = tl_path
                del self.packages["tool-mkfatfs"]
                del self.packages["tool-mkspiffs"]
            elif filesystem == "fatfs":
                self.packages["tool-mkfatfs"]["optional"] = False
                del self.packages["tool-mklittlefs"]
                del self.packages["tool-mkspiffs"]
            elif filesystem == "spiffs":
                self.packages["tool-mkspiffs"]["optional"] = False
                del self.packages["tool-mkfatfs"]
                del self.packages["tool-mklittlefs"]
        else:
            del self.packages["tool-mklittlefs"]
            del self.packages["tool-mkfatfs"]
            del self.packages["tool-mkspiffs"]

        if variables.get("upload_protocol"):
            self.packages["tool-openocd"]["optional"] = False
        else:
            del self.packages["tool-openocd"]

        if "downloadfs" in targets:
            filesystem = variables.get("board_build.filesystem", "littlefs")
            if filesystem == "littlefs":
                # Use mklittlefs v4.0.0 to unpack, older version is incompatible
                tl_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tool-mklittlefs400")
                self.packages["tool-mklittlefs"]["optional"] = False
                self.packages["tool-mklittlefs"]["version"] = tl_path

        # Currently only Arduino Nano ESP32 uses the dfuutil tool as uploader
        if variables.get("board") == "arduino_nano_esp32":
            self.packages["tool-dfuutil"]["optional"] = False
        else:
            del self.packages["tool-dfuutil"]

        # Enable needed toolchains
        for available_mcu in ("esp32", "esp32s2", "esp32s3"):
            if available_mcu == mcu and tl_flag:
                tc_path = "file://" + join(IDF_TOOLS_PATH_DEFAULT, "tools", "tc-xt-%s" % mcu)
                self.packages["tc-xt-%s" % mcu]["optional"] = False
                self.packages["tc-xt-%s" % mcu]["version"] = tc_path
                if available_mcu == "esp32":
                    del self.packages["tc-rv32"]
        # Enable ULP toolchains
        if mcu in ("esp32s2", "esp32s3", "esp32c2", "esp32c3", "esp32c6", "esp32h2"):
            if mcu in ("esp32c2", "esp32c3", "esp32c6", "esp32h2"):
                del self.packages["tc-ulp"]
            # RISC-V based toolchain for ESP32C3, ESP32C6 ESP32S2, ESP32S3 ULP
            if tl_flag:
                self.packages["tc-rv32"]["optional"] = False

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
        if board.get("build.mcu", "") in ("esp32c3", "esp32c6", "esp32s3", "esp32h2"):
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
