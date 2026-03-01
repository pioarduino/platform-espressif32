"""
Unit tests for JSON schema validation

Tests board configuration files and platform.json for correct structure.
"""
import os
import sys
import unittest
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBoardJsonSchema(unittest.TestCase):
    """Test board JSON files for correct schema."""

    def setUp(self):
        """Set up test environment."""
        self.boards_dir = Path(__file__).parent.parent / "boards"
        self.board_files = [
            "featheresp32-s2.json",
            "seeed_xiao_esp32_s3_plus.json",
            "seeed_xiao_esp32c5.json",
            "seeed_xiao_esp32c6.json",
            "yb_esp32s3_amp_v2.json",
            "yb_esp32s3_amp_v3.json"
        ]

    def load_board_json(self, filename):
        """Load board JSON file."""
        filepath = self.boards_dir / filename
        with open(filepath, 'r') as f:
            return json.load(f)

    def test_board_files_exist(self):
        """Test that all board files exist."""
        for board_file in self.board_files:
            filepath = self.boards_dir / board_file
            self.assertTrue(filepath.exists(), f"Board file {board_file} does not exist")

    def test_board_json_valid(self):
        """Test that all board JSON files are valid JSON."""
        for board_file in self.board_files:
            with self.subTest(board=board_file):
                try:
                    data = self.load_board_json(board_file)
                    self.assertIsInstance(data, dict)
                except json.JSONDecodeError as e:
                    self.fail(f"Invalid JSON in {board_file}: {e}")

    def test_board_required_fields(self):
        """Test that board JSONs have required fields."""
        required_fields = ["build", "connectivity", "frameworks", "name", "upload", "url", "vendor"]

        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)
                for field in required_fields:
                    self.assertIn(field, data, f"Missing field '{field}' in {board_file}")

    def test_board_build_section(self):
        """Test board build section structure."""
        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)
                build = data.get("build", {})

                # Check required build fields
                self.assertIn("core", build)
                self.assertIn("extra_flags", build)
                self.assertIn("f_cpu", build)
                self.assertIn("f_flash", build)
                self.assertIn("flash_mode", build)
                self.assertIn("mcu", build)
                self.assertIn("variant", build)

                # Validate types
                self.assertEqual(build["core"], "esp32")
                self.assertIsInstance(build["extra_flags"], list)
                self.assertTrue(build["f_cpu"].endswith("L"))
                self.assertTrue(build["f_flash"].endswith("L"))
                self.assertIn(build["flash_mode"], ["qio", "dio", "qout", "dout"])

    def test_board_upload_section(self):
        """Test board upload section structure."""
        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)
                upload = data.get("upload", {})

                # Check required upload fields
                self.assertIn("flash_size", upload)
                self.assertIn("maximum_ram_size", upload)
                self.assertIn("maximum_size", upload)
                self.assertIn("require_upload_port", upload)
                self.assertIn("speed", upload)

                # Validate types
                self.assertIsInstance(upload["flash_size"], str)
                self.assertIsInstance(upload["maximum_ram_size"], int)
                self.assertIsInstance(upload["maximum_size"], int)
                self.assertIsInstance(upload["require_upload_port"], bool)
                self.assertIsInstance(upload["speed"], int)

                # Validate values
                self.assertTrue(upload["maximum_ram_size"] > 0)
                self.assertTrue(upload["maximum_size"] > 0)
                self.assertTrue(upload["speed"] > 0)

    def test_board_connectivity(self):
        """Test board connectivity section."""
        valid_connectivity = ["wifi", "bluetooth", "zigbee", "thread"]

        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)
                connectivity = data.get("connectivity", [])

                self.assertIsInstance(connectivity, list)
                self.assertTrue(len(connectivity) > 0, "Connectivity list should not be empty")

                for item in connectivity:
                    self.assertIn(item, valid_connectivity,
                        f"Invalid connectivity type '{item}' in {board_file}")

    def test_board_frameworks(self):
        """Test board frameworks section."""
        valid_frameworks = ["arduino", "espidf"]

        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)
                frameworks = data.get("frameworks", [])

                self.assertIsInstance(frameworks, list)
                self.assertTrue(len(frameworks) > 0, "Frameworks list should not be empty")

                for framework in frameworks:
                    self.assertIn(framework, valid_frameworks,
                        f"Invalid framework '{framework}' in {board_file}")

    def test_board_debug_section(self):
        """Test board debug section if present."""
        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)

                if "debug" in data:
                    debug = data["debug"]
                    self.assertIsInstance(debug, dict)
                    self.assertIn("openocd_target", debug)

    def test_board_hwids(self):
        """Test board hardware IDs."""
        for board_file in self.board_files:
            with self.subTest(board=board_file):
                data = self.load_board_json(board_file)
                build = data.get("build", {})

                if "hwids" in build:
                    hwids = build["hwids"]
                    self.assertIsInstance(hwids, list)
                    self.assertTrue(len(hwids) > 0)

                    for hwid in hwids:
                        self.assertIsInstance(hwid, list)
                        self.assertEqual(len(hwid), 2, "HWID should be [VID, PID]")
                        # Both should be hex strings
                        self.assertTrue(hwid[0].startswith("0x"))
                        self.assertTrue(hwid[1].startswith("0x"))


class TestFeatherESP32S2Board(unittest.TestCase):
    """Test specific features of featheresp32-s2.json."""

    def setUp(self):
        """Load board data."""
        boards_dir = Path(__file__).parent.parent / "boards"
        with open(boards_dir / "featheresp32-s2.json", 'r') as f:
            self.board = json.load(f)

    def test_custom_bootloader(self):
        """Test custom bootloader configuration."""
        build = self.board.get("build", {})
        arduino = build.get("arduino", {})
        self.assertIn("custom_bootloader", arduino)
        self.assertEqual(arduino["custom_bootloader"], "bootloader-tinyuf2.bin")

    def test_partitions(self):
        """Test partitions configuration."""
        build = self.board.get("build", {})
        arduino = build.get("arduino", {})
        self.assertIn("partitions", arduino)
        self.assertEqual(arduino["partitions"], "tinyuf2-partitions-4MB.csv")

    def test_flash_extra_images(self):
        """Test flash extra images."""
        upload = self.board.get("upload", {})
        arduino = upload.get("arduino", {})
        self.assertIn("flash_extra_images", arduino)

        flash_images = arduino["flash_extra_images"]
        self.assertIsInstance(flash_images, list)
        self.assertTrue(len(flash_images) > 0)

        for image in flash_images:
            self.assertIsInstance(image, list)
            self.assertEqual(len(image), 2, "Flash image should be [offset, path]")

    def test_usb_boot_features(self):
        """Test USB boot features."""
        upload = self.board.get("upload", {})
        self.assertIn("use_1200bps_touch", upload)
        self.assertIn("wait_for_upload_port", upload)
        self.assertTrue(upload["use_1200bps_touch"])
        self.assertTrue(upload["wait_for_upload_port"])


class TestXiaoBoards(unittest.TestCase):
    """Test Seeed XIAO board configurations."""

    def setUp(self):
        """Load XIAO board data."""
        boards_dir = Path(__file__).parent.parent / "boards"
        self.boards = {}
        for board_file in ["seeed_xiao_esp32_s3_plus.json", "seeed_xiao_esp32c5.json",
                           "seeed_xiao_esp32c6.json"]:
            with open(boards_dir / board_file, 'r') as f:
                self.boards[board_file] = json.load(f)

    def test_xiao_vendor(self):
        """Test that all XIAO boards have correct vendor."""
        for board_name, board_data in self.boards.items():
            with self.subTest(board=board_name):
                self.assertEqual(board_data["vendor"], "Seeed Studio")

    def test_xiao_usb_features(self):
        """Test XIAO USB features."""
        for board_name, board_data in self.boards.items():
            with self.subTest(board=board_name):
                build = board_data.get("build", {})
                extra_flags = build.get("extra_flags", [])

                # Check for USB CDC flag
                has_usb_cdc = any("ARDUINO_USB_CDC_ON_BOOT=1" in flag for flag in extra_flags)
                self.assertTrue(has_usb_cdc, f"Missing USB CDC flag in {board_name}")

    def test_xiao_s3_plus_psram(self):
        """Test XIAO ESP32S3 Plus PSRAM configuration."""
        board = self.boards["seeed_xiao_esp32_s3_plus.json"]
        build = board.get("build", {})
        extra_flags = build.get("extra_flags", [])

        # Should have PSRAM flag
        has_psram = any("BOARD_HAS_PSRAM" in flag for flag in extra_flags)
        self.assertTrue(has_psram)

        # Check memory type
        arduino = build.get("arduino", {})
        self.assertIn("memory_type", arduino)
        self.assertEqual(arduino["memory_type"], "qio_opi")


class TestYellowByteBoards(unittest.TestCase):
    """Test YelloByte board configurations."""

    def setUp(self):
        """Load YelloByte board data."""
        boards_dir = Path(__file__).parent.parent / "boards"
        self.boards = {}
        for board_file in ["yb_esp32s3_amp_v2.json", "yb_esp32s3_amp_v3.json"]:
            with open(boards_dir / board_file, 'r') as f:
                self.boards[board_file] = json.load(f)

    def test_yellobyte_vendor(self):
        """Test that YelloByte boards have correct vendor."""
        for board_name, board_data in self.boards.items():
            with self.subTest(board=board_name):
                self.assertEqual(board_data["vendor"], "YelloByte")

    def test_yellobyte_v2_vs_v3(self):
        """Test differences between v2 and v3."""
        v2 = self.boards["yb_esp32s3_amp_v2.json"]
        v3 = self.boards["yb_esp32s3_amp_v3.json"]

        # V3 should have USB CDC, V2 should not
        v2_flags = v2["build"]["extra_flags"]
        v3_flags = v3["build"]["extra_flags"]

        v2_has_cdc = any("ARDUINO_USB_CDC_ON_BOOT=1" in flag for flag in v2_flags)
        v3_has_cdc = any("ARDUINO_USB_CDC_ON_BOOT=1" in flag for flag in v3_flags)

        self.assertFalse(v2_has_cdc, "V2 should not have USB CDC")
        self.assertTrue(v3_has_cdc, "V3 should have USB CDC")

    def test_yellobyte_hwids(self):
        """Test hardware IDs."""
        v2 = self.boards["yb_esp32s3_amp_v2.json"]
        v3 = self.boards["yb_esp32s3_amp_v3.json"]

        # Different HWIDs
        self.assertNotEqual(v2["build"]["hwids"], v3["build"]["hwids"])


class TestPlatformJson(unittest.TestCase):
    """Test platform.json schema."""

    def setUp(self):
        """Load platform.json."""
        platform_file = Path(__file__).parent.parent / "platform.json"
        with open(platform_file, 'r') as f:
            self.platform = json.load(f)

    def test_platform_json_valid(self):
        """Test that platform.json is valid JSON."""
        self.assertIsInstance(self.platform, dict)

    def test_platform_required_fields(self):
        """Test required fields in platform.json."""
        required_fields = ["name", "title", "description", "homepage", "license",
                          "keywords", "engines", "repository", "version", "frameworks", "packages"]

        for field in required_fields:
            self.assertIn(field, self.platform, f"Missing field '{field}' in platform.json")

    def test_platform_name(self):
        """Test platform name."""
        self.assertEqual(self.platform["name"], "espressif32")

    def test_platform_frameworks(self):
        """Test frameworks configuration."""
        frameworks = self.platform.get("frameworks", {})
        self.assertIn("arduino", frameworks)
        self.assertIn("espidf", frameworks)

        # Check framework scripts
        self.assertIn("script", frameworks["arduino"])
        self.assertIn("script", frameworks["espidf"])

    def test_platform_packages(self):
        """Test packages configuration."""
        packages = self.platform.get("packages", {})

        # Essential packages
        essential_packages = [
            "framework-arduinoespressif32",
            "framework-espidf",
            "toolchain-xtensa-esp-elf",
            "toolchain-riscv32-esp",
            "tool-esptoolpy",
            "tool-esp_install"
        ]

        for pkg in essential_packages:
            with self.subTest(package=pkg):
                self.assertIn(pkg, packages, f"Missing package '{pkg}'")

    def test_package_structure(self):
        """Test package structure."""
        packages = self.platform.get("packages", {})

        for pkg_name, pkg_data in packages.items():
            with self.subTest(package=pkg_name):
                # Note: Some packages like contrib-piohome don't have a 'type' field
                self.assertIn("optional", pkg_data, f"Package {pkg_name} missing 'optional'")
                self.assertIsInstance(pkg_data["optional"], bool)

                # Check type field exists for most packages (except contrib packages)
                if not pkg_name.startswith("contrib-"):
                    self.assertIn("type", pkg_data, f"Package {pkg_name} missing 'type'")

    def test_toolchain_packages(self):
        """Test toolchain package configurations."""
        packages = self.platform.get("packages", {})

        toolchains = [
            "toolchain-xtensa-esp-elf",
            "toolchain-riscv32-esp",
            "toolchain-esp32ulp"
        ]

        for toolchain in toolchains:
            with self.subTest(toolchain=toolchain):
                self.assertIn(toolchain, packages)
                pkg = packages[toolchain]
                self.assertEqual(pkg["type"], "toolchain")
                self.assertIn("package-version", pkg)
                self.assertIn("version", pkg)

    def test_framework_packages(self):
        """Test framework package configurations."""
        packages = self.platform.get("packages", {})

        frameworks = ["framework-arduinoespressif32", "framework-espidf"]

        for framework in frameworks:
            with self.subTest(framework=framework):
                self.assertIn(framework, packages)
                pkg = packages[framework]
                self.assertEqual(pkg["type"], "framework")

    def test_tool_packages(self):
        """Test tool package configurations."""
        packages = self.platform.get("packages", {})

        tools = [
            "tool-esptoolpy",
            "tool-esp_install",
            "tool-cmake",
            "tool-ninja",
            "tool-esp-rom-elfs"
        ]

        for tool in tools:
            with self.subTest(tool=tool):
                self.assertIn(tool, packages)
                pkg = packages[tool]
                self.assertIn(pkg["type"], ["tool", "uploader", "debugger"])

    def test_platformio_version_requirement(self):
        """Test PlatformIO version requirement."""
        engines = self.platform.get("engines", {})
        self.assertIn("platformio", engines)

        version_req = engines["platformio"]
        self.assertTrue(version_req.startswith(">="))


class TestJsonConsistency(unittest.TestCase):
    """Test consistency across JSON files."""

    def setUp(self):
        """Load all JSON files."""
        self.boards_dir = Path(__file__).parent.parent / "boards"
        self.board_files = list(self.boards_dir.glob("*.json"))

    def test_all_boards_have_consistent_mcu_naming(self):
        """Test that MCU names follow consistent conventions."""
        valid_mcus = ["esp32", "esp32s2", "esp32s3", "esp32c2", "esp32c3",
                      "esp32c5", "esp32c6", "esp32c61", "esp32h2", "esp32p4"]

        for board_file in self.board_files:
            with self.subTest(board=board_file.name):
                with open(board_file, 'r') as f:
                    data = json.load(f)
                    build = data.get("build", {})
                    mcu = build.get("mcu", "")

                    self.assertIn(mcu, valid_mcus,
                        f"Invalid MCU '{mcu}' in {board_file.name}")

    def test_flash_sizes_consistency(self):
        """Test that flash sizes use consistent units."""
        valid_flash_sizes = ["2MB", "4MB", "8MB", "16MB", "32MB", "64MB", "128MB"]

        for board_file in self.board_files:
            with self.subTest(board=board_file.name):
                with open(board_file, 'r') as f:
                    data = json.load(f)
                    upload = data.get("upload", {})
                    flash_size = upload.get("flash_size", "")

                    self.assertIn(flash_size, valid_flash_sizes,
                        f"Invalid flash size '{flash_size}' in {board_file.name}")


if __name__ == '__main__':
    unittest.main()