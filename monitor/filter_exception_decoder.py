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
import types

# Defer PlatformIO imports when running as GDB RSP server
_RSP_SERVER_MODE = len(sys.argv) >= 2 and sys.argv[1] == "--rsp-server"

if not _RSP_SERVER_MODE:
    from platformio.compat import IS_WINDOWS
    from platformio.exception import PlatformioException
    from platformio.public import (
        DeviceMonitorFilterBase,
        load_build_metadata,
    )
else:
    IS_WINDOWS = sys.platform == "win32"
    DeviceMonitorFilterBase = object

try:
    from elftools.elf.elffile import ELFFile
    from elftools.elf.constants import SH_FLAGS

    HAS_PYELFTOOLS = True
except ImportError:
    HAS_PYELFTOOLS = False

env = DefaultEnvironment()
platform = env.PioPlatform()

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
        except (FileNotFoundError, NotImplementedError, Exception):
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
        self.buffer = ""
        self.firmware_path = None
        self.addr2line_path = None
        self.rom_elf_path = None
        self._addr_cache = {}
        self._firmware_matcher = None
        self._rom_matcher = None
        self._has_working_matcher = False
        self._is_riscv = False
        self._gdb_path = None

        # RISC-V panic accumulator
        self._riscv_state = self._RISCV_IDLE
        self._riscv_regs = {}
        self._riscv_stack_lines = []

        # Fallback context tracking (used when matcher unavailable)
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
        board = data.get("board", "").lower()
        sorted_chips = sorted(self.CHIP_NAME_MAP.keys(), key=len, reverse=True)
        for chip_key in sorted_chips:
            if chip_key in board:
                return self.CHIP_NAME_MAP[chip_key]
        mcu = data.get("mcu", "").lower()
        for chip_key in sorted_chips:
            if chip_key in mcu:
                return self.CHIP_NAME_MAP[chip_key]
        return "esp32"

    def find_rom_elf(self, chip_name):
        try:
            rom_elfs_dir = platform.get_package_dir("tool-esp-rom-elfs")
            # Install tool-esp-rom-elfs if not available
            if not rom_elfs_dir or not os.path.isdir(rom_elfs_dir):
                print("ESP ROM ELFs tool not found, installing...")
                try:
                    platform.install_package("tool-esp-rom-elfs")
                    rom_elfs_dir = platform.get_package_dir("tool-esp-rom-elfs")
                except Exception as e:
                    print(f"Warning: Failed to install tool-esp-rom-elfs: {e}")

            if not rom_elfs_dir or not os.path.isdir(rom_elfs_dir):
                return None

            patterns = [
                os.path.join(rom_elfs_dir, f"{chip_name}_rev*_rom.elf"),
                os.path.join(rom_elfs_dir, f"{chip_name}_rev*.elf"),
                os.path.join(rom_elfs_dir, f"{chip_name}*_rom.elf"),
                os.path.join(rom_elfs_dir, f"{chip_name}*.elf"),
            ]

            rom_files = []
            for pattern in patterns:
                rom_files.extend(glob.glob(pattern))
            rom_files = sorted(set(rom_files))
            if not rom_files:
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
        try:
            pkg = platform.get_package_dir("tool-riscv32-esp-elf-gdb")
            if pkg:
                gdb_bin = os.path.join(
                    pkg.path, "bin", "riscv32-esp-elf-gdb"
                )
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
        if 0 <= code < len(self.XTENSA_EXCEPTIONS):
            desc = self.XTENSA_EXCEPTIONS[code]
            if desc != "reserved":
                return desc
        return None

    def get_riscv_exception(self, code):
        return self.RISCV_EXCEPTIONS.get(code)

    # -------------------------------------------------------------------------
    # Main rx() loop
    # -------------------------------------------------------------------------

    def rx(self, text):
        if not self.enabled:
            return text

        last = 0
        while True:
            idx = text.find("\n", last)
            if idx == -1:
                if len(self.buffer) < 4096:
                    self.buffer += text[last:]
                break

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
            raw = subprocess.check_output(args).decode(enc)
        except subprocess.CalledProcessError:
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

    def _prefetch_addresses(self, addr_specs):
        """Pre-populate _addr_cache in batch for a list of (addr, is_return_addr)."""
        lookups = []
        for addr, is_ret in addr_specs:
            if self.is_address_ignored(addr):
                continue
            lookup = "0x%08x" % (int(addr, 16) - 1) if is_ret else addr
            lookups.append(lookup)

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
        cache_key = (addr, elf_path)
        if cache_key in self._addr_cache:
            return self._addr_cache[cache_key]

        enc = "mbcs" if IS_WINDOWS else "utf-8"
        args = [self.addr2line_path, "-fiaC", "-e", elf_path, addr]

        try:
            raw = subprocess.check_output(args).decode(enc)
        except subprocess.CalledProcessError:
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
        return address in ("", "0x00000000")

    def filter_addresses(self, addresses_str):
        addresses = self.ADDR_SPLIT.split(addresses_str)
        size = len(addresses)
        while size > 1 and self.is_address_ignored(addresses[size - 1]):
            size -= 1
        return addresses[:size]

    def _resolve_address(self, addr, is_return_addr=False):
        if self.is_address_ignored(addr):
            return None, False

        lookup = addr
        if is_return_addr:
            lookup = "0x%08x" % (int(addr, 16) - 1)

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
        addresses = self.filter_addresses(address_match)
        if not addresses:
            return ""

        self._prefetch_addresses(
            [(addr, j > 0) for j, addr in enumerate(addresses)]
        )

        prefix_match = self.PREFIX_RE.match(line)
        prefix = prefix_match.group(0) if prefix_match is not None else ""

        trace = ""
        i = 0
        for j, addr in enumerate(addresses):
            output, is_rom = self._resolve_address(
                addr, is_return_addr=(j > 0)
            )
            if output is not None:
                fmt = "%s  #%-2d %s %s\n" if is_rom else "%s  #%-2d %s in %s\n"
                trace += fmt % (prefix, i, addr, output)
                i += 1

        return trace + "\n" if trace else ""

    def build_stack_trace(self, line, addresses_str):
        addresses = re.findall(r"0x[0-9a-fA-F]{8}", addresses_str)
        if not addresses:
            return ""

        self._prefetch_addresses([(addr, True) for addr in addresses])

        prefix_match = self.PREFIX_RE.match(line)
        prefix = prefix_match.group(0) if prefix_match is not None else ""

        trace = ""
        for addr in addresses:
            output, _ = self._resolve_address(addr, is_return_addr=True)
            if output is not None:
                trace += "%s  %s: %s\n" % (prefix, addr, output)

        return trace

    def build_register_trace(self, line, reg_matches):
        # Pre-fetch code-address registers
        addr_specs = []
        for reg_name, addr in reg_matches:
            if reg_name in ("EXCCAUSE", "MCAUSE"):
                continue
            if reg_name in self.NON_CODE_REGISTERS:
                continue
            addr_specs.append((addr, reg_name == "RA"))
        self._prefetch_addresses(addr_specs)

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

            output, _ = self._resolve_address(
                addr, is_return_addr=(reg_name == "RA")
            )
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
            if reg_matches:
                for name, val in reg_matches:
                    self._riscv_regs[name] = int(val, 16)
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
        """Parse accumulated stack memory lines into (base_addr, bytes)."""
        stack_data = b""
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
            words = re.findall(r"0x([0-9a-fA-F]{8})", m.group(2))
            for w in words:
                stack_data += struct.pack("<I", int(w, 16))

        return base_addr or 0, stack_data

    def _invoke_gdb_backtrace(self):
        """Launch GDB to produce a proper backtrace from the RISC-V panic dump."""
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
                gdb_args += [
                    "-ex", "add-symbol-file %s" % self.rom_elf_path,
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
    """Minimal GDB Remote Serial Protocol server for RISC-V panic data."""
    with open(panic_file, "r") as f:
        panic_data = json.load(f)

    regs = {k: int(v) if isinstance(v, str) else v
            for k, v in panic_data["regs"].items()}
    stack_base = panic_data["stack_base"]
    stack_data = binascii.unhexlify(panic_data["stack_hex"])

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    def respond(data):
        checksum = sum(data.encode("ascii")) & 0xFF
        packet = ("$%s#%02x" % (data, checksum)).encode("ascii")
        stdout.write(packet)
        stdout.flush()
        ack = stdin.read(1)
        if ack == b"-":
            sys.exit(1)

    def get_regs():
        result = ""
        for name in GDB_REGS_RISCV_ILP32:
            val = regs.get(name, 0)
            result += binascii.hexlify(struct.pack("<I", val)).decode("ascii")
        return result

    def get_mem(addr, size):
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
            if c == b"#":
                stdin.read(2)  # checksum bytes
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


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--rsp-server":
        _run_rsp_server(sys.argv[2])
    else:
        sys.stderr.write(
            "Usage: %s --rsp-server <panic_data.json>\n" % sys.argv[0]
        )
        sys.exit(1)
