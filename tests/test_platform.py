"""
Unit tests for platform.py

Tests ESP32 platform configuration and package management.
"""
import os
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open, call
from pathlib import Path
import json
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock platformio modules before import
sys.modules['platformio'] = MagicMock()
sys.modules['platformio.public'] = MagicMock()
sys.modules['platformio.proc'] = MagicMock()
sys.modules['platformio.project'] = MagicMock()
sys.modules['platformio.project.config'] = MagicMock()
sys.modules['platformio.package'] = MagicMock()
sys.modules['platformio.package.manager'] = MagicMock()
sys.modules['platformio.package.manager.tool'] = MagicMock()
sys.modules['platformio.exception'] = MagicMock()
sys.modules['platformio.compat'] = MagicMock()
sys.modules['requests'] = MagicMock()

# Set IS_WINDOWS to False for testing
sys.modules['platformio.compat'].IS_WINDOWS = False

import platform as platform_module


class TestInternetAvailability(unittest.TestCase):
    """Test is_internet_available function."""

    def test_internet_available(self):
        """Test when internet is available."""
        with patch('platform.has_internet_connection') as mock_check:
            mock_check.return_value = True
            result = platform_module.is_internet_available()
            self.assertTrue(result)

    def test_internet_unavailable(self):
        """Test when internet is unavailable."""
        with patch('platform.has_internet_connection') as mock_check:
            mock_check.return_value = False
            result = platform_module.is_internet_available()
            self.assertFalse(result)


class TestSafeFileOperations(unittest.TestCase):
    """Test safe file operation wrappers."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_safe_remove_file_exists(self):
        """Test removing an existing file."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")

        result = platform_module.safe_remove_file(test_file)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(test_file))

    def test_safe_remove_file_not_exists(self):
        """Test removing a non-existent file."""
        test_file = os.path.join(self.temp_dir, "nonexistent.txt")
        result = platform_module.safe_remove_file(test_file)
        self.assertTrue(result)

    def test_safe_remove_directory_exists(self):
        """Test removing an existing directory."""
        test_dir = os.path.join(self.temp_dir, "test_subdir")
        os.makedirs(test_dir)

        result = platform_module.safe_remove_directory(test_dir)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(test_dir))

    def test_safe_remove_directory_not_exists(self):
        """Test removing a non-existent directory."""
        test_dir = os.path.join(self.temp_dir, "nonexistent_dir")
        result = platform_module.safe_remove_directory(test_dir)
        self.assertTrue(result)

    def test_safe_copy_file(self):
        """Test copying a file."""
        src_file = os.path.join(self.temp_dir, "source.txt")
        dst_file = os.path.join(self.temp_dir, "dest.txt")

        with open(src_file, 'w') as f:
            f.write("test content")

        result = platform_module.safe_copy_file(src_file, dst_file)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(dst_file))

        with open(dst_file, 'r') as f:
            self.assertEqual(f.read(), "test content")

    def test_safe_copy_directory(self):
        """Test copying a directory."""
        src_dir = os.path.join(self.temp_dir, "src_dir")
        dst_dir = os.path.join(self.temp_dir, "dst_dir")

        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "file.txt"), 'w') as f:
            f.write("content")

        result = platform_module.safe_copy_directory(src_dir, dst_dir)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(dst_dir, "file.txt")))

    def test_safe_remove_directory_pattern(self):
        """Test removing directories matching a pattern."""
        # Create test directories
        os.makedirs(os.path.join(self.temp_dir, "tool-test@1.0"))
        os.makedirs(os.path.join(self.temp_dir, "tool-test@2.0"))
        os.makedirs(os.path.join(self.temp_dir, "other-tool"))

        result = platform_module.safe_remove_directory_pattern(self.temp_dir, "tool-test@*")
        self.assertTrue(result)

        # Pattern-matched directories should be removed
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, "tool-test@1.0")))
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, "tool-test@2.0")))

        # Other directory should remain
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "other-tool")))


class TestEspressif32Platform(unittest.TestCase):
    """Test Espressif32Platform class."""

    def setUp(self):
        """Set up test environment."""
        with patch('platform.ProjectConfig') as mock_config:
            mock_instance = MagicMock()
            mock_instance.get.return_value = "/tmp/packages"
            mock_config.get_instance.return_value = mock_instance

            self.platform = platform_module.Espressif32Platform()
            self.platform.packages = {
                "tool-esp_install": {
                    "version": "https://example.com/v5.3.4/tool.zip",
                    "package-version": "5.3.4",
                    "optional": False
                },
                "toolchain-xtensa-esp-elf": {
                    "package-version": "14.2.0+20251107",
                    "optional": True
                },
                "framework-espidf": {
                    "optional": True
                }
            }
            self.platform.get_package = MagicMock()
            self.platform.get_package_dir = MagicMock(return_value="/tmp/packages/pkg")

    def test_packages_dir_caching(self):
        """Test packages directory caching."""
        # First access
        dir1 = self.platform.packages_dir
        # Second access should use cache
        dir2 = self.platform.packages_dir
        self.assertEqual(dir1, dir2)
        self.assertIsInstance(dir1, Path)

    def test_extract_version_from_url(self):
        """Test extracting version from URL."""
        url = "https://example.com/releases/download/v5.3.4/tool-v5.3.4.zip"
        result = self.platform._extract_version_from_url(url)
        self.assertEqual(result, "5.3.4")

    def test_extract_version_from_direct(self):
        """Test extracting version from direct version string."""
        version = "5.3.4"
        result = self.platform._extract_version_from_url(version)
        self.assertEqual(result, "5.3.4")

    def test_extract_version_no_match(self):
        """Test extracting version when no pattern matches."""
        url = "https://example.com/tool.zip"
        result = self.platform._extract_version_from_url(url)
        self.assertEqual(result, url)

    def test_compare_tl_install_versions_match(self):
        """Test version comparison when versions match."""
        result = self.platform._compare_tl_install_versions("5.3.4", "5.3.4")
        self.assertTrue(result)

    def test_compare_tl_install_versions_mismatch(self):
        """Test version comparison when versions don't match."""
        result = self.platform._compare_tl_install_versions("5.3.3", "5.3.4")
        self.assertFalse(result)

    def test_compare_tl_install_versions_url(self):
        """Test version comparison with URL versions."""
        installed = "https://example.com/v5.3.4/tool.zip"
        required = "https://example.com/v5.3.4/tool.zip"
        result = self.platform._compare_tl_install_versions(installed, required)
        self.assertTrue(result)

    def test_get_tool_paths_caching(self):
        """Test tool paths caching."""
        # First call
        paths1 = self.platform._get_tool_paths("test-tool")
        # Second call should use cache
        paths2 = self.platform._get_tool_paths("test-tool")

        self.assertEqual(paths1, paths2)
        self.assertIn('tool_path', paths1)
        self.assertIn('package_path', paths1)
        self.assertIn('tools_json_path', paths1)

    def test_check_tool_status(self):
        """Test checking tool installation status."""
        with patch('pathlib.Path.exists') as mock_exists:
            mock_exists.return_value = True

            status = self.platform._check_tool_status("test-tool")

            self.assertIn('has_idf_tools', status)
            self.assertIn('has_tools_json', status)
            self.assertIn('has_piopm', status)
            self.assertIn('tool_exists', status)

    def test_get_mcu_config_xtensa(self):
        """Test getting MCU configuration for Xtensa chips."""
        config = self.platform._get_mcu_config("esp32")
        self.assertIsNotNone(config)
        self.assertIn("toolchains", config)
        self.assertIn("ulp_toolchain", config)

    def test_get_mcu_config_riscv(self):
        """Test getting MCU configuration for RISC-V chips."""
        config = self.platform._get_mcu_config("esp32c3")
        self.assertIsNotNone(config)
        self.assertIn("toolchains", config)

    def test_get_mcu_config_caching(self):
        """Test MCU configuration caching."""
        config1 = self.platform._get_mcu_config("esp32")
        config2 = self.platform._get_mcu_config("esp32")
        self.assertEqual(config1, config2)

    def test_get_mcu_config_unknown(self):
        """Test getting configuration for unknown MCU."""
        config = self.platform._get_mcu_config("unknown_mcu")
        self.assertIsNone(config)

    def test_needs_debug_tools_build_type(self):
        """Test debug tools needed when build_type is set."""
        variables = {"build_type": "debug"}
        result = self.platform._needs_debug_tools(variables, [])
        self.assertTrue(result)

    def test_needs_debug_tools_debug_target(self):
        """Test debug tools needed when debug is in targets."""
        variables = {}
        result = self.platform._needs_debug_tools(variables, ["debug"])
        self.assertTrue(result)

    def test_needs_debug_tools_upload_protocol(self):
        """Test debug tools needed when upload_protocol is set."""
        variables = {"upload_protocol": "jlink"}
        result = self.platform._needs_debug_tools(variables, [])
        self.assertTrue(result)

    def test_needs_debug_tools_not_needed(self):
        """Test debug tools not needed."""
        variables = {}
        result = self.platform._needs_debug_tools(variables, [])
        self.assertFalse(result)

    def test_check_exception_decoder_filter_enabled(self):
        """Test exception decoder filter check when enabled."""
        variables = {"monitor_filters": ["esp32_exception_decoder", "other"]}
        result = self.platform._check_exception_decoder_filter(variables)
        self.assertTrue(result)

    def test_check_exception_decoder_filter_string(self):
        """Test exception decoder filter check with string format."""
        variables = {"monitor_filters": "esp32_exception_decoder, other"}
        result = self.platform._check_exception_decoder_filter(variables)
        self.assertTrue(result)

    def test_check_exception_decoder_filter_disabled(self):
        """Test exception decoder filter check when disabled."""
        variables = {"monitor_filters": ["other_filter"]}
        result = self.platform._check_exception_decoder_filter(variables)
        self.assertFalse(result)

    def test_check_exception_decoder_filter_empty(self):
        """Test exception decoder filter check with empty filters."""
        variables = {"monitor_filters": []}
        result = self.platform._check_exception_decoder_filter(variables)
        self.assertFalse(result)


class TestGetBoards(unittest.TestCase):
    """Test get_boards method."""

    def setUp(self):
        """Set up test environment."""
        with patch('platform.ProjectConfig'):
            self.platform = platform_module.Espressif32Platform()

    def test_add_dynamic_options_upload_protocols(self):
        """Test adding dynamic upload protocol options."""
        board = MagicMock()
        board.get.return_value = []
        board.manifest = {"upload": {}}

        result = self.platform._add_dynamic_options(board)

        self.assertIn("protocols", result.manifest["upload"])
        self.assertIn("esptool", result.manifest["upload"]["protocols"])
        self.assertIn("espota", result.manifest["upload"]["protocols"])

    def test_add_dynamic_options_esp_builtin(self):
        """Test adding esp-builtin debug tool for supported MCUs."""
        board = MagicMock()
        board.get.side_effect = lambda key, default=None: {
            "build.mcu": "esp32c3",
            "upload.protocols": [],
            "upload.protocol": "esptool"
        }.get(key, default)

        board.manifest = {"upload": {}, "debug": {}}
        board.id = "esp32c3-devkit"

        result = self.platform._add_dynamic_options(board)

        self.assertIn("protocols", result.manifest["upload"])
        protocols = result.manifest["upload"]["protocols"]
        self.assertIn("esp-builtin", protocols)

    def test_get_openocd_interface_jlink(self):
        """Test OpenOCD interface for J-Link."""
        result = self.platform._get_openocd_interface("jlink", MagicMock())
        self.assertEqual(result, "jlink")

    def test_get_openocd_interface_esp_builtin(self):
        """Test OpenOCD interface for ESP builtin."""
        result = self.platform._get_openocd_interface("esp-builtin", MagicMock())
        self.assertEqual(result, "esp_usb_jtag")

    def test_get_openocd_interface_ftdi(self):
        """Test OpenOCD interface for FTDI."""
        board = MagicMock()
        board.id = "generic"
        result = self.platform._get_openocd_interface("ftdi", board)
        self.assertIn("ftdi", result)

    def test_get_debug_server_args_target(self):
        """Test generating debug server arguments with target."""
        debug = {"openocd_target": "esp32.cfg"}
        args = self.platform._get_debug_server_args("jlink", debug)

        self.assertIn("-s", args)
        self.assertIn("-f", args)
        self.assertIn("interface/jlink.cfg", args)
        self.assertIn("target/esp32.cfg", args)

    def test_get_debug_server_args_board(self):
        """Test generating debug server arguments with board."""
        debug = {"openocd_board": "esp32-wrover.cfg"}
        args = self.platform._get_debug_server_args("cmsis-dap", debug)

        self.assertIn("-s", args)
        self.assertIn("-f", args)
        self.assertIn("interface/cmsis-dap.cfg", args)
        self.assertIn("board/esp32-wrover.cfg", args)


class TestConfigureArduinoFramework(unittest.TestCase):
    """Test Arduino framework configuration."""

    def setUp(self):
        """Set up test environment."""
        with patch('platform.ProjectConfig'):
            self.platform = platform_module.Espressif32Platform()
            self.platform.packages_dir = Path("/tmp/packages")
            self.platform.packages = {
                "framework-arduinoespressif32": {"optional": True},
                "framework-arduinoespressif32-libs": {"optional": True},
                "framework-arduino-c2-skeleton-lib": {"optional": True},
                "framework-arduino-c61-skeleton-lib": {"optional": True}
            }

    def test_configure_arduino_not_in_frameworks(self):
        """Test when Arduino is not in frameworks."""
        self.platform._configure_arduino_framework(["espidf"], "esp32")
        # Should not modify packages
        self.assertTrue(self.platform.packages["framework-arduinoespressif32"]["optional"])

    def test_configure_arduino_esp32(self):
        """Test configuring Arduino for ESP32."""
        with patch('platform.is_internet_available') as mock_internet:
            mock_internet.return_value = False

            self.platform._configure_arduino_framework(["arduino"], "esp32")

            self.assertFalse(self.platform.packages["framework-arduinoespressif32"]["optional"])
            self.assertFalse(self.platform.packages["framework-arduinoespressif32-libs"]["optional"])

    def test_configure_arduino_c2(self):
        """Test configuring Arduino for ESP32-C2."""
        with patch('platform.is_internet_available') as mock_internet:
            mock_internet.return_value = False

            self.platform._configure_arduino_framework(["arduino"], "esp32c2")

            self.assertFalse(self.platform.packages["framework-arduino-c2-skeleton-lib"]["optional"])

    def test_configure_arduino_c61(self):
        """Test configuring Arduino for ESP32-C61."""
        with patch('platform.is_internet_available') as mock_internet:
            mock_internet.return_value = False

            self.platform._configure_arduino_framework(["arduino"], "esp32c61")

            self.assertFalse(self.platform.packages["framework-arduino-c61-skeleton-lib"]["optional"])


class TestConfigureEspIdfFramework(unittest.TestCase):
    """Test ESP-IDF framework configuration."""

    def setUp(self):
        """Set up test environment."""
        with patch('platform.ProjectConfig'):
            self.platform = platform_module.Espressif32Platform()
            self.platform.packages_dir = Path("/tmp/packages")
            self.platform.packages = {
                "framework-espidf": {"optional": True}
            }

    def test_configure_espidf_custom_sdkconfig(self):
        """Test configuring ESP-IDF with custom sdkconfig."""
        variables = {"custom_sdkconfig": "file://sdkconfig.custom"}
        board_config = {}
        frameworks = []

        self.platform._configure_espidf_framework(frameworks, variables, board_config, "esp32")

        self.assertIn("espidf", frameworks)
        self.assertFalse(self.platform.packages["framework-espidf"]["optional"])

    def test_configure_espidf_board_sdkconfig(self):
        """Test configuring ESP-IDF with board sdkconfig."""
        variables = {}
        board_config = {"espidf.custom_sdkconfig": "file://board_sdkconfig"}
        frameworks = []

        self.platform._configure_espidf_framework(frameworks, variables, board_config, "esp32")

        self.assertIn("espidf", frameworks)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_safe_file_operation_decorator_error(self):
        """Test safe file operation decorator with error."""
        @platform_module.safe_file_operation
        def failing_operation():
            raise OSError("Test error")

        result = failing_operation()
        self.assertFalse(result)

    def test_mcu_config_ulp_toolchain_esp32(self):
        """Test ULP toolchain configuration for ESP32."""
        with patch('platform.ProjectConfig'):
            plat = platform_module.Espressif32Platform()
            config = plat._get_mcu_config("esp32")

            self.assertIn("toolchain-esp32ulp", config["ulp_toolchain"])
            self.assertIn("toolchain-riscv32-esp", config["ulp_toolchain"])

    def test_mcu_config_ulp_toolchain_esp32s2(self):
        """Test ULP toolchain configuration for ESP32-S2."""
        with patch('platform.ProjectConfig'):
            plat = platform_module.Espressif32Platform()
            config = plat._get_mcu_config("esp32s2")

            # ESP32-S2 also gets RISC-V toolchain for ULP
            self.assertIn("toolchain-riscv32-esp", config["ulp_toolchain"])


if __name__ == '__main__':
    unittest.main()