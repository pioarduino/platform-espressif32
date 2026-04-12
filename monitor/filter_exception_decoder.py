# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
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

import binascii
import glob
import json
import os
import re
import shlex
import struct
import subprocess
import sys
import tempfile
import threading
import types
from collections import deque
from pathlib import Path

# This file serves three roles:
#
# 1. As a PlatformIO monitor filter (loaded by PlatformIO, class
#    Esp32ExceptionDecoder is instantiated, rx() processes serial data).
#
# 2. As a standalone GDB RSP server (launched by GDB via
#    "target remote | python -u <this_file> --rsp-server <json>").
#
# 3. As a standalone CLI tool for offline crash log decoding.
#
# In modes 2 and 3, PlatformIO packages are not required, so imports
# are guarded to avoid ImportError.

_RSP_SERVER_MODE = len(sys.argv) >= 2 and sys.argv[1] == "--rsp-server"
# CLI mode: has arguments and first arg looks like a file path or option (no filesystem check)
_CLI_MODE = (len(sys.argv) >= 2 and 
             sys.argv[1] not in ("--rsp-server",) and
             (sys.argv[1].startswith("-") or "/" in sys.argv[1] or "\\" in sys.argv[1]))
# Standalone mode: running as main script, RSP server, or CLI mode
_STANDALONE_MODE = (__name__ == "__main__") or _RSP_SERVER_MODE or _CLI_MODE

if not _STANDALONE_MODE:
    # PlatformIO monitor filter mode - import dependencies
    from platformio.package.manager.tool import ToolPackageManager
    from platformio.compat import IS_WINDOWS
    from platformio.exception import PlatformioException
    from platformio.public import (
        DeviceMonitorFilterBase,
        load_build_metadata,
    )
else:
    # Standalone mode - create minimal shims
    IS_WINDOWS = sys.platform == "win32"
    DeviceMonitorFilterBase = object
    
    class PlatformioException(Exception):
        pass
    
    class ToolPackageManager:
        def get_package(self, name):
            return None
    
    def load_build_metadata(project_dir, environment, cache=True):
        raise PlatformioException("Not available in standalone mode")

try:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.constants import SH_FLAGS

    HAS_PYELFTOOLS = True
except ImportError:
    HAS_PYELFTOOLS = False


# By design, __init__ is called inside miniterm and we can't pass context to it.
# pylint: disable=attribute-defined-outside-init

# RISC-V ILP32 GDB register order: x0..x31 + pc (= MEPC)
GDB_REGS_RISCV_ILP32 = [
    "X0", "RA", "SP", "GP",
    "TP", "T0", "T1", "T2",
    "S0/FP", "S1", "A0", "A1",
    "A2", "A3", "A4", "A5",
    "A6", "A7", "S2", "S3",
    "S4", "S5", "S6", "S7",
    "S8", "S9", "S10", "S11",
    "T3", "T4", "T5", "T6",
    "MEPC",
]


class PcAddressMatcher:
    """
    Filters addresses by checking whether they fall into an executable
    ELF section (SHF_EXECINSTR).  This avoids unnecessary addr2line
    subprocess calls for data addresses, timestamps, or padding values.

    Requires pyelftools.  If the ELF file cannot be read the matcher
    silently accepts every address (fail-open).
    """

    def __init__(self, elf_path):
        self.intervals = []
        try:
            with open(elf_path, "rb") as f:
                elf = ELFFile(f)
                for section in elf.iter_sections():
                    if section["sh_flags"] & SH_FLAGS.SHF_EXECINSTR:
                        start = section["sh_addr"]
                        size = section["sh_size"]
                        if size > 0:
                            self.intervals.append((start, start + size))
            self.intervals.sort()
        except (FileNotFoundError, NotImplementedError, Exception) as e:
            sys.stderr.write(
                "PcAddressMatcher: failed to load executable sections from %s: %s\n"
                % (elf_path, e)
            )
            self.intervals = []

    def is_executable_address(self, addr):
        """Return True if *addr* (int) lies inside an executable section."""
        if not self.intervals:
            return True  # fail-open when no section info available
        for start, end in self.intervals:
            if start > addr:
                return False
            if start <= addr < end:
                return True
        return False


class Esp32ExceptionDecoder(DeviceMonitorFilterBase):
    """
    PlatformIO device monitor filter for decoding ESP32 exception backtraces.

    Uses ELF-section filtering (PcAddressMatcher) as the primary mechanism
    to decide which addresses to decode.  Falls back to keyword-based
    context detection when pyelftools is unavailable.

    Supports addr2line batching and GDB-based stack unwinding for RISC-V.
    """

    NAME = "esp32_exception_decoder"

    # -- Regex patterns ----------------------------------------------------------

    # PC:SP pairs in backtrace lines
    ADDR_PATTERN = re.compile(r"((?:0x[0-9a-fA-F]{8}:0x[0-9a-fA-F]{8}(?: |$))+)")
    ADDR_SPLIT = re.compile(r"[ :]")
    PREFIX_RE = re.compile(r"^ *")
    
    # Patterns that indicate we're in an exception/backtrace context
    BACKTRACE_KEYWORDS = re.compile(
        r"(Backtrace:|"
        r"\bPC:\s*0x[0-9a-fA-F]{8}\b|"
        r"abort\(\) was called at PC|"
        r"Guru Meditation Error:|"
        r"panic'ed|"
        r"register dump:|"
        r"Stack smashing protect failure!|"
        r"CORRUPT HEAP:|"
        r"assertion .* failed:|"
        r"Debug exception reason:|"
        r"Undefined behavior of type)",
        re.IGNORECASE
    )

    # Chip name mapping for ROM ELF files
    CHIP_NAME_MAP = {
        "esp32": "esp32",
        "esp32s2": "esp32s2",
        "esp32s3": "esp32s3",
        "esp32c2": "esp32c2",
        "esp32c3": "esp32c3",
        "esp32c5": "esp32c5",
        "esp32c6": "esp32c6",
        "esp32h2": "esp32h2",
        "esp32p4": "esp32p4",
    }

    # Stack memory dump: "3fca0000: 0x3fce0000 0x3fce0000 ..."
    STACK_MEM_LINE = re.compile(
        r"^\s*[0-9a-fA-F]{8}:\s+((?:0x[0-9a-fA-F]{8}\s*)+)"
    )

    # Register dump entries: "MEPC    : 0x00000000"
    REGISTER_ENTRY = re.compile(
        r"([A-Z][A-Z0-9/]+)\s*:\s*(0x[0-9a-fA-F]{8})"
    )

    # RISC-V panic dump detection
    RISCV_REG_DUMP_HEADER = re.compile(
        r"Core\s+(\d+)\s+register dump:", re.IGNORECASE
    )
    STACK_MEM_HEADER = re.compile(r"Stack memory:", re.IGNORECASE)

    # Fallback context detection (when PcAddressMatcher is unavailable)
    BACKTRACE_KEYWORDS = re.compile(
        r"(Backtrace:|"
        r"Stack memory:|"
        r"\bPC:\s*0x[0-9a-fA-F]{8}\b|"
        r"abort\(\) was called|"
        r"Guru Meditation Error:|"
        r"panic'ed|"
        r"register dump:|"
        r"Stack smashing|"
        r"CORRUPT HEAP:|"
        r"assertion .* failed:|"
        r"Debug exception reason:|"
        r"ELF file SHA256:)",
        re.IGNORECASE | re.MULTILINE
    )
    REBOOT_RE = re.compile(r"^\s*Rebooting\.\.\.", re.IGNORECASE)

    # addr2line batch output: address header line
    _ADDR2LINE_HEADER_RE = re.compile(r"^0x[0-9a-fA-F]+$")
    _DISCRIMINATOR_RE = re.compile(r"\s*\(discriminator \d+\)")

    # -- Chip / exception tables -------------------------------------------------

    CHIP_NAME_MAP = {
        "esp32": "esp32",
        "esp32s2": "esp32s2",
        "esp32s3": "esp32s3",
        "esp32c2": "esp32c2",
        "esp32c3": "esp32c3",
        "esp32c5": "esp32c5",
        "esp32c6": "esp32c6",
        "esp32h2": "esp32h2",
        "esp32h4": "esp32h4",
        "esp32p4": "esp32p4",
    }

    XTENSA_EXCEPTIONS = (
        "IllegalInstruction",           # 0
        "Syscall",                      # 1
        "InstructionFetchError",        # 2
        "LoadStoreError",               # 3
        "Level1Interrupt",              # 4
        "Alloca",                       # 5
        "IntegerDivideByZero",          # 6
        "reserved",                     # 7
        "Privileged",                   # 8
        "LoadStoreAlignment",           # 9
        "reserved",                     # 10
        "reserved",                     # 11
        "InstrPIFDataError",            # 12
        "LoadStorePIFDataError",        # 13
        "InstrPIFAddrError",            # 14
        "LoadStorePIFAddrError",        # 15
        "InstTLBMiss",                  # 16
        "InstTLBMultiHit",              # 17
        "InstFetchPrivilege",           # 18
        "reserved",                     # 19
        "InstFetchProhibited",          # 20
        "reserved",                     # 21
        "reserved",                     # 22
        "reserved",                     # 23
        "LoadStoreTLBMiss",             # 24
        "LoadStoreTLBMultiHit",         # 25
        "LoadStorePrivilege",           # 26
        "reserved",                     # 27
        "LoadProhibited",               # 28
        "StoreProhibited",              # 29
    )

    RISCV_EXCEPTIONS = types.MappingProxyType({
        0x0: "Instruction address misaligned",
        0x1: "Instruction access fault",
        0x2: "Illegal instruction",
        0x3: "Breakpoint",
        0x4: "Load address misaligned",
        0x5: "Load access fault",
        0x6: "Store/AMO address misaligned",
        0x7: "Store/AMO access fault",
        0x8: "Environment call from U-mode",
        0x9: "Environment call from S-mode",
        0xb: "Environment call from M-mode",
        0xc: "Instruction page fault",
        0xd: "Load page fault",
        0xf: "Store/AMO page fault",
    })

    # Standard RISC-V interrupt causes (MCAUSE with bit 31 set).
    # Lower 31 bits of MCAUSE identify the interrupt source.
    RISCV_INTERRUPT_CAUSES = types.MappingProxyType({
        1: "Supervisor software interrupt",
        3: "Machine software interrupt",
        5: "Supervisor timer interrupt",
        7: "Machine timer interrupt",
        9: "Supervisor external interrupt",
        11: "Machine external interrupt",
    })

    NON_CODE_REGISTERS = frozenset({
        "EXCVADDR",
        "MTVAL",
        "MSTATUS", "MHARTID",
        "PS",
        "SAR",
        "LBEG", "LEND", "LCOUNT",
    })

    # RISC-V panic accumulator states
    _RISCV_IDLE = 0
    _RISCV_REGS = 1
    _RISCV_STACK = 2

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def __call__(self):
        """Initialize the filter when the monitor activates it.

        Called by PlatformIO's miniterm.  Sets up all internal state, locates
        the firmware ELF, addr2line, ROM ELF, and (for RISC-V) GDB.

        Returns:
            self: The initialized filter instance.
        """
        self.buffer = ""
        self.firmware_path = None
        self.addr2line_path = None
        self.rom_elf_path = None
        self._addr_cache = {}           # (addr_str, elf_path) → decoded str | None
        self._firmware_matcher = None   # PcAddressMatcher for firmware ELF
        self._rom_matcher = None        # PcAddressMatcher for ROM ELF
        self._has_working_matcher = False  # True when firmware matcher has intervals
        self._is_riscv = False          # True when toolchain is RISC-V based
        self._gdb_path = None           # Path to riscv32-esp-elf-gdb (or None)

        # Serialization lock — ensures rx() processing is never concurrent.
        self._rx_lock = threading.Lock()

        # Bounded input buffer (64 KiB). Incoming serial data is appended
        # here; when the buffer is full further data is not buffered for
        # decoding (pass-through) until the current processing cycle drains it.
        
        self._buf_lock = threading.Lock()  # guards _rx_buf / _rx_buf_bytes
        self._rx_buf = deque()
        self._rx_buf_bytes = 0
        self._RX_BUF_MAX = 65536        # 64 KiB

        # RISC-V panic accumulator — collects register + stack dump across
        # multiple rx() calls so GDB can produce a proper backtrace.
        self._riscv_state = self._RISCV_IDLE
        self._riscv_regs = {}           # reg_name → int value
        self._riscv_stack_lines = []    # raw "addr: 0xWORD …" lines

        # Fallback keyword-based context tracking, used only when
        # PcAddressMatcher is unavailable (pyelftools missing or ELF unreadable).
        self._fallback_context = False
        self._fallback_lines = 0

        self.enabled = self.setup_paths()

        if self.config.get("env:" + self.environment, "build_type") != "debug":
            print(
                """
Please build project in debug configuration to get more details about an exception.
See https://docs.platformio.org/page/projectconf/build_configurations.html

"""
            )

        return self

    # -------------------------------------------------------------------------
    # Path / tool detection
    # -------------------------------------------------------------------------

    def get_chip_name(self, data):
        """Determine the ESP32 chip variant.

        Longest chip keys are compared first so that ``"esp32s3"`` is not
        confused with ``"esp32"``.

        Returns:
            Chip name string (e.g. ``"esp32c3"``), defaults to ``"esp32"``.
        """
        sorted_chips = sorted(self.CHIP_NAME_MAP.keys(), key=len, reverse=True)
        env_section = "env:" + self.environment
        board_mcu = None
        try:
            board_name = self.config.get(env_section, "board")
            if board_name:
                bdirs = [
                    self.config.get("platformio", "boards_dir"),
                    os.path.join(
                        self.config.get("platformio", "core_dir"), "boards"
                    ),
                    str(Path(__file__).parent.parent / "boards"),
                ]
                for boards_dir in bdirs:
                    board_json = os.path.join(boards_dir, board_name + ".json")
                    if os.path.isfile(board_json):
                        with open(board_json) as fh:
                            board_data = json.load(fh)
                        mcu = board_data.get("build", {}).get("mcu", "")
                        if mcu:
                            board_mcu = mcu.lower()
                        break
        except Exception:
            pass

        if board_mcu:
            for chip_key in sorted_chips:
                if chip_key in board_mcu:
                    return self.CHIP_NAME_MAP[chip_key]

        return "esp32"

    def find_rom_elf(self, chip_name):
        """Locate the ROM ELF file for the given chip variant.

        Searches the ``tool-esp-rom-elfs`` package for ELF files matching
        *chip_name* and picks the one with the lowest revision number for
        maximum compatibility.

        Args:
            chip_name: Chip variant (e.g. "esp32s3").

        Returns:
            Absolute path to the ROM ELF, or ``None`` if not found.
        """
        try:
            # Use ToolPackageManager to access already installed packages
            pm = ToolPackageManager()

            # Get the tool-esp-rom-elfs package (must be defined in platform.json)
            pkg = pm.get_package("tool-esp-rom-elfs")

            if not pkg:
                sys.stderr.write(
                    "%s: tool-esp-rom-elfs package not found. "
                    "Ensure it is defined in platform.json dependencies.\n"
                    % self.__class__.__name__
                )
                return None

            rom_elfs_dir = pkg.path

            if not rom_elfs_dir or not os.path.isdir(rom_elfs_dir):
                sys.stderr.write(
                    "%s: ROM ELFs directory not found at %s\n"
                    % (self.__class__.__name__, rom_elfs_dir)
                )
                return None

            patterns = [
                Path(rom_elfs_dir) / f"{chip_name}_rev*_rom.elf",
                Path(rom_elfs_dir) / f"{chip_name}_rev*.elf",
                Path(rom_elfs_dir) / f"{chip_name}*_rom.elf",
                Path(rom_elfs_dir) / f"{chip_name}*.elf",
            ]

            rom_files = []
            for pattern in patterns:
                rom_files.extend(glob.glob(str(pattern)))
            rom_files = sorted(set(rom_files))
            if not rom_files:
                sys.stderr.write(
                    "%s: No ROM ELF files found for chip %s in %s\n"
                    % (self.__class__.__name__, chip_name, rom_elfs_dir)
                )
                return None

            def _rev_key(path):
                m = re.search(r"_rev(\d+)", os.path.basename(path))
                return int(m.group(1)) if m else 10**9

            rom_files.sort(key=_rev_key)
            return rom_files[0]

        except (PlatformioException, OSError) as e:
            sys.stderr.write(
                "%s: Error accessing ROM ELF package: %s\n"
                % (self.__class__.__name__, e)
            )
            return None

    def setup_paths(self):
        """Locate firmware ELF, addr2line, ROM ELF, and (optionally) GDB.

        Reads PlatformIO build metadata, derives toolchain paths, builds
        PcAddressMatcher instances for ELF-section filtering, and detects
        whether the target is RISC-V (to enable GDB stack unwinding).

        Returns:
            ``True`` if the minimum required tools (firmware ELF + addr2line)
            were found and the filter can operate; ``False`` otherwise.
        """
        self.project_dir = os.path.abspath(self.project_dir)
        try:
            data = load_build_metadata(
                self.project_dir, self.environment, cache=True
            )

            # Firmware ELF
            self.firmware_path = data["prog_path"]
            if not os.path.isfile(self.firmware_path):
                sys.stderr.write(
                    "%s: firmware at %s does not exist, rebuild the project?\n"
                    % (self.__class__.__name__, self.firmware_path)
                )
                return False

            # addr2line
            cc_path = data.get("cc_path", "")
            if "-gcc" in cc_path:
                path = cc_path.replace("-gcc", "-addr2line")
                if os.path.isfile(path):
                    self.addr2line_path = path
            elif "-clang" in cc_path:
                path = cc_path.replace("-clang", "-addr2line")
                if os.path.isfile(path):
                    self.addr2line_path = path

            if not self.addr2line_path:
                sys.stderr.write(
                    "%s: disabling, failed to find addr2line.\n"
                    % self.__class__.__name__
                )
                return False

            # ROM ELF
            chip_name = self.get_chip_name(data)
            self.rom_elf_path = self.find_rom_elf(chip_name)

            if self.rom_elf_path:
                sys.stderr.write(
                    "%s: ROM ELF found at %s\n"
                    % (self.__class__.__name__, self.rom_elf_path)
                )
            else:
                sys.stderr.write(
                    "%s: ROM ELF not found for chip %s, "
                    "ROM addresses will not be decoded\n"
                    % (self.__class__.__name__, chip_name)
                )

            # ELF-section matchers
            if HAS_PYELFTOOLS:
                self._firmware_matcher = PcAddressMatcher(self.firmware_path)
                if self.rom_elf_path:
                    self._rom_matcher = PcAddressMatcher(self.rom_elf_path)
                self._has_working_matcher = bool(
                    self._firmware_matcher.intervals
                )

            # RISC-V detection and GDB lookup
            self._is_riscv = "riscv" in cc_path.lower()
            if self._is_riscv:
                self._find_riscv_gdb()

            return True

        except PlatformioException as e:
            sys.stderr.write(
                "%s: disabling, exception while looking for addr2line: %s\n"
                % (self.__class__.__name__, e)
            )
            return False

    def _find_riscv_gdb(self):
        """Try to locate the RISC-V GDB binary from the platform package.

        Sets ``self._gdb_path`` if found.  GDB is required for the RSP-based
        stack unwinding on RISC-V targets; without it the filter falls back
        to addr2line-only decoding.
        """
        try:
            pm = ToolPackageManager()
            pkg = pm.get_package("tool-riscv32-esp-elf-gdb")
            if pkg and pkg.path:
                pkg_path = pkg.path
                gdb_bin = str(Path(pkg_path) / "bin" / "riscv32-esp-elf-gdb")
                if IS_WINDOWS:
                    gdb_bin += ".exe"
                if os.path.isfile(gdb_bin):
                    self._gdb_path = gdb_bin
        except (PlatformioException, OSError):
            pass

        if self._gdb_path:
            sys.stderr.write(
                "%s: RISC-V GDB found for stack unwinding\n"
                % self.__class__.__name__
            )
        else:
            sys.stderr.write(
                "%s: RISC-V GDB not found, "
                "stack unwinding will be limited to addr2line\n"
                % self.__class__.__name__
            )

    def _find_toolchain_in_path(self, tool_names):
        """Search for a toolchain binary in common locations.
        
        Args:
            tool_names: List of possible binary names to search for
            
        Returns:
            Path to the tool if found, None otherwise
        """
        # Try using ToolPackageManager first (PlatformIO mode)
        try:
            pm = ToolPackageManager()
            for tool_name in tool_names:
                # Derive possible package names from tool name
                # e.g., "riscv32-esp-elf-addr2line" could be in:
                #   - "toolchain-riscv32-esp-elf"
                #   - "toolchain-riscv32-esp"
                # e.g., "xtensa-esp32-elf-addr2line" could be in:
                #   - "toolchain-xtensa-esp32-elf"
                #   - "toolchain-xtensa-esp32"
                base_name = tool_name.rsplit("-", 1)[0]  # Remove last part (addr2line, gdb, etc.)
                
                # Try different package name variations
                pkg_name_candidates = [
                    "toolchain-" + base_name,  # e.g., toolchain-riscv32-esp-elf
                ]
                
                # Also try without the "-elf" suffix if present
                if base_name.endswith("-elf"):
                    pkg_name_candidates.append("toolchain-" + base_name[:-4])  # e.g., toolchain-riscv32-esp
                
                for pkg_name in pkg_name_candidates:
                    pkg = pm.get_package(pkg_name)
                    if pkg and pkg.path:
                        tool_bin = str(Path(pkg.path) / "bin" / tool_name)
                        if IS_WINDOWS:
                            tool_bin += ".exe"
                        if os.path.isfile(tool_bin):
                            return tool_bin
        except (PlatformioException, OSError, AttributeError):
            # Fall back to manual search if ToolPackageManager is not available
            pass
        
        # Fallback: Search in PlatformIO packages directory manually
        # Use the same logic as ToolPackageManager mode to find the correct toolchain
        home = os.path.expanduser("~")
        pio_packages = os.path.join(home, ".platformio/packages")
        
        if os.path.isdir(pio_packages):
            for tool_name in tool_names:
                # Derive possible package names from tool name (same logic as above)
                base_name = tool_name.rsplit("-", 1)[0]
                
                pkg_name_candidates = [
                    "toolchain-" + base_name,
                ]
                
                if base_name.endswith("-elf"):
                    pkg_name_candidates.append("toolchain-" + base_name[:-4])
                
                for pkg_name in pkg_name_candidates:
                    pkg_dir = os.path.join(pio_packages, pkg_name)
                    
                    if os.path.isdir(pkg_dir):
                        bin_dir = os.path.join(pkg_dir, "bin")
                        if os.path.isdir(bin_dir):
                            candidate = os.path.join(bin_dir, tool_name)
                            if IS_WINDOWS:
                                candidate += ".exe"
                            if os.path.isfile(candidate):
                                return candidate
        
        return None

    # -------------------------------------------------------------------------
    # Line filtering
    # -------------------------------------------------------------------------

    def _should_decode_line(self, line):
        """Determine if a line should be checked for decodable addresses.

        With working PcAddressMatcher all lines are processed (the matcher
        filters individual addresses).  Without matcher, fall back to
        keyword-based context detection.
        """
        if self._has_working_matcher:
            return True

        if self.REBOOT_RE.match(line):
            self._fallback_context = False
            return False

        if self.BACKTRACE_KEYWORDS.search(line):
            self._fallback_context = True
            self._fallback_lines = 0
            return True

        if self._fallback_context:
            self._fallback_lines += 1
            if self._fallback_lines > 50 or not line.strip():
                self._fallback_context = False
                return False
            return True

        return False

    # -------------------------------------------------------------------------
    # Exception description helpers
    # -------------------------------------------------------------------------

    def get_xtensa_exception(self, code):
        """Return the human-readable name of an Xtensa EXCCAUSE value, or None."""
        if 0 <= code < len(self.XTENSA_EXCEPTIONS):
            desc = self.XTENSA_EXCEPTIONS[code]
            if desc != "reserved":
                return desc
        return None

    def get_riscv_exception(self, code):
        """Return a human-readable description for a RISC-V MCAUSE value.

        MCAUSE bit 31 distinguishes interrupts (1) from exceptions (0).
        Returns a descriptive string, or None if the cause is unknown.
        """
        if code & 0x80000000:
            cause = code & 0x7FFFFFFF
            desc = self.RISCV_INTERRUPT_CAUSES.get(cause)
            if desc:
                return "Interrupt: " + desc
            return "Interrupt (cause %d)" % cause
        return self.RISCV_EXCEPTIONS.get(code)

    # -------------------------------------------------------------------------
    # Main rx() loop
    # -------------------------------------------------------------------------

    def rx(self, text):
        """Process incoming serial text and insert decoded backtraces.

        Incoming data is appended to a bounded 64 KiB buffer.  When the
        buffer is full, further data is not buffered for decoding (pass-through)
        until the current processing cycle finishes.  A lock ensures that all
        processing is strictly serialized — no concurrent rx() calls.

        For each complete line the method:

        1. Feeds RISC-V panic accumulator; when a full register + stack dump
           is collected, invokes GDB to produce a proper backtrace.
        2. Checks whether the line should be decoded (ELF-section matcher or
           fallback keyword context).
        3. Matches against known crash-output patterns (PC:SP backtrace,
           stack memory dump, register dump) and decodes addresses via
           addr2line in batch mode.

        Decoded output is spliced into *text* immediately after the
        originating line.

        Args:
            text: Raw text chunk received from the serial device.

        Returns:
            The text with decoded trace blocks inserted.
        """
        if not self.enabled:
            return text

        # Append to bounded buffer; discard if full.
        with self._buf_lock:
            text_len = len(text)
            if self._rx_buf_bytes + text_len > self._RX_BUF_MAX:
                return text
            self._rx_buf.append(text)
            self._rx_buf_bytes += text_len

        # Serialize processing — if another call is already running,
        # the data has been buffered above and will be picked up by
        # the active call.  Return empty string so the caller does not
        # display the original text (it will be emitted by _process_buffer).
        with self._rx_lock:
            out = []
            while True:
                out.append(self._process_buffer())
                with self._buf_lock:
                    if not self._rx_buf:
                        break
            return "".join(out)

    def _process_buffer(self):
        """Drain the bounded rx buffer and process all complete lines.

        Called while holding ``_rx_lock``.  Concatenates all buffered
        chunks, processes them line-by-line, and returns the result.
        """
        # Drain buffer atomically
        with self._buf_lock:
            chunks = list(self._rx_buf)
            self._rx_buf.clear()
            self._rx_buf_bytes = 0

        text = "".join(chunks)

        last = 0
        while True:
            idx = text.find("\n", last)
            if idx == -1:
                remainder = text[last:]
                if len(self.buffer) + len(remainder) <= 4096:
                    self.buffer += remainder
                # Return only the processed part (up to last), not the remainder
                return text[:last]

            line = text[last:idx]
            if self.buffer:
                line = self.buffer + line
                self.buffer = ""
            last = idx + 1

            # Feed RISC-V panic accumulator
            if self._is_riscv and self._feed_riscv_line(line):
                trace = self._invoke_gdb_backtrace()
                if trace:
                    text = text[: idx + 1] + trace + text[idx + 1 :]
                    last += len(trace)

            if not self._should_decode_line(line):
                continue

            # PC:SP backtrace
            m = self.ADDR_PATTERN.search(line)
            if m is not None:
                trace = self.build_backtrace(line, m.group(1))
                if trace:
                    text = text[: idx + 1] + trace + text[idx + 1 :]
                    last += len(trace)
                continue

            # Stack memory dump
            m = self.STACK_MEM_LINE.search(line)
            if m is not None:
                trace = self.build_stack_trace(line, m.group(1))
                if trace:
                    text = text[: idx + 1] + trace + text[idx + 1 :]
                    last += len(trace)
                continue

            # Register dump
            reg_matches = self.REGISTER_ENTRY.findall(line)
            if len(reg_matches) >= 2:
                trace = self.build_register_trace(line, reg_matches)
                if trace:
                    text = text[: idx + 1] + trace + text[idx + 1 :]
                    last += len(trace)

        return text

    # -------------------------------------------------------------------------
    # addr2line batching
    # -------------------------------------------------------------------------

    def _decode_batch(self, addrs, elf_path):
        """Decode multiple addresses in a single addr2line call (-fiaC)."""
        if not addrs:
            return

        addr_list = list(addrs)
        enc = "mbcs" if IS_WINDOWS else "utf-8"
        args = [self.addr2line_path, "-fiaC", "-e", elf_path] + addr_list

        try:
            raw = subprocess.check_output(args, timeout=10).decode(enc)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            for addr in addr_list:
                self._addr_cache[(addr, elf_path)] = None
            return

        # State-machine parser: split output into sections by address headers
        sections = []
        current_body = []

        for raw_line in raw.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if self._ADDR2LINE_HEADER_RE.match(stripped):
                sections.append(current_body)
                current_body = []
            else:
                current_body.append(stripped)
        sections.append(current_body)

        # First section (before first header) is empty — skip it
        body_sections = sections[1:] if sections else []

        # Correlate by position (addr2line preserves input order)
        for i, addr in enumerate(addr_list):
            if i < len(body_sections):
                self._finalize_batch_entry(addr, body_sections[i], elf_path)
            else:
                self._addr_cache[(addr, elf_path)] = None

    def _finalize_batch_entry(self, addr, lines, elf_path):
        """Parse function / file:line pairs and store in _addr_cache."""
        parts = []
        i = 0
        while i + 1 < len(lines):
            func = lines[i]
            loc = self._DISCRIMINATOR_RE.sub("", lines[i + 1])
            if func == "??" and loc.startswith("??:"):
                i += 2
                continue
            parts.append("%s at %s" % (func, loc))
            i += 2

        if not parts:
            self._addr_cache[(addr, elf_path)] = None
        else:
            output = parts[0]
            for p in parts[1:]:
                output += "\n     (inlined by) " + p
            self._addr_cache[(addr, elf_path)] = output

    def _prefetch_addresses(self, addrs):
        """Pre-populate _addr_cache in batch for a list of address strings."""
        lookups = []
        seen = set()
        for addr in addrs:
            if self.is_address_ignored(addr):
                continue
            if addr not in seen:
                seen.add(addr)
                lookups.append(addr)

        if not lookups:
            return

        # Batch against firmware ELF
        fw_batch = [
            a for a in lookups
            if (a, self.firmware_path) not in self._addr_cache
            and (
                self._firmware_matcher is None
                or self._firmware_matcher.is_executable_address(int(a, 16))
            )
        ]
        if fw_batch:
            self._decode_batch(fw_batch, self.firmware_path)

        # Batch unresolved against ROM ELF
        if self.rom_elf_path:
            rom_batch = [
                a for a in lookups
                if self._addr_cache.get((a, self.firmware_path)) is None
                and (a, self.rom_elf_path) not in self._addr_cache
                and (
                    self._rom_matcher is None
                    or self._rom_matcher.is_executable_address(int(a, 16))
                )
            ]
            if rom_batch:
                self._decode_batch(rom_batch, self.rom_elf_path)

    # -------------------------------------------------------------------------
    # Single-address decode (cache-first, falls back to subprocess)
    # -------------------------------------------------------------------------

    def decode_address(self, addr, elf_path):
        """Decode a single address via addr2line (cache-first).

        Checks ``_addr_cache`` before spawning a subprocess.  Uses the same
        ``-fiaC`` flags and parsing logic as the batch decoder so results
        are consistent regardless of code path.

        Args:
            addr: Address string (e.g. "0x400d1234").
            elf_path: Path to the ELF file containing debug symbols.

        Returns:
            Decoded string ("func at file:line") or ``None``.
        """
        cache_key = (addr, elf_path)
        if cache_key in self._addr_cache:
            return self._addr_cache[cache_key]

        enc = "mbcs" if IS_WINDOWS else "utf-8"
        args = [self.addr2line_path, "-fiaC", "-e", elf_path, addr]

        try:
            raw = subprocess.check_output(args, timeout=10).decode(enc)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self._addr_cache[cache_key] = None
            return None

        # Parse using the same logic as batch mode
        lines = [
            l.strip() for l in raw.splitlines() if l.strip()  # noqa: E741
        ]
        # Skip address header if present
        if lines and self._ADDR2LINE_HEADER_RE.match(lines[0]):
            lines = lines[1:]

        self._finalize_batch_entry(addr, lines, elf_path)
        return self._addr_cache.get(cache_key)

    # -------------------------------------------------------------------------
    # Address helpers
    # -------------------------------------------------------------------------

    def is_address_ignored(self, address):
        """Return True for empty or null addresses that should be skipped."""
        return address in ("", "0x00000000")

    def filter_addresses(self, addresses_str):
        """Split a PC:SP address string and strip trailing null addresses."""
        addresses = self.ADDR_SPLIT.split(addresses_str)
        size = len(addresses)
        while size > 1 and self.is_address_ignored(addresses[size - 1]):
            size -= 1
        return addresses[:size]

    def _resolve_address(self, addr):
        """Resolve a single address through firmware ELF, then ROM ELF.

        Applies PcAddressMatcher filtering before calling addr2line.

        Returns:
            ``(decoded_string, is_rom)`` or ``(None, False)`` if unresolved.
        """
        if self.is_address_ignored(addr):
            return None, False

        lookup = addr
        int_addr = int(lookup, 16)

        output = None
        if (
            self._firmware_matcher is None
            or self._firmware_matcher.is_executable_address(int_addr)
        ):
            output = self.decode_address(lookup, self.firmware_path)
        is_rom = False

        if output is None and self.rom_elf_path:
            if (
                self._rom_matcher is None
                or self._rom_matcher.is_executable_address(int_addr)
            ):
                output = self.decode_address(lookup, self.rom_elf_path)
                if output is not None:
                    is_rom = True

        if output is None:
            return None, False

        output = self.strip_project_dir(output)

        if is_rom:
            parts = output.split(" at ", 1)
            if len(parts) == 2:
                output = f"{parts[0]} in ROM"
            else:
                output = f"{output} in ROM"

        return output, is_rom

    # -------------------------------------------------------------------------
    # Trace builders (with batch pre-fetch)
    # -------------------------------------------------------------------------

    def build_backtrace(self, line, address_match):
        """Decode a PC:SP backtrace line into numbered source locations.

        Pre-fetches all addresses in a single batch call to addr2line,
        then formats the results as a numbered trace block.  The first
        address is treated as the faulting PC; subsequent addresses are
        return addresses (decremented by 1 for accurate call-site reporting).

        Returns:
            Formatted trace string, or empty string if nothing decoded.
        """
        addresses = self.filter_addresses(address_match)
        if not addresses:
            return ""

        self._prefetch_addresses(addresses)

        prefix_match = self.PREFIX_RE.match(line)
        prefix = prefix_match.group(0) if prefix_match is not None else ""

        trace = ""
        i = 0
        for j, addr in enumerate(addresses):
            output, is_rom = self._resolve_address(addr)
            if output is not None:
                fmt = "%s  #%-2d %s %s\n" if is_rom else "%s  #%-2d %s in %s\n"
                trace += fmt % (prefix, i, addr, output)
                i += 1

        return trace + "\n" if trace else ""

    def build_stack_trace(self, line, addresses_str):
        """Decode addresses from a stack memory dump line.

        Each 32-bit word on the line is checked; only those that fall into
        an executable ELF section and resolve via addr2line are shown.

        Returns:
            Formatted trace string, or empty string if nothing decoded.
        """
        addresses = re.findall(r"0x[0-9a-fA-F]{8}", addresses_str)
        if not addresses:
            return ""

        self._prefetch_addresses(addresses)

        prefix_match = self.PREFIX_RE.match(line)
        prefix = prefix_match.group(0) if prefix_match is not None else ""

        trace = ""
        for addr in addresses:
            output, _ = self._resolve_address(addr)
            if output is not None:
                trace += "%s  %s: %s\n" % (prefix, addr, output)

        return trace

    def build_register_trace(self, line, reg_matches):
        """Decode a register dump line.

        Annotates EXCCAUSE / MCAUSE with human-readable exception names.
        For code-address registers (PC, MEPC, RA, …) attempts addr2line
        resolution.  Non-code registers (EXCVADDR, MTVAL, PS, …) are
        skipped.

        Returns:
            Formatted annotation string, or empty string if nothing decoded.
        """
        # Pre-fetch code-address registers
        reg_addrs = []
        for reg_name, addr in reg_matches:
            if reg_name in ("EXCCAUSE", "MCAUSE"):
                continue
            if reg_name in self.NON_CODE_REGISTERS:
                continue
            reg_addrs.append(addr)
        self._prefetch_addresses(reg_addrs)

        prefix_match = self.PREFIX_RE.match(line)
        prefix = prefix_match.group(0) if prefix_match is not None else ""

        trace = ""
        for reg_name, addr in reg_matches:
            if reg_name == "EXCCAUSE":
                code = int(addr, 16)
                desc = self.get_xtensa_exception(code)
                if desc:
                    trace += "%s  %s: %s (%s)\n" % (
                        prefix, reg_name, addr, desc
                    )
                continue

            if reg_name == "MCAUSE":
                code = int(addr, 16)
                desc = self.get_riscv_exception(code)
                if desc:
                    trace += "%s  %s: %s (%s)\n" % (
                        prefix, reg_name, addr, desc
                    )
                continue

            if reg_name in self.NON_CODE_REGISTERS:
                continue

            output, _ = self._resolve_address(addr)
            if output is not None:
                trace += "%s  %s: %s: %s\n" % (prefix, reg_name, addr, output)

        return trace

    # -------------------------------------------------------------------------
    # RISC-V panic accumulation
    # -------------------------------------------------------------------------

    def _feed_riscv_line(self, line):
        """Feed a line to the RISC-V panic accumulator.

        Returns True when a complete register + stack dump has been collected.
        """
        m = self.RISCV_REG_DUMP_HEADER.search(line)
        if m:
            self._riscv_state = self._RISCV_REGS
            self._riscv_regs = {}
            self._riscv_stack_lines = []
            return False

        if self._riscv_state == self._RISCV_REGS:
            reg_matches = self.REGISTER_ENTRY.findall(line)
            if len(reg_matches) >= 2:
                for name, val in reg_matches:
                    self._riscv_regs[name] = int(val, 16)
                return False
            if (
                len(reg_matches) == 1
                and reg_matches[0][0] == "MHARTID"
                and self.is_address_ignored(reg_matches[0][1])
            ):
                self._riscv_regs["MHARTID"] = int(reg_matches[0][1], 16)
                return False

            if self.STACK_MEM_HEADER.search(line):
                self._riscv_state = self._RISCV_STACK
                return False

            if line.strip():
                self._riscv_state = self._RISCV_IDLE
            return False

        if self._riscv_state == self._RISCV_STACK:
            if self.STACK_MEM_LINE.match(line):
                self._riscv_stack_lines.append(line)
                return False

            # End of stack section
            if self._riscv_regs and self._riscv_stack_lines:
                self._riscv_state = self._RISCV_IDLE
                return True

            self._riscv_state = self._RISCV_IDLE
            return False

        return False

    # -------------------------------------------------------------------------
    # GDB-based RISC-V stack unwinding
    # -------------------------------------------------------------------------

    def _build_riscv_stack_data(self):
        """Parse accumulated stack memory lines into (base_addr, bytes).

        Uses per-line addresses to place words at their correct offsets,
        zero-filling any gaps from missing or out-of-order lines.
        """
        stack_data = bytearray()
        base_addr = None

        for line in self._riscv_stack_lines:
            m = re.match(
                r"\s*([0-9a-fA-F]{8}):\s+((?:0x[0-9a-fA-F]{8}\s*)+)", line
            )
            if not m:
                continue
            addr = int(m.group(1), 16)
            if base_addr is None:
                base_addr = addr
            elif addr < base_addr:
                # Line has a lower address than current base — prepend zeros
                delta = base_addr - addr
                stack_data = bytearray(b"\x00" * delta) + stack_data
                base_addr = addr
            words = re.findall(r"0x([0-9a-fA-F]{8})", m.group(2))
            for w in words:
                offset = addr - base_addr
                # Pad with zeros up to the current offset if there are gaps
                if offset > len(stack_data):
                    stack_data.extend(b"\x00" * (offset - len(stack_data)))
                if offset == len(stack_data):
                    stack_data.extend(struct.pack("<I", int(w, 16)))
                else:
                    # Overlapping write — overwrite existing bytes
                    packed = struct.pack("<I", int(w, 16))
                    stack_data[offset : offset + 4] = packed
                addr += 4

        return base_addr or 0, bytes(stack_data)

    def _invoke_gdb_backtrace(self):
        """Launch GDB to produce a proper backtrace from the RISC-V panic dump.

        Workflow:
          1. Serialize accumulated registers + stack bytes to a temp JSON file.
          2. Start ``riscv32-esp-elf-gdb --batch`` with the firmware ELF.
          3. GDB connects to a pipe target that re-executes *this file* as
             ``python -u <this_file> --rsp-server <tmp.json>``.
          4. The RSP server (see ``_run_rsp_server``) answers GDB's register
             and memory read requests from the captured panic data.
          5. GDB's ``bt`` command unwinds the stack and prints the backtrace.
          6. The backtrace lines are captured and returned for insertion into
             the monitor output.

        Returns:
            Formatted GDB backtrace string, or empty string on failure.
        """
        if not self._gdb_path or not self._riscv_regs:
            return ""

        stack_base, stack_data = self._build_riscv_stack_data()
        if not stack_data:
            return ""

        panic_info = {
            "regs": self._riscv_regs,
            "stack_base": stack_base,
            "stack_hex": binascii.hexlify(stack_data).decode("ascii"),
        }

        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="esp_panic_"
            )
            json.dump(panic_info, tmp)
            tmp.close()

            this_script = os.path.abspath(__file__)
            python_cmd = sys.executable

            if IS_WINDOWS:
                rsp_cmd = '"%s" -u "%s" --rsp-server "%s"' % (
                    python_cmd, this_script, tmp.name,
                )
            else:
                rsp_cmd = "%s -u %s --rsp-server %s" % (
                    shlex.quote(python_cmd),
                    shlex.quote(this_script),
                    shlex.quote(tmp.name),
                )

            gdb_args = [
                self._gdb_path,
                "--batch", "-n",
                self.firmware_path,
                "-ex", "set pagination off",
            ]

            if self.rom_elf_path:
                rom_elf_for_gdb = self.rom_elf_path.replace("\\", "/")
                gdb_args += [
                    "-ex", 'add-symbol-file "%s"' % rom_elf_for_gdb,
                ]

            gdb_args += [
                "-ex", "target remote | %s" % rsp_cmd,
                "-ex", "bt",
            ]

            enc = "mbcs" if IS_WINDOWS else "utf-8"
            output = subprocess.check_output(
                gdb_args, stderr=subprocess.DEVNULL, timeout=10
            ).decode(enc)

            bt_lines = []
            for bt_line in output.splitlines():
                stripped = bt_line.strip()
                if stripped.startswith("#"):
                    bt_lines.append("  " + stripped)

            if bt_lines:
                result = "  GDB Backtrace:\n" + "\n".join(bt_lines) + "\n\n"
                return self.strip_project_dir(result)
            return ""

        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError,
        ) as e:
            sys.stderr.write(
                "%s: GDB backtrace failed: %s\n"
                % (self.__class__.__name__, e)
            )
            return ""
        finally:
            if tmp and os.path.exists(tmp.name):
                os.unlink(tmp.name)

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    def strip_project_dir(self, trace):
        """Remove the absolute project directory prefix from file paths.

        Makes trace output more readable by showing relative paths only.
        """
        while True:
            idx = trace.find(self.project_dir)
            if idx == -1:
                break
            trace = trace[:idx] + trace[idx + len(self.project_dir) + 1 :]
        return trace


# ---------------------------------------------------------------------------
# GDB RSP Server  (invoked by GDB as pipe target: --rsp-server <json>)
# ---------------------------------------------------------------------------

def _run_rsp_server(panic_file):
    """Minimal GDB Remote Serial Protocol server for RISC-V panic data.

    This function is the entry point when GDB launches this file as a pipe
    target (``target remote | python -u <this_file> --rsp-server <json>``).

    It reads the captured register values and stack memory from the JSON file
    written by ``_invoke_gdb_backtrace()``, then speaks GDB RSP over
    stdin/stdout so GDB can query registers (``g`` packet) and memory
    (``m`` packet) and produce a backtrace.

    Supported RSP commands:
        ?             → stop reason (T05 / SIGTRAP)
        Hg / Hc       → set thread (always OK, single-threaded)
        qfThreadInfo  → list threads (m1)
        qC            → current thread (QC1)
        g             → all register values (x0..x31 + pc in ILP32 order)
        m addr,size   → memory read (served from captured stack region)
        k / vKill     → terminate
    """
    with open(panic_file, "r") as f:
        panic_data = json.load(f)

    regs = {k: int(v) if isinstance(v, str) else v
            for k, v in panic_data["regs"].items()}
    stack_base = panic_data["stack_base"]
    stack_data = binascii.unhexlify(panic_data["stack_hex"])

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    def respond(data):
        """Send an RSP packet ($data#checksum) and wait for ACK (+)."""
        checksum = sum(data.encode("ascii")) & 0xFF
        packet = ("$%s#%02x" % (data, checksum)).encode("ascii")
        stdout.write(packet)
        stdout.flush()
        ack = stdin.read(1)
        if ack == b"-":
            sys.exit(1)

    def get_regs():
        """Pack all registers as little-endian hex for the GDB 'g' response."""
        result = ""
        for name in GDB_REGS_RISCV_ILP32:
            val = regs.get(name, 0)
            result += binascii.hexlify(struct.pack("<I", val)).decode("ascii")
        return result

    def get_mem(addr, size):
        """Serve memory from the captured stack region; return 0x00 outside it."""
        result = ""
        for i in range(size):
            offset = (addr + i) - stack_base
            if 0 <= offset < len(stack_data):
                result += "%02x" % stack_data[offset]
            else:
                result += "00"
        return result

    while True:
        c = stdin.read(1)
        if not c:
            break
        if c == b"+":
            continue
        if c != b"$":
            continue

        data = b""
        while True:
            c = stdin.read(1)
            if not c:
                # EOF mid-packet — discard partial data and exit
                sys.exit(0)
            if c == b"#":
                checksum = stdin.read(2)  # checksum bytes
                if len(checksum) < 2:
                    sys.exit(0)
                break
            data += c

        stdout.write(b"+")
        stdout.flush()

        cmd = data.decode("ascii", errors="replace")

        if cmd == "?":
            respond("T05")
        elif cmd.startswith("Hg") or cmd.startswith("Hc"):
            respond("OK")
        elif cmd == "qfThreadInfo":
            respond("m1")
        elif cmd == "qsThreadInfo":
            respond("l")
        elif cmd == "qC":
            respond("QC1")
        elif cmd == "g":
            respond(get_regs())
        elif cmd.startswith("m"):
            try:
                parts = cmd[1:].split(",")
                addr = int(parts[0], 16)
                size = int(parts[1], 16)
                respond(get_mem(addr, size))
            except (ValueError, IndexError):
                respond("E01")
        elif cmd.startswith("vKill") or cmd == "k":
            respond("OK")
            break
        elif cmd == "qSymbol::":
            respond("OK")
        else:
            respond("")

    sys.exit(0)


# ---------------------------------------------------------------------------
# Standalone CLI Mode
# ---------------------------------------------------------------------------

def _find_toolchain_binaries(elf_path):
    """Auto-detect toolchain binaries (addr2line, GDB) based on ELF architecture.
    
    Returns:
        tuple: (addr2line_path, gdb_path, is_riscv)
    """
    addr2line_path = None
    gdb_path = None
    is_riscv = False
    
    # Detect architecture from ELF file
    try:
        with open(elf_path, "rb") as f:
            # Read ELF header to detect architecture
            elf_header = f.read(20)
            if len(elf_header) >= 18:
                e_machine = struct.unpack("<H", elf_header[18:20])[0]
                # 0xF3 = EM_RISCV, 0x5E = EM_XTENSA
                is_riscv = (e_machine == 0xF3)
    except (OSError, struct.error) as e:
        sys.stderr.write("Warning: Could not detect ELF architecture, defaulting to Xtensa: %s\n" % e)
    
    # Determine toolchain names based on architecture
    if is_riscv:
        addr2line_names = ["riscv32-esp-elf-addr2line"]
        gdb_names = ["riscv32-esp-elf-gdb"]
    else:
        addr2line_names = ["xtensa-esp32-elf-addr2line", "xtensa-esp-elf-addr2line"]
        gdb_names = ["xtensa-esp32-elf-gdb", "xtensa-esp-elf-gdb"]
    
    # Create a temporary decoder instance to use its search method
    decoder = Esp32ExceptionDecoder()
    addr2line_path = decoder._find_toolchain_in_path(addr2line_names)
    gdb_path = decoder._find_toolchain_in_path(gdb_names)
    
    return addr2line_path, gdb_path, is_riscv


def _run_standalone_decoder(elf_path, crash_log_path, output_path=None):
    """Run the decoder in standalone mode with provided ELF and crash log files.
    
    Args:
        elf_path: Path to firmware ELF file
        crash_log_path: Path to crash log text file
        output_path: Optional output file path (default: stdout)
    """
    # Validate inputs
    if not os.path.isfile(elf_path):
        sys.stderr.write("Error: ELF file not found: %s\n" % elf_path)
        sys.exit(1)
    
    if not os.path.isfile(crash_log_path):
        sys.stderr.write("Error: Crash log file not found: %s\n" % crash_log_path)
        sys.exit(1)
    
    # Auto-detect toolchain
    addr2line_path, gdb_path, is_riscv = _find_toolchain_binaries(elf_path)
    
    if not addr2line_path:
        sys.stderr.write(
            "Error: addr2line tool not found.\n"
            "Please install pioarduino with espressif32 platform.\n"
        )
        sys.exit(1)
    
    sys.stderr.write("Found addr2line: %s\n" % addr2line_path)
    if gdb_path:
        sys.stderr.write("Found GDB: %s\n" % gdb_path)
    sys.stderr.write("Architecture: %s\n" % ("RISC-V" if is_riscv else "Xtensa"))
    sys.stderr.write("\n")
    
    # Create a minimal mock environment for the decoder
    class StandaloneConfig:
        def __init__(self):
            pass
        
        def get(self, section, key):
            if key == "build_type":
                return "debug"
            return ""
    
    # Create decoder instance
    decoder = Esp32ExceptionDecoder()
    decoder.project_dir = os.path.dirname(os.path.abspath(elf_path))
    decoder.environment = "standalone"
    decoder.config = StandaloneConfig()
    
    # Manually set paths (bypass PlatformIO dependency)
    decoder.firmware_path = os.path.abspath(elf_path)
    decoder.addr2line_path = addr2line_path
    decoder.rom_elf_path = None  # ROM ELF not needed for basic decoding
    decoder._addr_cache = {}
    decoder._is_riscv = is_riscv
    decoder._gdb_path = gdb_path
    
    # Initialize matchers
    if HAS_PYELFTOOLS:
        decoder._firmware_matcher = PcAddressMatcher(decoder.firmware_path)
        decoder._has_working_matcher = bool(decoder._firmware_matcher.intervals)
        decoder._rom_matcher = None  # ROM ELF not used in standalone mode
    else:
        decoder._firmware_matcher = None
        decoder._rom_matcher = None
        decoder._has_working_matcher = False
    
    # Initialize state
    decoder.buffer = ""
    decoder._rx_lock = threading.Lock()
    decoder._buf_lock = threading.Lock()
    decoder._rx_buf = deque()
    decoder._rx_buf_bytes = 0
    decoder._RX_BUF_MAX = 65536
    decoder._riscv_state = decoder._RISCV_IDLE
    decoder._riscv_regs = {}
    decoder._riscv_stack_lines = []
    decoder._fallback_context = False
    decoder._fallback_lines = 0
    decoder.enabled = True
    
    sys.stderr.write("Decoding crash log...\n\n")
    
    # Process the crash log incrementally (not single-shot)
    # Read file in chunks to respect _RX_BUF_MAX and allow proper
    # RISC-V backtrace accumulation and EOF detection
    output_buffer = []
    chunk_size = min(8192, decoder._RX_BUF_MAX // 2)  # Use reasonable chunk size
    
    with open(crash_log_path, 'r', encoding='utf-8', errors='replace') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            
            # Feed chunk to decoder incrementally
            decoded_chunk = decoder.rx(chunk)
            output_buffer.append(decoded_chunk)
    
    # Flush any remaining buffered data and trigger EOF processing
    # This is critical for RISC-V backtrace generation
    if decoder.buffer:
        # Process any remaining incomplete line
        final_line = decoder.buffer + "\n"
        decoder.buffer = ""
        
        # Feed final line and check for RISC-V backtrace
        if decoder._is_riscv and decoder._feed_riscv_line(final_line.rstrip('\n')):
            trace = decoder._invoke_gdb_backtrace()
            if trace:
                output_buffer.append(trace)
            # Line was consumed as part of RISC-V dump
        else:
            output_buffer.append(final_line)
    
    # Check if we have accumulated RISC-V state that needs final processing
    if decoder._is_riscv and decoder._riscv_state != decoder._RISCV_IDLE:
        if decoder._riscv_regs and decoder._riscv_stack_lines:
            trace = decoder._invoke_gdb_backtrace()
            if trace:
                output_buffer.append(trace)
    
    decoded_output = "".join(output_buffer)
    
    # Write output
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(decoded_output)
        sys.stderr.write("\nDecoded output written to: %s\n" % output_path)
    else:
        sys.stdout.write(decoded_output)


if __name__ == "__main__":
    import argparse
    
    # Check for RSP server mode first
    if len(sys.argv) >= 3 and sys.argv[1] == "--rsp-server":
        _run_rsp_server(sys.argv[2])
        sys.exit(0)
    
    # CLI mode
    parser = argparse.ArgumentParser(
        description="ESP32 Exception Decoder - Decode crash logs from ESP32 devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Decode crash log and print to stdout
  %(prog)s firmware.elf crash.txt
  
  # Decode crash log and save to file
  %(prog)s firmware.elf crash.txt -o decoded.txt
  
  # Decode with specific output file
  %(prog)s /path/to/firmware.elf /path/to/crash.log --output result.txt

The tool will automatically detect the architecture (RISC-V or Xtensa) and
find the required toolchain binaries (addr2line, GDB) in:
  - ~/.platformio/packages/
"""
    )
    
    parser.add_argument(
        "elf_file",
        help="Path to firmware ELF file"
    )
    
    parser.add_argument(
        "crash_log",
        help="Path to crash log text file"
    )
    
    parser.add_argument(
        "-o", "--output",
        dest="output_file",
        help="Output file path (default: stdout)",
        default=None
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="ESP32 Exception Decoder 1.0 (Standalone Mode)"
    )
    
    args = parser.parse_args()
    
    _run_standalone_decoder(args.elf_file, args.crash_log, args.output_file)
