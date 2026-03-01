"""
Unit tests for builder/main.py

Tests filesystem builders, partition parsing, and build utilities.
"""
import os
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch, mock_open
from pathlib import Path
import struct
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock SCons modules before import
sys.modules['SCons'] = MagicMock()
sys.modules['SCons.Script'] = MagicMock()
sys.modules['platformio'] = MagicMock()
sys.modules['platformio.project'] = MagicMock()
sys.modules['platformio.project.helpers'] = MagicMock()
sys.modules['platformio.util'] = MagicMock()
sys.modules['platformio.compat'] = MagicMock()
sys.modules['littlefs'] = MagicMock()
sys.modules['fatfs'] = MagicMock()
sys.modules['fatfs.partition_extended'] = MagicMock()
sys.modules['fatfs.wrapper'] = MagicMock()

# Import after mocking
from builder import main as builder_main


class TestParseSize(unittest.TestCase):
    """Test _parse_size function for various input formats."""

    def test_parse_size_int(self):
        """Test parsing integer values."""
        result = builder_main._parse_size(1024)
        self.assertEqual(result, 1024)

    def test_parse_size_string_numeric(self):
        """Test parsing string numeric values."""
        result = builder_main._parse_size("2048")
        self.assertEqual(result, 2048)

    def test_parse_size_hex(self):
        """Test parsing hexadecimal values."""
        result = builder_main._parse_size("0x1000")
        self.assertEqual(result, 4096)

    def test_parse_size_kb(self):
        """Test parsing kilobyte suffix."""
        result = builder_main._parse_size("4K")
        self.assertEqual(result, 4096)

        result = builder_main._parse_size("8k")
        self.assertEqual(result, 8192)

    def test_parse_size_mb(self):
        """Test parsing megabyte suffix."""
        result = builder_main._parse_size("1M")
        self.assertEqual(result, 1048576)

        result = builder_main._parse_size("2m")
        self.assertEqual(result, 2097152)

    def test_parse_size_invalid(self):
        """Test handling of invalid string values."""
        result = builder_main._parse_size("invalid")
        self.assertEqual(result, "invalid")


class TestNormalizeFrequency(unittest.TestCase):
    """Test _normalize_frequency function."""

    def test_normalize_frequency_basic(self):
        """Test normalizing basic frequency values."""
        result = builder_main._normalize_frequency("40000000")
        self.assertEqual(result, "40m")

    def test_normalize_frequency_with_l(self):
        """Test normalizing frequency with L suffix."""
        result = builder_main._normalize_frequency("80000000L")
        self.assertEqual(result, "80m")

    def test_normalize_frequency_small(self):
        """Test normalizing small frequency values."""
        result = builder_main._normalize_frequency("20000000")
        self.assertEqual(result, "20m")


class TestBeforeUpload(unittest.TestCase):
    """Test BeforeUpload function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.mock_env.BoardConfig.return_value = {
            "upload": {"use_1200bps_touch": False, "wait_for_upload_port": False}
        }
        self.mock_env.subst.return_value = "/dev/ttyUSB0"

    def test_before_upload_with_port(self):
        """Test BeforeUpload when upload port is set."""
        builder_main.BeforeUpload(None, None, self.mock_env)
        self.mock_env.subst.assert_called_with("$UPLOAD_PORT")

    def test_before_upload_without_port(self):
        """Test BeforeUpload when upload port is not set."""
        self.mock_env.subst.return_value = ""
        builder_main.BeforeUpload(None, None, self.mock_env)
        self.mock_env.AutodetectUploadPort.assert_called_once()

    def test_before_upload_with_1200bps_touch(self):
        """Test BeforeUpload with 1200bps touch enabled."""
        self.mock_env.BoardConfig.return_value = {
            "upload": {"use_1200bps_touch": True, "wait_for_upload_port": False}
        }
        with patch('builder.main.get_serial_ports') as mock_ports:
            mock_ports.return_value = []
            builder_main.BeforeUpload(None, None, self.mock_env)
            self.mock_env.TouchSerialPort.assert_called_once_with("$UPLOAD_PORT", 1200)


class TestBoardMemoryType(unittest.TestCase):
    """Test _get_board_memory_type function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.mock_board_config = MagicMock()
        self.mock_env.BoardConfig.return_value = self.mock_board_config
        self.mock_env.subst.return_value = "arduino"

    def test_default_memory_type(self):
        """Test default memory type calculation."""
        self.mock_board_config.get.side_effect = lambda key, default=None: {
            "build.flash_mode": "dio",
            "build.psram_type": "qspi"
        }.get(key, default)

        result = builder_main._get_board_memory_type(self.mock_env)
        self.assertEqual(result, "dio_qspi")

    def test_custom_memory_type(self):
        """Test custom memory type override."""
        self.mock_board_config.get.side_effect = lambda key, default=None: {
            "build.memory_type": "opi_opi",
            "build.flash_mode": "dio",
            "build.psram_type": "qspi"
        }.get(key, default)

        result = builder_main._get_board_memory_type(self.mock_env)
        self.assertEqual(result, "opi_opi")


class TestBoardFlashMode(unittest.TestCase):
    """Test _get_board_flash_mode function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()

    def test_flash_mode_opi(self):
        """Test flash mode for OPI memory type."""
        with patch('builder.main._get_board_memory_type') as mock_memory:
            mock_memory.return_value = "opi_opi"
            result = builder_main._get_board_flash_mode(self.mock_env)
            self.assertEqual(result, "dout")

    def test_flash_mode_qio_to_dio(self):
        """Test QIO mode conversion to DIO."""
        with patch('builder.main._get_board_memory_type') as mock_memory:
            mock_memory.return_value = "qio_qspi"
            self.mock_env.subst.return_value = "qio"
            result = builder_main._get_board_flash_mode(self.mock_env)
            self.assertEqual(result, "dio")

    def test_flash_mode_dio(self):
        """Test DIO flash mode."""
        with patch('builder.main._get_board_memory_type') as mock_memory:
            mock_memory.return_value = "dio_qspi"
            self.mock_env.subst.return_value = "dio"
            result = builder_main._get_board_flash_mode(self.mock_env)
            self.assertEqual(result, "dio")


class TestPartitionParsing(unittest.TestCase):
    """Test partition table parsing."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.partition_file = os.path.join(self.temp_dir, "partitions.csv")
        self.mock_env.subst.return_value = self.partition_file
        self.mock_env.Exit = MagicMock()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_parse_partitions_basic(self):
        """Test parsing basic partition table."""
        partition_content = """# Name, Type, SubType, Offset, Size, Flags
nvs,      data, nvs,     0x9000,  0x5000,
otadata,  data, ota,     0xe000,  0x2000,
app0,     app,  ota_0,   0x10000, 0x140000,
app1,     app,  ota_1,   0x150000,0x140000,
spiffs,   data, spiffs,  0x290000,0x170000,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        result = builder_main._parse_partitions(self.mock_env)

        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]['name'], 'nvs')
        self.assertEqual(result[2]['name'], 'app0')
        self.assertEqual(result[2]['subtype'], 'ota_0')

    def test_parse_partitions_with_comments(self):
        """Test parsing partition table with comments."""
        partition_content = """# ESP32 Partition Table
# Name, Type, SubType, Offset, Size
# This is a comment
nvs,      data, nvs,     ,  0x6000,
phy_init, data, phy,     ,  0x1000,
factory,  app,  factory, ,  1M,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        result = builder_main._parse_partitions(self.mock_env)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['name'], 'nvs')
        self.assertEqual(result[2]['name'], 'factory')

    def test_parse_partitions_missing_file(self):
        """Test handling of missing partition file."""
        self.mock_env.subst.return_value = "/nonexistent/partitions.csv"
        result = builder_main._parse_partitions(self.mock_env)
        self.mock_env.Exit.assert_called_with(1)


class TestFetchFsSize(unittest.TestCase):
    """Test fetch_fs_size function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.temp_dir = tempfile.mkdtemp()
        self.partition_file = os.path.join(self.temp_dir, "partitions.csv")
        self.mock_env.subst.return_value = self.partition_file
        self.mock_env.Exit = MagicMock()

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_fetch_fs_size_spiffs(self):
        """Test fetching filesystem size for SPIFFS partition."""
        partition_content = """# Name, Type, SubType, Offset, Size
nvs,      data, nvs,     0x9000,  0x5000,
app0,     app,  ota_0,   0x10000, 0x200000,
spiffs,   data, spiffs,  0x210000,0x1F0000,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        builder_main.fetch_fs_size(self.mock_env)

        self.assertEqual(self.mock_env.__setitem__.call_count, 4)
        # Check that FS_START and FS_SIZE were set
        calls = {call[0][0]: call[0][1] for call in self.mock_env.__setitem__.call_args_list}
        self.assertIn("FS_START", calls)
        self.assertIn("FS_SIZE", calls)

    def test_fetch_fs_size_littlefs(self):
        """Test fetching filesystem size for LittleFS partition."""
        partition_content = """# Name, Type, SubType, Offset, Size
nvs,      data, nvs,     0x9000,  0x5000,
app0,     app,  factory, 0x10000, 0x180000,
littlefs, data, littlefs,0x190000,0x270000,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        builder_main.fetch_fs_size(self.mock_env)

        calls = {call[0][0]: call[0][1] for call in self.mock_env.__setitem__.call_args_list}
        self.assertIn("FS_START", calls)
        self.assertIn("FS_SIZE", calls)

    def test_fetch_fs_size_fatfs(self):
        """Test fetching filesystem size for FatFS partition."""
        partition_content = """# Name, Type, SubType, Offset, Size
nvs,      data, nvs,     0x9000,  0x5000,
app0,     app,  factory, 0x10000, 0x300000,
fat,      data, fat,     0x310000,0xF0000,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        builder_main.fetch_fs_size(self.mock_env)

        calls = {call[0][0]: call[0][1] for call in self.mock_env.__setitem__.call_args_list}
        self.assertIn("FS_START", calls)
        self.assertIn("FS_SIZE", calls)

    def test_fetch_fs_size_no_filesystem(self):
        """Test error handling when no filesystem partition exists."""
        partition_content = """# Name, Type, SubType, Offset, Size
nvs,      data, nvs,     0x9000,  0x5000,
app0,     app,  factory, 0x10000, 0x3F0000,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        builder_main.fetch_fs_size(self.mock_env)

        self.mock_env.Exit.assert_called_with(1)


class TestToUnixSlashes(unittest.TestCase):
    """Test _to_unix_slashes function."""

    def test_convert_backslashes(self):
        """Test converting backslashes to forward slashes."""
        result = builder_main._to_unix_slashes("C:\\Users\\test\\file.txt")
        self.assertEqual(result, "C:/Users/test/file.txt")

    def test_already_unix_path(self):
        """Test handling of already Unix-style paths."""
        result = builder_main._to_unix_slashes("/home/user/file.txt")
        self.assertEqual(result, "/home/user/file.txt")

    def test_mixed_slashes(self):
        """Test handling of mixed slashes."""
        result = builder_main._to_unix_slashes("C:\\Users/test\\file.txt")
        self.assertEqual(result, "C:/Users/test/file.txt")


class TestUpdateMaxUploadSize(unittest.TestCase):
    """Test _update_max_upload_size function."""

    def setUp(self):
        """Set up test environment."""
        self.mock_env = MagicMock()
        self.mock_env.get.return_value = "/tmp/partitions.csv"
        self.temp_dir = tempfile.mkdtemp()
        self.partition_file = os.path.join(self.temp_dir, "partitions.csv")
        self.mock_env.subst.return_value = self.partition_file

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.temp_dir)

    def test_update_with_ota_partition(self):
        """Test updating max upload size with OTA partition."""
        partition_content = """# Name, Type, SubType, Offset, Size
nvs,      data, nvs,     0x9000,  0x5000,
otadata,  data, ota,     0xe000,  0x2000,
app0,     app,  ota_0,   0x10000, 0x140000,
app1,     app,  ota_1,   0x150000,0x140000,
"""
        with open(self.partition_file, 'w') as f:
            f.write(partition_content)

        with patch('builder.main.board') as mock_board:
            mock_board.get.return_value = ""
            mock_board.update = MagicMock()
            builder_main._update_max_upload_size(self.mock_env)
            # Should update board with app0 size (0x140000)
            mock_board.update.assert_called()


class TestCheckLibArchive(unittest.TestCase):
    """Test check_lib_archive_exists function."""

    def test_lib_archive_exists(self):
        """Test when lib_archive is set in config."""
        with patch('builder.main.projectconfig') as mock_config:
            mock_config.sections.return_value = ["common", "env:test"]
            mock_config.options.side_effect = [["other"], ["lib_archive", "other"]]

            result = builder_main.check_lib_archive_exists()
            self.assertTrue(result)

    def test_lib_archive_not_exists(self):
        """Test when lib_archive is not set in config."""
        with patch('builder.main.projectconfig') as mock_config:
            mock_config.sections.return_value = ["common", "env:test"]
            mock_config.options.side_effect = [["other"], ["debug"]]

            result = builder_main.check_lib_archive_exists()
            self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()