"""
Unit tests for monitor/filter_exception_decoder.py

Tests ESP32 exception decoder filter for backtrace decoding.
"""
import os
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path
import re

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock platformio modules
sys.modules['platformio'] = MagicMock()
sys.modules['platformio.public'] = MagicMock()
sys.modules['platformio.exception'] = MagicMock()
sys.modules['platformio.package'] = MagicMock()
sys.modules['platformio.package.manager'] = MagicMock()
sys.modules['platformio.package.manager.tool'] = MagicMock()

from monitor import filter_exception_decoder


class TestEsp32ExceptionDecoder(unittest.TestCase):
    """Test Esp32ExceptionDecoder filter."""

    def setUp(self):
        """Set up test environment."""
        self.decoder = filter_exception_decoder.Esp32ExceptionDecoder()
        self.decoder.project_dir = "/tmp/project"
        self.decoder.environment = "test"
        self.decoder.firmware_path = "/tmp/firmware.elf"
        self.decoder.addr2line_path = "/tmp/addr2line"
        self.decoder.rom_elf_path = "/tmp/rom.elf"
        self.decoder.enabled = True
        self.decoder._addr_cache = {}
        self.decoder.in_backtrace_context = False
        self.decoder.lines_since_context = 0
        self.decoder.max_context_lines = 50
        self.decoder.buffer = ""
        self.decoder.config = MagicMock()
        self.decoder.config.get.return_value = "release"

    def test_addr_pattern_matching(self):
        """Test address pattern matching."""
        test_line = "Backtrace: 0x40081234:0x3ffb1234 0x40082345:0x3ffb2345"
        match = self.decoder.ADDR_PATTERN.search(test_line)
        self.assertIsNotNone(match)
        self.assertIn("0x40081234", match.group(1))

    def test_stack_mem_pattern_matching(self):
        """Test stack memory pattern matching."""
        test_line = "3ffb1000: 0x40081234 0x40082345 0x00000000 0x3ffb5678"
        match = self.decoder.STACK_MEM_LINE.search(test_line)
        self.assertIsNotNone(match)
        self.assertIn("0x40081234", match.group(1))

    def test_register_pattern_matching(self):
        """Test register entry pattern matching."""
        test_line = "PC      : 0x40081234  SP      : 0x3ffb1000"
        matches = self.decoder.REGISTER_ENTRY.findall(test_line)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], ("PC", "0x40081234"))
        self.assertEqual(matches[1], ("SP", "0x3ffb1000"))

    def test_backtrace_context_detection(self):
        """Test backtrace context detection."""
        test_lines = [
            "Backtrace: 0x40081234:0x3ffb1234",
            "Guru Meditation Error: Core 0 panic'ed",
            "abort() was called at PC 0x40081234",
            "Exception (3): LoadStoreError"
        ]
        for line in test_lines:
            result = self.decoder.is_backtrace_context(line)
            self.assertTrue(result, f"Failed to detect context in: {line}")

    def test_reboot_detection(self):
        """Test reboot pattern detection."""
        test_line = "  Rebooting..."
        match = self.decoder.REBOOT_RE.match(test_line)
        self.assertIsNotNone(match)

    def test_should_process_line_in_context(self):
        """Test line processing in backtrace context."""
        self.decoder.in_backtrace_context = True
        self.decoder.lines_since_context = 10
        result = self.decoder.should_process_line("Some debug line")
        self.assertTrue(result)

    def test_should_process_line_out_of_context(self):
        """Test line processing outside backtrace context."""
        self.decoder.in_backtrace_context = False
        result = self.decoder.should_process_line("Normal output line")
        self.assertFalse(result)

    def test_should_process_line_context_start(self):
        """Test starting backtrace context."""
        self.decoder.in_backtrace_context = False
        line = "Backtrace: 0x40081234:0x3ffb1234"
        result = self.decoder.should_process_line(line)
        self.assertTrue(result)
        self.assertTrue(self.decoder.in_backtrace_context)
        self.assertEqual(self.decoder.lines_since_context, 0)

    def test_should_process_line_reboot_ends_context(self):
        """Test that reboot message ends backtrace context."""
        self.decoder.in_backtrace_context = True
        line = "Rebooting..."
        result = self.decoder.should_process_line(line)
        self.assertFalse(result)
        self.assertFalse(self.decoder.in_backtrace_context)

    def test_is_address_ignored(self):
        """Test address ignore logic."""
        self.assertTrue(self.decoder.is_address_ignored(""))
        self.assertTrue(self.decoder.is_address_ignored("0x00000000"))
        self.assertFalse(self.decoder.is_address_ignored("0x40081234"))

    def test_filter_addresses(self):
        """Test address filtering."""
        addresses_str = "0x40081234:0x3ffb1234 0x40082345:0x3ffb2345 0x00000000:0x00000000"
        result = self.decoder.filter_addresses(addresses_str)
        # Should remove trailing null addresses
        self.assertTrue(len(result) > 0)
        self.assertNotIn("0x00000000", result[-1])

    def test_get_chip_name_from_board(self):
        """Test chip name detection from board metadata."""
        data = {"board": "esp32s3-devkitc-1", "mcu": ""}
        result = self.decoder.get_chip_name(data)
        self.assertEqual(result, "esp32s3")

    def test_get_chip_name_from_mcu(self):
        """Test chip name detection from MCU metadata."""
        data = {"board": "", "mcu": "esp32c3"}
        result = self.decoder.get_chip_name(data)
        self.assertEqual(result, "esp32c3")

    def test_get_chip_name_default(self):
        """Test default chip name when not found."""
        data = {"board": "unknown", "mcu": ""}
        result = self.decoder.get_chip_name(data)
        self.assertEqual(result, "esp32")

    def test_get_chip_name_priority(self):
        """Test that more specific chip names are matched first."""
        # Test that esp32s3 is matched instead of esp32
        data = {"board": "esp32s3-custom", "mcu": ""}
        result = self.decoder.get_chip_name(data)
        self.assertEqual(result, "esp32s3")

    def test_get_xtensa_exception_valid(self):
        """Test Xtensa exception lookup for valid codes."""
        result = self.decoder.get_xtensa_exception(0)
        self.assertEqual(result, "IllegalInstruction")

        result = self.decoder.get_xtensa_exception(3)
        self.assertEqual(result, "LoadStoreError")

        result = self.decoder.get_xtensa_exception(9)
        self.assertEqual(result, "LoadStoreAlignment")

    def test_get_xtensa_exception_reserved(self):
        """Test Xtensa exception lookup for reserved codes."""
        result = self.decoder.get_xtensa_exception(7)
        self.assertIsNone(result)

        result = self.decoder.get_xtensa_exception(10)
        self.assertIsNone(result)

    def test_get_xtensa_exception_out_of_range(self):
        """Test Xtensa exception lookup for out of range codes."""
        result = self.decoder.get_xtensa_exception(100)
        self.assertIsNone(result)

        result = self.decoder.get_xtensa_exception(-1)
        self.assertIsNone(result)

    def test_get_riscv_exception_valid(self):
        """Test RISC-V exception lookup for valid codes."""
        result = self.decoder.get_riscv_exception(0x0)
        self.assertEqual(result, "Instruction address misaligned")

        result = self.decoder.get_riscv_exception(0x2)
        self.assertEqual(result, "Illegal instruction")

        result = self.decoder.get_riscv_exception(0x5)
        self.assertEqual(result, "Load access fault")

    def test_get_riscv_exception_invalid(self):
        """Test RISC-V exception lookup for invalid codes."""
        result = self.decoder.get_riscv_exception(0xFF)
        self.assertIsNone(result)

        result = self.decoder.get_riscv_exception(0x10)
        self.assertIsNone(result)

    def test_decode_address_caching(self):
        """Test address decoding with caching."""
        with patch('subprocess.check_output') as mock_output:
            mock_output.return_value = b"function_name at file.c:42\n"

            # First call
            result1 = self.decoder.decode_address("0x40081234", "/tmp/firmware.elf")
            self.assertIn("function_name", result1)

            # Second call should use cache
            result2 = self.decoder.decode_address("0x40081234", "/tmp/firmware.elf")
            self.assertEqual(result1, result2)
            # subprocess should only be called once
            mock_output.assert_called_once()

    def test_decode_address_not_found(self):
        """Test decoding address not found in ELF."""
        with patch('subprocess.check_output') as mock_output:
            mock_output.return_value = b"?? ??:0\n"

            result = self.decoder.decode_address("0x40081234", "/tmp/firmware.elf")
            self.assertIsNone(result)

    def test_decode_address_inlined(self):
        """Test decoding inlined function addresses."""
        with patch('subprocess.check_output') as mock_output:
            mock_output.return_value = b"outer_func at file.c:10\ninner_func at file.c:20\n"

            result = self.decoder.decode_address("0x40081234", "/tmp/firmware.elf")
            self.assertIn("outer_func", result)
            self.assertIn("inner_func", result)
            # Should have indented second line
            self.assertIn("     ", result)

    def test_strip_project_dir(self):
        """Test stripping project directory from paths."""
        self.decoder.project_dir = "/home/user/project"
        trace = "/home/user/project/src/main.cpp:42"

        result = self.decoder.strip_project_dir(trace)
        self.assertEqual(result, "src/main.cpp:42")

    def test_strip_project_dir_multiple(self):
        """Test stripping multiple occurrences of project directory."""
        self.decoder.project_dir = "/home/user/project"
        trace = "/home/user/project/src/main.cpp:42 at /home/user/project/include/header.h:10"

        result = self.decoder.strip_project_dir(trace)
        self.assertNotIn("/home/user/project", result)

    def test_non_code_registers(self):
        """Test that non-code registers are not decoded."""
        non_code_regs = ["EXCVADDR", "MTVAL", "MSTATUS", "MHARTID", "PS", "SAR"]
        for reg in non_code_regs:
            self.assertIn(reg, self.decoder.NON_CODE_REGISTERS)

    def test_build_register_trace_exccause(self):
        """Test building trace for EXCCAUSE register."""
        line = "EXCCAUSE: 0x00000003  EXCVADDR: 0x00000000"
        reg_matches = self.decoder.REGISTER_ENTRY.findall(line)

        trace = self.decoder.build_register_trace(line, reg_matches)
        self.assertIn("EXCCAUSE", trace)
        self.assertIn("LoadStoreError", trace)

    def test_build_register_trace_mcause(self):
        """Test building trace for MCAUSE register."""
        line = "MCAUSE  : 0x00000002  MTVAL   : 0x00000000"
        reg_matches = self.decoder.REGISTER_ENTRY.findall(line)

        trace = self.decoder.build_register_trace(line, reg_matches)
        self.assertIn("MCAUSE", trace)
        self.assertIn("Illegal instruction", trace)

    def test_build_register_trace_with_code_address(self):
        """Test building trace for register with code address."""
        line = "PC      : 0x40081234  SP      : 0x3ffb1000"
        reg_matches = self.decoder.REGISTER_ENTRY.findall(line)

        with patch.object(self.decoder, '_resolve_address') as mock_resolve:
            mock_resolve.return_value = ("main at main.cpp:10", False)

            trace = self.decoder.build_register_trace(line, reg_matches)
            self.assertIn("PC", trace)
            self.assertIn("0x40081234", trace)
            self.assertIn("main at main.cpp:10", trace)


class TestRxProcessing(unittest.TestCase):
    """Test rx text processing."""

    def setUp(self):
        """Set up test environment."""
        self.decoder = filter_exception_decoder.Esp32ExceptionDecoder()
        self.decoder.enabled = True
        self.decoder.buffer = ""
        self.decoder.in_backtrace_context = False
        self.decoder.lines_since_context = 0
        self.decoder.max_context_lines = 50

    def test_rx_disabled(self):
        """Test rx when decoder is disabled."""
        self.decoder.enabled = False
        text = "Some text\n"
        result = self.decoder.rx(text)
        self.assertEqual(result, text)

    def test_rx_normal_text(self):
        """Test rx with normal text (no backtrace)."""
        text = "Normal output\nAnother line\n"
        result = self.decoder.rx(text)
        self.assertEqual(result, text)

    def test_rx_incomplete_line(self):
        """Test rx with incomplete line (no newline)."""
        text = "Partial line without"
        result = self.decoder.rx(text)
        # Should buffer the incomplete line
        self.assertEqual(self.decoder.buffer, text)
        self.assertEqual(result, text)

    def test_rx_buffer_continuation(self):
        """Test rx continuing buffered line."""
        self.decoder.buffer = "Partial "
        text = "complete line\nNext line\n"
        result = self.decoder.rx(text)
        # Buffer should be cleared
        self.assertEqual(self.decoder.buffer, "")

    def test_rx_large_buffer_protection(self):
        """Test that buffer doesn't grow beyond 4096 bytes."""
        text = "x" * 5000
        result = self.decoder.rx(text)
        self.assertTrue(len(self.decoder.buffer) <= 4096)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Set up test environment."""
        self.decoder = filter_exception_decoder.Esp32ExceptionDecoder()

    def test_empty_address_string(self):
        """Test handling of empty address string."""
        result = self.decoder.filter_addresses("")
        self.assertEqual(result, [])

    def test_malformed_register_line(self):
        """Test handling of malformed register dump."""
        line = "INVALID_FORMAT"
        matches = self.decoder.REGISTER_ENTRY.findall(line)
        self.assertEqual(len(matches), 0)

    def test_decode_address_subprocess_error(self):
        """Test handling of addr2line subprocess error."""
        with patch('subprocess.check_output') as mock_output:
            mock_output.side_effect = Exception("addr2line failed")

            result = self.decoder.decode_address("0x40081234", "/tmp/firmware.elf")
            # Should handle error gracefully
            self.assertIsNone(result)

    def test_context_line_limit(self):
        """Test that context processing stops after max_context_lines."""
        self.decoder.in_backtrace_context = True
        self.decoder.max_context_lines = 5

        # Process lines beyond limit
        for i in range(10):
            self.decoder.lines_since_context = i
            result = self.decoder.should_process_line(f"Line {i}")
            if i <= 5:
                self.assertTrue(result)
            else:
                self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()