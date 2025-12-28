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

import locale
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
from os.path import isfile, join
from pathlib import Path
from littlefs import LittleFS
from fatfs import Partition, RamDisk, create_extended_partition
from fatfs import create_esp32_wl_image
from fatfs import calculate_esp32_wl_overhead
from fatfs import is_esp32_wl_image, extract_fat_from_esp32_wl
from fatfs.partition_extended import PartitionExtended
from fatfs.wrapper import pyf_mkfs, PY_FR_OK as FR_OK
import importlib.util

from SCons.Script import (
    ARGUMENTS,
    COMMAND_LINE_TARGETS,
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)

from platformio.project.helpers import get_project_dir
from platformio.util import get_serial_ports
from platformio.compat import IS_WINDOWS

# Initialize SCons environment and project configuration
env = DefaultEnvironment()
platform = env.PioPlatform()
projectconfig = env.GetProjectConfig()
terminal_cp = locale.getpreferredencoding().lower()
platform_dir = Path(env.PioPlatform().get_dir())
framework_dir = platform.get_package_dir("framework-arduinoespressif32")
core_dir = projectconfig.get("platformio", "core_dir")
build_dir = Path(projectconfig.get("platformio", "build_dir"))

# Configure Python environment through centralized platform management
PYTHON_EXE, esptool_binary_path = platform.setup_python_env(env)

# Load SPIFFS generator from local module
spiffsgen_path = platform_dir / "builder" / "spiffsgen.py"
spec = importlib.util.spec_from_file_location("spiffsgen", str(spiffsgen_path))
spiffsgen = importlib.util.module_from_spec(spec)
sys.modules["spiffsgen"] = spiffsgen
spec.loader.exec_module(spiffsgen)
SpiffsFS = spiffsgen.SpiffsFS
SpiffsBuildConfig = spiffsgen.SpiffsBuildConfig

# Load board configuration and determine MCU architecture
board = env.BoardConfig()
board_id = env.subst("$BOARD")
mcu = board.get("build.mcu", "esp32")
is_xtensa = mcu in ("esp32", "esp32s2", "esp32s3")
toolchain_arch = "xtensa-%s" % mcu
filesystem = board.get("build.filesystem", "littlefs")


def load_board_script(env):
    if not board_id:
        return

    script_path = platform_dir / "boards" / f"{board_id}.py"

    if script_path.exists():
        try:
            spec = importlib.util.spec_from_file_location(
                f"board_{board_id}", 
                str(script_path)
            )
            board_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(board_module)

            if hasattr(board_module, 'configure_board'):
                board_module.configure_board(env)

        except Exception as e:
            print(f"Error loading board script {board_id}.py: {e}")

def BeforeUpload(target, source, env):
    """
    Prepare the environment before uploading firmware.
    Handles port detection and special upload configurations.
    
    Args:
        target: SCons target
        source: SCons source
        env: SCons environment object
    """
    upload_options = {}
    if "BOARD" in env:
        upload_options = env.BoardConfig().get("upload", {})

    if not env.subst("$UPLOAD_PORT"):
        env.AutodetectUploadPort()

    before_ports = get_serial_ports()
    if upload_options.get("use_1200bps_touch", False):
        env.TouchSerialPort("$UPLOAD_PORT", 1200)

    if upload_options.get("wait_for_upload_port", False):
        env.Replace(UPLOAD_PORT=env.WaitForNewSerialPort(before_ports))


def _get_board_memory_type(env):
    """
    Determine the memory type configuration for the board.
    
    Args:
        env: SCons environment object
        
    Returns:
        str: The appropriate memory type string based on board configuration
    """
    board_config = env.BoardConfig()
    default_type = "%s_%s" % (
        board_config.get("build.flash_mode", "dio"),
        board_config.get("build.psram_type", "qspi"),
    )

    return board_config.get(
        "build.memory_type",
        board_config.get(
            "build.%s.memory_type"
            % env.subst("$PIOFRAMEWORK").strip().replace(" ", "_"),
            default_type,
        ),
    )


def _normalize_frequency(frequency):
    """
    Convert frequency value to normalized string format (e.g., "40m").
    
    Args:
        frequency: Frequency value to normalize
        
    Returns:
        str: Normalized frequency string with 'm' suffix
    """
    frequency = str(frequency).replace("L", "")
    return str(int(int(frequency) / 1000000)) + "m"


def _get_board_f_flash(env):
    """
    Get the flash frequency for the board.
    
    Args:
        env: SCons environment object
        
    Returns:
        str: Flash frequency string
    """
    frequency = env.subst("$BOARD_F_FLASH")
    return _normalize_frequency(frequency)


def _get_board_f_image(env):
    """
    Get the image frequency for the board, fallback to flash frequency.
    
    Args:
        env: SCons environment object
        
    Returns:
        str: Image frequency string
    """
    board_config = env.BoardConfig()
    if "build.f_image" in board_config:
        return _normalize_frequency(board_config.get("build.f_image"))

    return _get_board_f_flash(env)


def _get_board_f_boot(env):
    """
    Get the boot frequency for the board, fallback to flash frequency.
    
    Args:
        env: SCons environment object
        
    Returns:
        str: Boot frequency string
    """
    board_config = env.BoardConfig()
    if "build.f_boot" in board_config:
        return _normalize_frequency(board_config.get("build.f_boot"))

    return _get_board_f_flash(env)


def _get_board_flash_mode(env):
    """
    Determine the appropriate flash mode for the board.
    Handles special cases for OPI memory types.
    
    Args:
        env: SCons environment object
        
    Returns:
        str: Flash mode string
    """
    if _get_board_memory_type(env) in ("opi_opi", "opi_qspi"):
        return "dout"

    mode = env.subst("$BOARD_FLASH_MODE")
    if mode in ("qio", "qout"):
        return "dio"
    return mode


def _get_board_boot_mode(env):
    """
    Determine the boot mode for the board.
    Handles special cases for OPI memory types.
    
    Args:
        env: SCons environment object
        
    Returns:
        str: Boot mode string
    """
    memory_type = env.BoardConfig().get("build.arduino.memory_type", "")
    build_boot = env.BoardConfig().get("build.boot", "$BOARD_FLASH_MODE")
    if memory_type in ("opi_opi", "opi_qspi"):
        build_boot = "opi"
    return build_boot


def _parse_size(value):
    """
    Parse size values from various formats (int, hex, K/M suffixes).
    
    Args:
        value: Size value to parse
        
    Returns:
        int: Size in bytes as an integer
    """
    if isinstance(value, int):
        return value
    elif value.isdigit():
        return int(value)
    elif value.startswith("0x"):
        return int(value, 16)
    elif value[-1].upper() in ("K", "M"):
        base = 1024 if value[-1].upper() == "K" else 1024 * 1024
        return int(value[:-1]) * base
    return value


def _parse_partitions(env):
    """
    Parse the partition table CSV file and return partition information.
    Also sets the application offset for the environment.
    
    Args:
        env: SCons environment object
        
    Returns:
        list: List of partition dictionaries
    """
    partitions_csv = env.subst("$PARTITIONS_TABLE_CSV")
    if not isfile(partitions_csv):
        sys.stderr.write(
            "Could not find the file %s with partitions table.\n"
            % partitions_csv
        )
        env.Exit(1)
        return

    result = []
    next_offset = 0
    app_offset = 0x10000  # Default address for firmware

    with open(partitions_csv) as fp:
        for line in fp.readlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = [t.strip() for t in line.split(",")]
            if len(tokens) < 5:
                continue
            bound = 0x10000 if tokens[1] in ("0", "app") else 4
            calculated_offset = (next_offset + bound - 1) & ~(bound - 1)
            partition = {
                "name": tokens[0],
                "type": tokens[1],
                "subtype": tokens[2],
                "offset": tokens[3] or calculated_offset,
                "size": tokens[4],
                "flags": tokens[5] if len(tokens) > 5 else None,
            }
            result.append(partition)
            next_offset = _parse_size(partition["offset"])
            if partition["subtype"] == "ota_0":
                app_offset = next_offset
            next_offset = next_offset + _parse_size(partition["size"])

    # Configure application partition offset
    env.Replace(ESP32_APP_OFFSET=str(hex(app_offset)))
    # Propagate application offset to debug configurations
    env["INTEGRATION_EXTRA_DATA"].update(
        {"application_offset": str(hex(app_offset))}
    )
    return result


def _update_max_upload_size(env):
    """
    Update the maximum upload size based on partition table configuration.
    Prioritizes user-specified partition names.
    
    Args:
        env: SCons environment object
    """
    if not env.get("PARTITIONS_TABLE_CSV"):
        return

    sizes = {
        p["subtype"]: _parse_size(p["size"])
        for p in _parse_partitions(env)
        if p["type"] in ("0", "app")
    }

    partitions = {p["name"]: p for p in _parse_partitions(env)}

    # User-specified partition name has the highest priority
    custom_app_partition_name = board.get("build.app_partition_name", "")
    if custom_app_partition_name:
        selected_partition = partitions.get(custom_app_partition_name, {})
        if selected_partition:
            board.update(
                "upload.maximum_size", _parse_size(selected_partition["size"])
            )
            return
        else:
            print(
                "Warning! Selected partition `%s` is not available in the "
                "partition table! Default partition will be used!"
                % custom_app_partition_name
            )

    for p in partitions.values():
        if p["type"] in ("0", "app") and p["subtype"] in ("ota_0"):
            board.update("upload.maximum_size", _parse_size(p["size"]))
            break


def _to_unix_slashes(path):
    """
    Convert Windows-style backslashes to Unix-style forward slashes.
    
    Args:
        path (str): Path to convert
        
    Returns:
        str: Path with Unix-style slashes
    """
    return path.replace("\\", "/")


def fetch_fs_size(env):
    """
    Extract filesystem size and offset information from partition table.
    Sets FS_START, FS_SIZE, FS_PAGE, and FS_BLOCK environment variables.
    
    Args:
        env: SCons environment object
    """
    fs = None
    for p in _parse_partitions(env):
        if p["type"] == "data" and p["subtype"] in (
            "spiffs",
            "fat",
            "littlefs",
        ):
            fs = p
    if not fs:
        sys.stderr.write(
            "Could not find the any filesystem section in the partitions "
            "table %s\n" % env.subst("$PARTITIONS_TABLE_CSV")
        )
        env.Exit(1)
        return
    
    env["FS_START"] = _parse_size(fs["offset"])
    env["FS_SIZE"] = _parse_size(fs["size"])
    env["FS_PAGE"] = int("0x100", 16)
    env["FS_BLOCK"] = int("0x1000", 16)


def __fetch_fs_size(target, source, env):
    """
    Wrapper function for fetch_fs_size to be used as SCons emitter.
    
    Args:
        target: SCons target
        source: SCons source
        env: SCons environment object
        
    Returns:
        tuple: (target, source) tuple
    """
    fetch_fs_size(env)
    return (target, source)


def build_fs_image(target, source, env):
    """
    Build filesystem image using littlefs-python.

    Args:
        target: SCons target (output .bin file)
        source: SCons source (directory with files)
        env: SCons environment object

    Returns:
        int: 0 on success, 1 on failure
    """

    # Get parameters
    source_dir = str(source[0])
    target_file = str(target[0])
    fs_size = env["FS_SIZE"]
    block_size = env.get("FS_BLOCK", 4096)

    # Calculate block count
    block_count = fs_size // block_size

    # Get disk version from board config or project options
    # Default to LittleFS version 2.1 (0x00020001)
    disk_version_str = "2.1"
    
    # Try to read from project config (env-specific or common section)
    for section in ["env:" + env["PIOENV"], "common"]:
        if projectconfig.has_option(section, "board_build.littlefs_version"):
            disk_version_str = projectconfig.get(section, "board_build.littlefs_version")
            break
    
    # Parse version string and create proper version integer
    # LittleFS version format: (major << 16) | (minor << 0)
    try:
        version_parts = str(disk_version_str).split(".")
        major = int(version_parts[0])
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
        # Format: major in upper 16 bits, minor in lower 16 bits
        disk_version = (major << 16) | minor
    except (ValueError, IndexError):
        print(f"Warning: Invalid littlefs version '{disk_version_str}', using default 2.1")
        disk_version = (2 << 16) | 1

    try:
        # Create LittleFS instance with Arduino / IDF compatible parameters
        fs = LittleFS(
            block_size=block_size,
            block_count=block_count,
            read_size=1,              # Minimum read size
            prog_size=1,              # Minimum program size
            cache_size=block_size,    # Cache size = block size
            lookahead_size=32,        # Default lookahead buffer
            block_cycles=500,         # Wear leveling cycles
            name_max=64,              # ESP-IDF default filename length
            disk_version=disk_version,
            mount=True
        )

        # Add all files from source directory
        source_path = Path(source_dir)
        if source_path.exists():
            for item in source_path.rglob("*"):
                rel_path = item.relative_to(source_path)
                fs_path = rel_path.as_posix()
                
                if item.is_dir():
                    fs.makedirs(fs_path, exist_ok=True)
                    # Set directory mtime attribute
                    try:
                        mtime = int(item.stat().st_mtime)
                        fs.setattr(fs_path, 't', mtime.to_bytes(4, 'little'))
                    except Exception:
                        pass  # Ignore timestamp errors
                else:
                    # Ensure parent directories exist
                    if rel_path.parent != Path("."):
                        fs.makedirs(rel_path.parent.as_posix(), exist_ok=True)
                    # Copy file
                    with fs.open(fs_path, "wb") as dest:
                        dest.write(item.read_bytes())
                    # Set file mtime attribute (ESP-IDF compatible)
                    try:
                        mtime = int(item.stat().st_mtime)
                        fs.setattr(fs_path, 't', mtime.to_bytes(4, 'little'))
                    except Exception:
                        pass  # Ignore timestamp errors

        # Write filesystem image
        with open(target_file, "wb") as f:
            f.write(fs.context.buffer)

        return 0

    except Exception as e:
        print(f"Error building filesystem image: {e}")
        return 1


def build_spiffs_image(target, source, env):
    """
    Build SPIFFS filesystem image using spiffsgen.py.

    Args:
        target: SCons target (output .bin file)
        source: SCons source (directory with files)
        env: SCons environment object

    Returns:
        int: 0 on success, 1 on failure
    """

    # Get parameters
    source_dir = str(source[0])
    target_file = str(target[0])
    fs_size = env["FS_SIZE"]
    page_size = env.get("FS_PAGE", 256)
    block_size = env.get("FS_BLOCK", 4096)

    # Get SPIFFS configuration from project config or use defaults
    obj_name_len = 32
    meta_len = 4
    use_magic = True
    use_magic_len = True
    aligned_obj_ix_tables = False

    # Check common section first, then env-specific (so env-specific takes precedence)
    for section in ["common", "env:" + env["PIOENV"]]:
        if projectconfig.has_option(section, "board_build.spiffs.obj_name_len"):
            obj_name_len = int(projectconfig.get(section, "board_build.spiffs.obj_name_len"))
        if projectconfig.has_option(section, "board_build.spiffs.meta_len"):
            meta_len = int(projectconfig.get(section, "board_build.spiffs.meta_len"))
        if projectconfig.has_option(section, "board_build.spiffs.use_magic"):
            use_magic = projectconfig.getboolean(section, "board_build.spiffs.use_magic")
        if projectconfig.has_option(section, "board_build.spiffs.use_magic_len"):
            use_magic_len = projectconfig.getboolean(section, "board_build.spiffs.use_magic_len")
        if projectconfig.has_option(section, "board_build.spiffs.aligned_obj_ix_tables"):
            aligned_obj_ix_tables = projectconfig.getboolean(section, "board_build.spiffs.aligned_obj_ix_tables")

    try:
        # Create SPIFFS build configuration
        spiffs_build_config = SpiffsBuildConfig(
            page_size=page_size,
            page_ix_len=2,  # SPIFFS_PAGE_IX_LEN
            block_size=block_size,
            block_ix_len=2,  # SPIFFS_BLOCK_IX_LEN
            meta_len=meta_len,
            obj_name_len=obj_name_len,
            obj_id_len=2,  # SPIFFS_OBJ_ID_LEN
            span_ix_len=2,  # SPIFFS_SPAN_IX_LEN
            packed=True,
            aligned=True,
            endianness='little',
            use_magic=use_magic,
            use_magic_len=use_magic_len,
            aligned_obj_ix_tables=aligned_obj_ix_tables
        )

        # Create SPIFFS filesystem
        spiffs = SpiffsFS(fs_size, spiffs_build_config)

        # Add all files from source directory
        source_path = Path(source_dir)
        if source_path.exists():
            for item in source_path.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(source_path)
                    img_path = "/" + rel_path.as_posix()
                    spiffs.create_file(img_path, str(item))

        # Generate binary image
        image = spiffs.to_binary()

        # Write to file
        with open(target_file, "wb") as f:
            f.write(image)

        print(f"\nSuccessfully created SPIFFS image: {target_file}")
        return 0

    except Exception as e:
        print(f"Error building SPIFFS image: {e}")
        return 1


def build_fatfs_image(target, source, env):
    """
    Build FatFS filesystem image with ESP32 Wear Leveling support.
    
    Uses fatfs-ng module to create ESP-IDF compatible WL-wrapped FAT images.

    Args:
        target: SCons target (output .bin file)
        source: SCons source (directory with files)
        env: SCons environment object

    Returns:
        int: 0 on success, 1 on failure
    """

    # Get parameters
    source_dir = str(source[0])
    target_file = str(target[0])
    fs_size = env["FS_SIZE"]
    sector_size = env.get("FS_SECTOR", 4096)
    
    # ESP-IDF WL layout (following wl_fatfsgen.py):
    # [dummy sector] [FAT data] [state1] [state2] [config]
    # Total WL sectors: 1 dummy + 2 states + 1 config = 4 sectors
    wl_info = calculate_esp32_wl_overhead(fs_size, sector_size)
    
    wl_reserved_sectors = wl_info['wl_overhead_sectors']
    fat_fs_size = wl_info['fat_size']
    sector_count = wl_info['fat_sectors']

    try:
        # Create RAM disk with the FAT filesystem size (without WL overhead)
        storage = bytearray(fat_fs_size)
        disk = RamDisk(storage, sector_size=sector_size, sector_count=sector_count)

        # Create partition, format, and mount
        base_partition = Partition(disk)

        # Format the filesystem with proper workarea size for LFN support
        # Workarea needs to be at least sector_size, use 2x for safety with LFN
        workarea_size = sector_size * 2
        
        # Create filesystem with parameters matching ESP-IDF expectations:
        # - n_fat=2: Two FAT copies for redundancy
        # - align=0: Auto-align (let FATFS decide)
        # - n_root=512: Number of root directory entries (FAT12/16 only, 0 for FAT32)
        # - au_size=0: Auto allocation unit size
        ret = pyf_mkfs(
            base_partition.pname, 
            n_fat=2, 
            align=0,
            n_root=512,  # Standard root entries for FAT16
            au_size=0,   # Auto
            workarea_size=workarea_size
        )
        if ret != FR_OK:
            raise Exception(f"Failed to format filesystem: error code {ret}")

        # Mount the filesystem
        base_partition.mount()

        # Wrap with extended partition for directory support
        partition = PartitionExtended(base_partition)

        # Track skipped files
        skipped_files = []

        # Add all files from source directory
        source_path = Path(source_dir)
        if source_path.exists():
            for item in source_path.rglob("*"):
                rel_path = item.relative_to(source_path)
                fs_path = "/" + rel_path.as_posix()

                if item.is_dir():
                    try:
                        partition.mkdir(fs_path)
                    except Exception:
                        # Directory might already exist or be root
                        pass
                else:
                    # Ensure parent directories exist
                    if rel_path.parent != Path("."):
                        parent_path = "/" + rel_path.parent.as_posix()
                        try:
                            partition.mkdir(parent_path)
                        except Exception:
                            pass  # Directory might already exist

                    # Copy file
                    try:
                        with partition.open(fs_path, "w") as dest:
                            dest.write(item.read_bytes())
                    except Exception as e:
                        print(f"Warning: Failed to write file {rel_path}: {e}")
                        skipped_files.append(str(rel_path))

        # Unmount filesystem
        base_partition.unmount()
        
        # Read boot sector parameters for validation
        bytes_per_sector = struct.unpack('<H', storage[11:13])[0]
        reserved_sectors = struct.unpack('<H', storage[14:16])[0]
        num_fats = storage[16]
        sectors_per_fat = struct.unpack('<H', storage[22:24])[0]
        total_sectors = struct.unpack('<H', storage[19:21])[0]
        
        # Validate boot sector matches our expectations
        if bytes_per_sector != sector_size:
            raise Exception(f"Boot sector bytes_per_sector ({bytes_per_sector}) != sector_size ({sector_size})")
        
        print(f"\nBoot sector validation:")
        print(f"  Bytes per sector: {bytes_per_sector}")
        print(f"  Reserved sectors: {reserved_sectors}")
        print(f"  Number of FATs: {num_fats}")
        print(f"  Sectors per FAT: {sectors_per_fat}")
        print(f"  Total sectors: {total_sectors}")
        
        # Wrap FAT image with ESP-IDF wear leveling layer
        # This uses the fatfs-ng module's ESP32WearLeveling implementation
        print(f"\nWrapping FAT image with ESP-IDF wear leveling...")
        print(f"  Layout: {wl_info['layout']}")
        print(f"  Partition size: {fs_size} bytes")
        print(f"  FAT filesystem size: {fat_fs_size} bytes ({sector_count} sectors)")
        print(f"  WL overhead: {wl_reserved_sectors} sectors ({wl_info['wl_overhead_size']} bytes)")

        wl_image = create_esp32_wl_image(bytes(storage), fs_size, sector_size)
        
        print(f"  WL-wrapped image created ({len(wl_image)} bytes)")

        # Write WL-wrapped image to file
        with open(target_file, "wb") as f:
            f.write(wl_image)

        # Print summary
        if skipped_files:
            print(f"\nWarning: {len(skipped_files)} file(s) skipped:")
            for skipped in skipped_files[:10]:  # Show first 10
                print(f"  - {skipped}")
            if len(skipped_files) > 10:
                print(f"  ... and {len(skipped_files) - 10} more")
        
        print(f"\nSuccessfully created ESP-IDF WL-wrapped FAT image: {target_file}")

        return 0

    except Exception as e:
        print(f"Error building FatFS image: {e}")
        return 1


def check_lib_archive_exists():
    """
    Check if lib_archive is set in platformio.ini configuration.
    
    Returns:
        bool: True if found, False otherwise
    """
    for section in projectconfig.sections():
        if "lib_archive" in projectconfig.options(section):
            return True
    return False


def build_fs_router(target, source, env):
    """Route to appropriate filesystem builder based on filesystem type."""
    fs_type = board.get("build.filesystem", "littlefs")
    if fs_type == "littlefs":
        return build_fs_image(target, source, env)
    elif fs_type == "fatfs":
        return build_fatfs_image(target, source, env)
    elif fs_type == "spiffs":
        return build_spiffs_image(target, source, env)
    else:
        print(f"Error: Unknown filesystem type '{fs_type}'. Supported types: littlefs, fatfs, spiffs")
        return 1


def switch_off_ldf():
    """
    Disables LDF (Library Dependency Finder) for uploadfs, uploadfsota, buildfs, 
    download_fs, and erase targets.

    This optimization prevents unnecessary library dependency scanning and compilation
    when only filesystem operations are performed.
    """
    fs_targets = {"uploadfs", "uploadfsota", "buildfs", "erase", "download_fs"}
    if fs_targets & set(COMMAND_LINE_TARGETS):
        # Disable LDF by modifying project configuration directly
        env_section = "env:" + env["PIOENV"]
        if not projectconfig.has_section(env_section):
            projectconfig.add_section(env_section)
        projectconfig.set(env_section, "lib_ldf_mode", "off")


# Board specific script
load_board_script(env)

# Set toolchain architecture for RISC-V based ESP32 variants
if not is_xtensa:
    toolchain_arch = "riscv32-esp"

# Ensure integration extra data structure exists
if "INTEGRATION_EXTRA_DATA" not in env:
    env["INTEGRATION_EXTRA_DATA"] = {}

# Take care of possible whitespaces in path
uploader_path = (
    f'"{esptool_binary_path}"' 
    if ' ' in esptool_binary_path 
    else esptool_binary_path
)
# Configure SCons build tools and compiler settings
env.Replace(
    __get_board_boot_mode=_get_board_boot_mode,
    __get_board_f_flash=_get_board_f_flash,
    __get_board_f_image=_get_board_f_image,
    __get_board_f_boot=_get_board_f_boot,
    __get_board_flash_mode=_get_board_flash_mode,
    __get_board_memory_type=_get_board_memory_type,
    AR="%s-elf-gcc-ar" % toolchain_arch,
    AS="%s-elf-as" % toolchain_arch,
    CC="%s-elf-gcc" % toolchain_arch,
    CXX="%s-elf-g++" % toolchain_arch,
    GDB=join(
        platform.get_package_dir(
            "tool-riscv32-esp-elf-gdb"
            if not is_xtensa
            else "tool-xtensa-esp-elf-gdb"
        )
        or "",
        "bin",
        "%s-elf-gdb" % toolchain_arch,
    ),
    OBJCOPY=uploader_path,
    RANLIB="%s-elf-gcc-ranlib" % toolchain_arch,
    SIZETOOL="%s-elf-size" % toolchain_arch,
    ARFLAGS=["rc"],
    SIZEPROGREGEXP=r"^(?:\.iram0\.text|\.iram0\.vectors|\.dram0\.data|"
    r"\.flash\.text|\.flash\.rodata|)\s+([0-9]+).*",
    SIZEDATAREGEXP=r"^(?:\.dram0\.data|\.dram0\.bss|\.noinit)\s+([0-9]+).*",
    SIZECHECKCMD="$SIZETOOL -A -d $SOURCES",
    SIZEPRINTCMD="$SIZETOOL -B -d $SOURCES",
    ERASEFLAGS=["--chip", mcu, "--port", '"$UPLOAD_PORT"'],
    ERASETOOL=uploader_path,
    ERASECMD='$ERASETOOL $ERASEFLAGS erase-flash',
    ESP32_FS_IMAGE_NAME=env.get(
        "ESP32_FS_IMAGE_NAME",
        env.get("ESP32_SPIFFS_IMAGE_NAME", filesystem),
    ),
    ESP32_APP_OFFSET=env.get("INTEGRATION_EXTRA_DATA").get(
        "application_offset"
    ),
    ARDUINO_LIB_COMPILE_FLAG="Inactive",
    PROGSUFFIX=".elf",
)

# Check if lib_archive is set in platformio.ini and set it to False
# if not found. This makes weak defs in framework and libs possible.
if not check_lib_archive_exists():
    env_section = "env:" + env["PIOENV"]
    projectconfig.set(env_section, "lib_archive", "False")

# Allow user to override via pre:script
if env.get("PROGNAME", "program") == "program":
    env.Replace(PROGNAME="firmware")

# Configure build actions and builders
env.Append(
    BUILDERS=dict(
        ElfToBin=Builder(
            action=env.VerboseAction(
                " ".join(
                    [
                        "$ERASETOOL",
                        "--chip",
                        mcu,
                        "elf2image",
                        "--flash-mode",
                        "${__get_board_flash_mode(__env__)}",
                        "--flash-freq",
                        "${__get_board_f_image(__env__)}",
                        "--flash-size",
                        board.get("upload.flash_size", "4MB"),
                        "-o",
                        "\"$TARGET\"",
                        "\"$SOURCES\"",
                    ]
                ),
                "Building $TARGET",
            ),
            suffix=".bin",
        ),
        DataToBin=Builder(
            action=env.VerboseAction(
                build_fs_router,
                "Building FS image from '$SOURCES' directory to $TARGET",
            ),
            emitter=__fetch_fs_size,
            source_factory=env.Dir,
            suffix=".bin",
        ),
    )
)

# Load framework-specific configuration
if not env.get("PIOFRAMEWORK"):
    env.SConscript("frameworks/_bare.py", exports="env")


# Disable LDF for filesystem operations
switch_off_ldf()


def firmware_metrics(target, source, env):
    """
    Custom target to run esp-idf-size with support for command line parameters.
    Usage: pio run -t metrics -- [esp-idf-size arguments]
    
    Args:
        target: SCons target
        source: SCons source
        env: SCons environment object
    """
    if terminal_cp not in ["utf-8", "cp65001"]:
        print("Firmware metrics can not be shown. Set the terminal codepage to \"utf-8\" or \"cp65001\" on Windows.")
        return

    map_file = str(Path(env.subst("$BUILD_DIR")) / (env.subst("$PROGNAME") + ".map"))
    if not Path(map_file).is_file():
        # map file can be in project dir
        map_file = str(Path(get_project_dir()) / (env.subst("$PROGNAME") + ".map"))

    if not Path(map_file).is_file():
        print(f"Error: Map file not found: {map_file}")
        print("Make sure the project is built first with 'pio run'")
        return

    try:        
        cmd = [PYTHON_EXE, "-m", "esp_idf_size"]
        
        # Parameters from platformio.ini
        extra_args = env.GetProjectOption("custom_esp_idf_size_args", "")
        if extra_args:
            cmd.extend(shlex.split(extra_args))
        
        # Command Line Parameter, after --
        cli_args = []
        if "--" in sys.argv:
            dash_index = sys.argv.index("--")
            if dash_index + 1 < len(sys.argv):
                cli_args = sys.argv[dash_index + 1:]

        # Add CLI arguments before the map file
        if cli_args:
            cmd.extend(cli_args)

        # Map-file as last argument
        cmd.append(map_file)
        
        # Debug-Info if wanted
        if env.GetProjectOption("custom_esp_idf_size_verbose", False):
            print(f"Running command: {' '.join(cmd)}")
        
        # Execute esp-idf-size with current environment
        result = subprocess.run(cmd, check=False, capture_output=False, env=os.environ)
        
        if result.returncode != 0:
            print(f"Warning: esp-idf-size exited with code {result.returncode}")

    except FileNotFoundError:
        print("Error: Python executable not found.")
        print("Check your Python installation.")
    except Exception as e:
        print(f"Error: Failed to run firmware metrics: {e}")
        print(f'Make sure esp-idf-size is installed: uv pip install --python "{PYTHON_EXE}" esp-idf-size')


def coredump_analysis(target, source, env):
    """
    Custom target to run esp-coredump with support for command line parameters.
    Usage: pio run -t coredump -- [esp-coredump arguments]
    
    Args:
        target: SCons target
        source: SCons source
        env: SCons environment object
    """
    if terminal_cp != "utf-8":
        print("Coredump analysis can not be shown. Set the terminal codepage to \"utf-8\"")
        return

    elf_file = str(Path(env.subst("$BUILD_DIR")) / (env.subst("$PROGNAME") + ".elf"))
    if not Path(elf_file).is_file():
        # elf file can be in project dir
        elf_file = str(Path(get_project_dir()) / (env.subst("$PROGNAME") + ".elf"))

    if not Path(elf_file).is_file():
        print(f"Error: ELF file not found: {elf_file}")
        print("Make sure the project is built first with 'pio run'")
        return

    try:        
        cmd = [PYTHON_EXE, "-m", "esp_coredump"]
        
        # Command Line Parameter, after --
        cli_args = []
        if "--" in sys.argv:
            dash_index = sys.argv.index("--")
            if dash_index + 1 < len(sys.argv):
                cli_args = sys.argv[dash_index + 1:]

        # Add CLI arguments or use defaults
        if cli_args:
            cmd.extend(cli_args)
            # ELF file should be at the end as positional argument
            if not any(arg.endswith('.elf') for arg in cli_args):
                cmd.append(elf_file)
        else:
            # Default arguments if none provided
            # Parameters from platformio.ini
            extra_args = env.GetProjectOption("custom_esp_coredump_args", "")
            if extra_args:
                args = shlex.split(extra_args)
                cmd.extend(args)
                # Ensure ELF is last positional if not present
                if not any(a.endswith(".elf") for a in args):
                    cmd.append(elf_file)
            else:
                # Prefer an explicit core file if configured or present; else read from flash
                core_file = env.GetProjectOption("custom_esp_coredump_corefile", "")
                if not core_file:
                    for name in ("coredump.bin", "coredump.b64"):
                        cand = Path(get_project_dir()) / name
                        if cand.is_file():
                            core_file = str(cand)
                            break

                # Global options
                cmd.extend(["--chip", mcu])
                upload_port = env.subst("$UPLOAD_PORT")
                if upload_port:
                    cmd.extend(["--port", upload_port])

                # Subcommand and arguments
                cmd.append("info_corefile")
                if core_file:
                    cmd.extend(["--core", core_file])
                    if core_file.lower().endswith(".b64"):
                        cmd.extend(["--core-format", "b64"])
                # ELF is the required positional
                cmd.append(elf_file)

        # Set up ESP-IDF environment variables and ensure required packages are installed
        coredump_env = os.environ.copy()
        
        # Check if ESP-IDF packages are available, install if missing
        _framework_pkg_dir = platform.get_package_dir("framework-espidf")
        _rom_elfs_dir = platform.get_package_dir("tool-esp-rom-elfs")
        
        # Install framework-espidf if not available
        if not _framework_pkg_dir or not os.path.isdir(_framework_pkg_dir):
            print("ESP-IDF framework not found, installing...")
            try:
                platform.install_package("framework-espidf")
                _framework_pkg_dir = platform.get_package_dir("framework-espidf")
            except Exception as e:
                print(f"Warning: Failed to install framework-espidf: {e}")
        
        # Install tool-esp-rom-elfs if not available
        if not _rom_elfs_dir or not os.path.isdir(_rom_elfs_dir):
            print("ESP ROM ELFs tool not found, installing...")
            try:
                platform.install_package("tool-esp-rom-elfs")
                _rom_elfs_dir = platform.get_package_dir("tool-esp-rom-elfs")
            except Exception as e:
                print(f"Warning: Failed to install tool-esp-rom-elfs: {e}")
        
        # Set environment variables if packages are available
        if _framework_pkg_dir and os.path.isdir(_framework_pkg_dir):
            coredump_env['IDF_PATH'] = str(Path(_framework_pkg_dir).resolve())
            if _rom_elfs_dir and os.path.isdir(_rom_elfs_dir):
                coredump_env['ESP_ROM_ELF_DIR'] = str(Path(_rom_elfs_dir).resolve())

        # Debug-Info if wanted
        if env.GetProjectOption("custom_esp_coredump_verbose", False):
            print(f"Running command: {' '.join(cmd)}")
            if 'IDF_PATH' in coredump_env:
                print(f"IDF_PATH: {coredump_env['IDF_PATH']}")
                print(f"ESP_ROM_ELF_DIR: {coredump_env.get('ESP_ROM_ELF_DIR', 'Not set')}")
        
        # Execute esp-coredump with ESP-IDF environment
        result = subprocess.run(cmd, check=False, capture_output=False, env=coredump_env)
        
        if result.returncode != 0:
            print(f"Warning: esp-coredump exited with code {result.returncode}")

    except FileNotFoundError:
        print("Error: Python executable not found.")
        print("Check your Python installation.")
    except Exception as e:
        print(f"Error: Failed to run coredump analysis: {e}")
        print(f'Make sure esp-coredump is installed: uv pip install --python "{PYTHON_EXE}" esp-coredump')


def _get_unpack_dir(env):
    """
    Get the unpack directory from project configuration.

    Args:
        env: SCons environment object

    Returns:
        str: Unpack directory path
    """
    unpack_dir = "unpacked_fs"

    # Read from project config (env-specific or common section)
    for section in ["env:" + env["PIOENV"], "common"]:
        if projectconfig.has_option(section, "board_build.unpack_dir"):
            unpack_dir = projectconfig.get(section, "board_build.unpack_dir")
            break

    return unpack_dir


def _prepare_unpack_dir(unpack_dir):
    """
    Prepare the unpack directory by removing old content and creating fresh directory.

    Args:
        unpack_dir: Directory path to prepare

    Returns:
        Path: Path object for the unpack directory
    """
    unpack_path = Path(get_project_dir()) / unpack_dir
    if unpack_path.exists():
        shutil.rmtree(unpack_path)
    unpack_path.mkdir(parents=True, exist_ok=True)
    return unpack_path


def _download_partition_image(env, fs_type_filter=None):
    """
    Common function to download partition table and filesystem image from device.

    Args:
        env: SCons environment object
        fs_type_filter: List of partition subtypes to look for (e.g., [0x82, 0x83] for LittleFS/SPIFFS)
                       or [0x81] for FAT. If None, accepts any data partition.

    Returns:
        tuple: (fs_file_path, fs_start, fs_size, fs_subtype) or (None, None, None, None) on error
    """
    # Ensure upload port is set
    if not env.subst("$UPLOAD_PORT"):
        env.AutodetectUploadPort()

    upload_port = env.subst("$UPLOAD_PORT")
    download_speed = board.get("download.speed", "115200")

    # Download partition table from device
    print(f"\nDownloading partition table from {upload_port}...\n")

    build_dir = Path(env.subst("$BUILD_DIR"))
    build_dir.mkdir(parents=True, exist_ok=True)
    partition_file = build_dir / "partition_table_from_flash.bin"

    esptool_cmd = [
        uploader_path.strip('"'),
        "--port", upload_port,
        "--baud", str(download_speed),
        "--before", "default-reset",
        "--after", "hard-reset",
        "read-flash",
        "0x8000",  # Partition table offset
        "0x1000",  # Partition table size (4KB)
        str(partition_file)
    ]

    try:
        result = subprocess.run(esptool_cmd, check=False)
        if result.returncode != 0:
            print("Error: Failed to download partition table")
            return None, None, None, None
    except Exception as e:
        print(f"Error: {e}")
        return None, None, None, None

    with open(partition_file, 'rb') as f:
        partition_data = f.read()

    # Parse partition entries (format: 0xAA 0x50 followed by entry data)
    entries = [e for e in partition_data.split(b'\xaaP') if len(e) > 0]

    fs_start = None
    fs_size = None
    fs_subtype = None

    for entry in entries:
        if len(entry) < 32:
            continue

        # Byte 0: Type (0x01 for data partitions)
        # Byte 1: SubType (0x81=FAT, 0x82=SPIFFS, 0x83=LittleFS)
        # Bytes 2-5: Offset (4 bytes, little-endian)
        # Bytes 6-9: Size (4 bytes, little-endian)

        part_subtype = entry[1]

        # Check if this partition matches our filter
        if fs_type_filter is None or part_subtype in fs_type_filter:
            fs_start = int.from_bytes(entry[2:6], byteorder='little', signed=False)
            fs_size = int.from_bytes(entry[6:10], byteorder='little', signed=False)
            fs_subtype = part_subtype
            break

    if fs_start is None or fs_size is None:
        print("Error: No matching filesystem partition found in partition table")
        return None, None, None, None

    print(f"\nFound filesystem partition (subtype {hex(fs_subtype)}):")
    print(f"  Start: {hex(fs_start)}")
    print(f"  Size: {hex(fs_size)} ({fs_size} bytes)")

    # Download filesystem image
    fs_file = build_dir / f"downloaded_fs_{hex(fs_start)}_{hex(fs_size)}.bin"

    print("\nDownloading filesystem from device...\n")

    esptool_cmd = [
        uploader_path.strip('"'),
        "--port", upload_port,
        "--baud", str(download_speed),
        "--before", "default-reset",
        "--after", "hard-reset",
        "read-flash",
        hex(fs_start),
        hex(fs_size),
        str(fs_file)
    ]

    try:
        result = subprocess.run(esptool_cmd, check=False)
        if result.returncode != 0:
            print(f"Error: Download failed with code {result.returncode}")
            return None, None, None, None
    except Exception as e:
        print(f"Error: {e}")
        return None, None, None, None

    print(f"\nDownloaded to {fs_file}")

    return fs_file, fs_start, fs_size, fs_subtype


def _parse_littlefs_superblock(fs_data):
    """Parse LittleFS superblock to extract filesystem parameters.
    
    The superblock is stored in blocks 0/1 as a metadata pair with:
    - Name tag containing magic string "littlefs" (8 bytes)
    - Inline-struct tag with format parameters (all 32-bit little-endian)
    
    Args:
        fs_data: Raw filesystem image data (bytes or bytearray)
        
    Returns:
        dict: Filesystem parameters or None on error
        {
            'version_major': int,
            'version_minor': int,
            'block_size': int,
            'block_count': int,
            'name_max': int,
            'file_max': int,
            'attr_max': int,
        }
    """
    try:
        # Search for littlefs magic string in first two blocks (try common block sizes)
        for try_block_size in [4096, 512, 1024, 2048, 8192]:
            max_search = min(len(fs_data), try_block_size * 2)
            
            # Look for the magic string "littlefs"
            magic_offset = fs_data[:max_search].find(b'littlefs')
            if magic_offset == -1:
                continue
            
            # Found magic string, now parse the inline-struct tag that follows
            # The superblock inline-struct starts right after the name tag
            # Format: version(4) + block_size(4) + block_count(4) + name_max(4) + file_max(4) + attr_max(4)
            # Skip past magic string and look for inline-struct tag
            # LittleFS tags have a 4-byte header, then data
            # We need to find the inline-struct tag containing the superblock parameters
            # Typically the inline-struct follows the name tag
            
            # Try to parse starting from various offsets after the magic
            for struct_offset in [magic_offset + 8, magic_offset + 12, magic_offset + 16]:
                if struct_offset + 24 > len(fs_data):
                    continue
                
                try:
                    # Parse superblock fields (all 32-bit little-endian)
                    version = struct.unpack('<I', fs_data[struct_offset:struct_offset + 4])[0]
                    block_size = struct.unpack('<I', fs_data[struct_offset + 4:struct_offset + 8])[0]
                    block_count = struct.unpack('<I', fs_data[struct_offset + 8:struct_offset + 12])[0]
                    name_max = struct.unpack('<I', fs_data[struct_offset + 12:struct_offset + 16])[0]
                    file_max = struct.unpack('<I', fs_data[struct_offset + 16:struct_offset + 20])[0]
                    attr_max = struct.unpack('<I', fs_data[struct_offset + 20:struct_offset + 24])[0]
                    
                    # Validate that values are reasonable
                    version_major = (version >> 16) & 0xFFFF
                    version_minor = version & 0xFFFF
                    
                    # Sanity checks
                    if (block_size in [512, 1024, 2048, 4096, 8192, 16384] and
                        block_count > 0 and block_count < 0x10000000 and
                        name_max > 0 and name_max <= 1022 and
                        version_major > 0 and version_major <= 10):
                        
                        print("\nDetected LittleFS parameters from superblock:")
                        print(f"  Version: {version_major}.{version_minor}")
                        print(f"  Block size: {block_size} bytes")
                        print(f"  Block count: {block_count}")
                        print(f"  Max filename length: {name_max}")
                        print(f"  Max file size: {file_max}")
                        print(f"  Max attributes: {attr_max}")
                        
                        return {
                            'version_major': version_major,
                            'version_minor': version_minor,
                            'block_size': block_size,
                            'block_count': block_count,
                            'name_max': name_max,
                            'file_max': file_max,
                            'attr_max': attr_max,
                        }
                except struct.error:
                    continue
    
    except Exception as e:
        print(f"Warning: Failed to parse LittleFS superblock: {e}")
    
    return None


def _extract_littlefs(fs_file, fs_size, unpack_path, unpack_dir):
    """Extract LittleFS filesystem with auto-detected parameters."""
    # Read the downloaded filesystem image
    with open(fs_file, 'rb') as f:
        fs_data = f.read()

    # Try to auto-detect filesystem parameters from superblock
    superblock = _parse_littlefs_superblock(fs_data)
    
    if superblock:
        # Use detected parameters
        block_size = superblock['block_size']
        block_count = superblock['block_count']
        name_max = superblock['name_max']
        print("\nUsing auto-detected LittleFS parameters")
    else:
        # Fall back to defaults
        print(f"\nWarning: Could not auto-detect LittleFS parameters, using defaults")
        block_size = 0x1000  # 4KB default
        block_count = fs_size // block_size
        name_max = 64
        print(f"  Block size: {block_size} bytes (default)")
        print(f"  Block count: {block_count} (calculated)")
        print(f"  Max filename length: {name_max} (default)")

    # Create LittleFS instance and mount the image
    try:
        fs = LittleFS(
            block_size=block_size,
            block_count=block_count,
            name_max=name_max,
            mount=False
        )
        fs.context.buffer = bytearray(fs_data)
        fs.mount()
    except Exception as e:
        # If mount fails with detected parameters, try defaults
        if superblock:
            print(f"\nWarning: Mount failed with detected parameters: {e}")
            print("Retrying with default parameters...")
            block_size = 0x1000
            block_count = fs_size // block_size
            name_max = 64
            fs = LittleFS(
                block_size=block_size,
                block_count=block_count,
                name_max=name_max,
                mount=False
            )
            fs.context.buffer = bytearray(fs_data)
            fs.mount()
        else:
            raise

    # Extract all files
    file_count = 0
    print("\nExtracted files:")
    for root, dirs, files in fs.walk("/"):
        if not root.endswith("/"):
            root += "/"

        # Create directories
        for dir_name in dirs:
            src_path = root + dir_name
            dst_path = unpack_path / src_path[1:]  # Remove leading '/'
            dst_path.mkdir(parents=True, exist_ok=True)
            print(f"  [DIR]  {src_path}")

        # Extract files
        for file_name in files:
            src_path = root + file_name
            dst_path = unpack_path / src_path[1:]  # Remove leading '/'
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            with fs.open(src_path, "rb") as src:
                file_data = src.read()
                dst_path.write_bytes(file_data)

            print(f"  [FILE] {src_path} ({len(file_data)} bytes)")
            file_count += 1

    fs.unmount()
    print(f"\nSuccessfully extracted {file_count} file(s) to {unpack_dir}")
    return 0


def _parse_spiffs_config(fs_data, fs_size):
    """
    Auto-detect SPIFFS configuration from the image.
    Tries common configurations and validates against the image.
    
    Returns:
        dict: SPIFFS configuration parameters or None
    """
    # Common ESP32/ESP8266 SPIFFS configurations
    common_configs = [
        # ESP32/ESP8266 defaults
        {'page_size': 256, 'block_size': 4096, 'obj_name_len': 32},
        # Alternative configurations
        {'page_size': 256, 'block_size': 8192, 'obj_name_len': 32},
        {'page_size': 512, 'block_size': 4096, 'obj_name_len': 32},
        {'page_size': 256, 'block_size': 4096, 'obj_name_len': 64},
    ]
    
    print("\nAuto-detecting SPIFFS configuration...")
    
    for config in common_configs:
        try:
            # Try to parse with this configuration
            spiffs_build_config = SpiffsBuildConfig(
                page_size=config['page_size'],
                page_ix_len=2,
                block_size=config['block_size'],
                block_ix_len=2,
                meta_len=4,
                obj_name_len=config['obj_name_len'],
                obj_id_len=2,
                span_ix_len=2,
                packed=True,
                aligned=True,
                endianness='little',
                use_magic=True,
                use_magic_len=True,
                aligned_obj_ix_tables=False
            )
            
            # Try to create and parse the filesystem
            spiffs = SpiffsFS(fs_size, spiffs_build_config)
            spiffs.from_binary(fs_data)
            
            # If we got here without exception, this config works
            print("  Detected SPIFFS configuration:")
            print(f"    Page size: {config['page_size']} bytes")
            print(f"    Block size: {config['block_size']} bytes")
            print(f"    Max filename length: {config['obj_name_len']}")
            
            return {
                'page_size': config['page_size'],
                'block_size': config['block_size'],
                'obj_name_len': config['obj_name_len'],
                'meta_len': 4,
                'use_magic': True,
                'use_magic_len': True,
                'aligned_obj_ix_tables': False
            }
        except Exception:
            continue
    
    # If no config worked, return defaults
    print("  Could not auto-detect configuration, using ESP32/ESP8266 defaults")
    return {
        'page_size': 256,
        'block_size': 4096,
        'obj_name_len': 32,
        'meta_len': 4,
        'use_magic': True,
        'use_magic_len': True,
        'aligned_obj_ix_tables': False
    }


def _extract_spiffs(fs_file, fs_size, unpack_path, unpack_dir):
    """Extract SPIFFS filesystem with auto-detected configuration."""
    # Read the downloaded filesystem image
    with open(fs_file, 'rb') as f:
        fs_data = f.read()

    # Auto-detect SPIFFS configuration
    config = _parse_spiffs_config(fs_data, fs_size)
    
    # Create SPIFFS build configuration
    spiffs_build_config = SpiffsBuildConfig(
        page_size=config['page_size'],
        page_ix_len=2,
        block_size=config['block_size'],
        block_ix_len=2,
        meta_len=config['meta_len'],
        obj_name_len=config['obj_name_len'],
        obj_id_len=2,
        span_ix_len=2,
        packed=True,
        aligned=True,
        endianness='little',
        use_magic=config['use_magic'],
        use_magic_len=config['use_magic_len'],
        aligned_obj_ix_tables=config['aligned_obj_ix_tables']
    )

    # Create SPIFFS filesystem and parse the image
    spiffs = SpiffsFS(fs_size, spiffs_build_config)
    spiffs.from_binary(fs_data)

    # Extract files
    file_count = spiffs.extract_files(str(unpack_path))

    if file_count == 0:
        print("\nNo files were extracted.")
        print("The filesystem may be empty, freshly formatted, or contain only deleted entries.")
    else:
        print(f"\nSuccessfully extracted {file_count} file(s) to {unpack_dir}")

    return 0


def _extract_fatfs(fs_file, unpack_path, unpack_dir):
    """Extract FatFS filesystem."""
    # Read the downloaded filesystem image
    with open(fs_file, 'rb') as f:
        fs_data = bytearray(f.read())

    # Check if the image looks like a valid FAT filesystem
    if len(fs_data) < 512:
        print("Error: Downloaded image is too small to be a valid FAT filesystem")
        return 1
    
    # Try to detect and extract wear leveling layer
    sector_size = 4096  # Default ESP32 sector size
    
    # Check if this is a wear-leveling wrapped image
    if is_esp32_wl_image(fs_data, sector_size):
        print("Detected Wear Leveling layer, extracting FAT data...")
        fat_data = extract_fat_from_esp32_wl(fs_data, sector_size)
        if fat_data is None:
            print("Error: Failed to extract FAT data from wear-leveling image")
            return 1
        fs_data = bytearray(fat_data)
        print(f"  Extracted FAT data: {len(fs_data)} bytes")
    else:
        print("No Wear Leveling layer detected, treating as raw FAT image...")

    # Read sector size from FAT boot sector (offset 0x0B, 2 bytes, little-endian)
    sector_size = int.from_bytes(fs_data[0x0B:0x0D], byteorder='little')

    # Validate sector size
    if sector_size not in [512, 1024, 2048, 4096]:
        print(f"Error: Invalid sector size {sector_size}. Must be 512, 1024, 2048, or 4096")
        return 1

    # Mount with fatfs-python
    fs_size_adjusted = len(fs_data)
    sector_count = fs_size_adjusted // sector_size
    disk = RamDisk(fs_data, sector_size=sector_size, sector_count=sector_count)
    partition = create_extended_partition(disk)
    partition.mount()

    # Extract all files using PartitionExtended.walk() and read_file()
    print("Extracting files:\n")
    extracted_count = 0
    for root, _dirs, files in partition.walk("/"):
        # Create directories
        rel_root = root[1:] if root.startswith("/") else root
        abs_root = unpack_path / rel_root
        abs_root.mkdir(parents=True, exist_ok=True)
        for filename in files:
            src_file = root.rstrip("/") + "/" + filename if root != "/" else "/" + filename
            dst_file = abs_root / filename
            try:
                data = partition.read_file(src_file)
                dst_file.write_bytes(data)
                print(f"  FILE: {src_file} ({len(data)} bytes)")
                extracted_count += 1
            except Exception as e:
                print(f"  Warning: Failed to extract {src_file}: {e}")
    partition.unmount()
    
    # Summary
    if extracted_count == 0:
        print("\nNo files were extracted.")
        print("The filesystem may be empty, freshly formatted, or contain only deleted entries.")
    else:
        print(f"\nSuccessfully extracted {extracted_count} file(s) to {unpack_dir}")
    
    return 0


def download_fs_action(target, source, env):
    """Download and extract filesystem from device."""
    # Get unpack directory (use global env, not the parameter)
    unpack_dir = _get_unpack_dir(env)
    
    # Download partition image
    fs_file, _fs_start, fs_size, fs_subtype = _download_partition_image(env, None)
    
    if fs_file is None:
        return 1
    
    # Detect filesystem type
    fs_type = None
    if fs_subtype == 0x81:
        fs_type = "fatfs"
    elif fs_subtype == 0x82:
        with open(fs_file, 'rb') as f:
            header = f.read(8192)
            fs_type = "littlefs" if b'littlefs' in header else "spiffs"
    elif fs_subtype == 0x83:
        fs_type = "littlefs"
    else:
        print(f"Error: Unknown partition subtype 0x{fs_subtype:02X}")
        return 1
    
    print(f"\nDetected filesystem: {fs_type.upper()}")
    
    # Prepare unpack directory
    unpack_path = _prepare_unpack_dir(unpack_dir)
    
    # Extract filesystem
    try:
        if fs_type == "littlefs":
            return _extract_littlefs(fs_file, fs_size, unpack_path, unpack_dir)
        elif fs_type == "spiffs":
            return _extract_spiffs(fs_file, fs_size, unpack_path, unpack_dir)
        elif fs_type == "fatfs":
            return _extract_fatfs(fs_file, unpack_path, unpack_dir)
    except Exception as e:
        print(f"Error: {e}")
        return 1



#
# Target: Build executable and linkable firmware or FS image
#

target_elf = None
if "nobuild" in COMMAND_LINE_TARGETS:
    target_elf = str(Path("$BUILD_DIR") / "${PROGNAME}.elf")
    if set(["uploadfs", "uploadfsota"]) & set(COMMAND_LINE_TARGETS):
        fetch_fs_size(env)
        target_firm = str(Path("$BUILD_DIR") / "${ESP32_FS_IMAGE_NAME}.bin")
    else:
        target_firm = str(Path("$BUILD_DIR") / "${PROGNAME}.bin")
else:
    target_elf = env.BuildProgram()
    silent_action = env.Action(firmware_metrics)
    # Hack to silence scons command output
    silent_action.strfunction = lambda target, source, env: ""
    env.AddPostAction(target_elf, silent_action)
    if set(["buildfs", "uploadfs", "uploadfsota"]) & set(COMMAND_LINE_TARGETS):
        target_firm = env.DataToBin(
            str(Path("$BUILD_DIR") / "${ESP32_FS_IMAGE_NAME}"), "$PROJECT_DATA_DIR"
        )
        env.NoCache(target_firm)
        AlwaysBuild(target_firm)
    else:
        target_firm = env.ElfToBin(str(Path("$BUILD_DIR") / "${PROGNAME}"), target_elf)
        env.Depends(target_firm, "checkprogsize")

# Configure platform targets
env.AddPlatformTarget(
    "buildfs", target_firm, target_firm, "Build Filesystem Image"
)
AlwaysBuild(env.Alias("nobuild", target_firm))
target_buildprog = env.Alias("buildprog", target_firm, target_firm)

# Update max upload size based on CSV file
if env.get("PIOMAINPROG"):
    env.AddPreAction(
        "checkprogsize",
        env.VerboseAction(
            lambda source, target, env: _update_max_upload_size(env),
            "Retrieving maximum program size $SOURCES",
        ),
    )

# Target: Print binary size
target_size = env.AddPlatformTarget(
    "size",
    target_elf,
    env.VerboseAction("$SIZEPRINTCMD", "Calculating size $SOURCE"),
    "Program Size",
    "Calculate program size",
)

# Target: Upload firmware or FS image
upload_protocol = env.subst("$UPLOAD_PROTOCOL") or "esptool"
debug_tools = board.get("debug.tools", {})
upload_actions = []

# Compatibility with old OTA configurations
if upload_protocol != "espota" and re.match(
    r"\"?((([0-9]{1,3}\.){3}[0-9]{1,3})|[^\\/]+\.local)\"?$",
    env.get("UPLOAD_PORT", ""),
):
    upload_protocol = "espota"
    sys.stderr.write(
        "Warning! We have just detected `upload_port` as IP address or host "
        "name of ESP device. `upload_protocol` is switched to `espota`.\n"
        "Please specify `upload_protocol = espota` in `platformio.ini` "
        "project configuration file.\n"
    )

# Configure upload protocol: ESP OTA
if upload_protocol == "espota":
    if not env.subst("$UPLOAD_PORT"):
        sys.stderr.write(
            "Error: Please specify IP address or host name of ESP device "
            "using `upload_port` for build environment or use "
            "global `--upload-port` option.\n"
            "See https://docs.platformio.org/page/platforms/"
            "espressif32.html#over-the-air-ota-update\n"
        )
    env.Replace(
        UPLOADER=str(Path(framework_dir).resolve() / "tools" / "espota.py"),
        UPLOADERFLAGS=["--debug", "--progress", "-i", "$UPLOAD_PORT"],
        UPLOADCMD=f'"{PYTHON_EXE}" "$UPLOADER" $UPLOADERFLAGS -f $SOURCE',
    )
    if set(["uploadfs", "uploadfsota"]) & set(COMMAND_LINE_TARGETS):
        env.Append(UPLOADERFLAGS=["--spiffs"])
    upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]

# Configure upload protocol: esptool
elif upload_protocol == "esptool":
    env.Replace(
        UPLOADER=uploader_path,
        UPLOADERFLAGS=[
            "--chip",
            mcu,
            "--port",
            '"$UPLOAD_PORT"',
            "--baud",
            "$UPLOAD_SPEED",
            "--before",
            board.get("upload.before_reset", "default-reset"),
            "--after",
            board.get("upload.after_reset", "hard-reset"),
            "write-flash",
            "-z",
            "--flash-mode",
            "${__get_board_flash_mode(__env__)}",
            "--flash-freq",
            "${__get_board_f_image(__env__)}",
            "--flash-size",
            "detect",
        ],
        UPLOADCMD='$UPLOADER $UPLOADERFLAGS $ESP32_APP_OFFSET $SOURCE'
    )
    for image in env.get("FLASH_EXTRA_IMAGES", []):
        env.Append(UPLOADERFLAGS=[image[0], env.subst(image[1])])

    if "uploadfs" in COMMAND_LINE_TARGETS:
        env.Replace(
            UPLOADERFLAGS=[
                "--chip",
                mcu,
                "--port",
                '"$UPLOAD_PORT"',
                "--baud",
                "$UPLOAD_SPEED",
                "--before",
                board.get("upload.before_reset", "default-reset"),
                "--after",
                board.get("upload.after_reset", "hard-reset"),
                "write-flash",
                "-z",
                "--flash-mode",
                "${__get_board_flash_mode(__env__)}",
                "--flash-freq",
                "${__get_board_f_image(__env__)}",
                "--flash-size",
                "detect",
                "$FS_START",
            ],
            UPLOADCMD='$UPLOADER $UPLOADERFLAGS $SOURCE',
        )

    upload_actions = [
        env.VerboseAction(BeforeUpload, "Looking for upload port..."),
        env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE"),
    ]

# Configure upload protocol: DFU
elif upload_protocol == "dfu":
    hwids = board.get("build.hwids", [["0x2341", "0x0070"]])
    vid = hwids[0][0]
    pid = hwids[0][1]

    upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]

    env.Replace(
        UPLOADER=str(
            Path(platform.get_package_dir("tool-dfuutil-arduino")).resolve() / "dfu-util"
        ),
        UPLOADERFLAGS=[
            "-d",
            ",".join(["%s:%s" % (hwid[0], hwid[1]) for hwid in hwids]),
            "-Q",
            "-D",
        ],
        UPLOADCMD='"$UPLOADER" $UPLOADERFLAGS "$SOURCE"',
    )

# Configure upload protocol: Debug tools (OpenOCD)
elif upload_protocol in debug_tools:
    _parse_partitions(env)
    openocd_args = ["-d%d" % (2 if int(ARGUMENTS.get("PIOVERBOSE", 0)) else 1)]
    openocd_args.extend(
        debug_tools.get(upload_protocol).get("server").get("arguments", [])
    )
    openocd_args.extend(
        [
            "-c",
            "adapter speed %s" % env.GetProjectOption("debug_speed", "5000"),
            "-c",
            "program_esp {{$SOURCE}} %s verify"
            % (
                "$FS_START"
                if "uploadfs" in COMMAND_LINE_TARGETS
                else env.get("INTEGRATION_EXTRA_DATA").get("application_offset")
            ),
        ]
    )
    if "uploadfs" not in COMMAND_LINE_TARGETS:
        for image in env.get("FLASH_EXTRA_IMAGES", []):
            openocd_args.extend(
                [
                    "-c",
                    "program_esp {{%s}} %s verify"
                    % (_to_unix_slashes(image[1]), image[0]),
                ]
            )
    openocd_args.extend(["-c", "reset run; shutdown"])
    openocd_args = [
        f.replace(
            "$PACKAGE_DIR",
            _to_unix_slashes(
                platform.get_package_dir("tool-openocd-esp32") or ""
            ),
        )
        for f in openocd_args
    ]
    env.Replace(
        UPLOADER="openocd",
        UPLOADERFLAGS=openocd_args,
        UPLOADCMD="$UPLOADER $UPLOADERFLAGS",
    )
    upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]

# Configure upload protocol: Custom
elif upload_protocol == "custom":
    upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]

else:
    sys.stderr.write("Warning! Unknown upload protocol %s\n" % upload_protocol)

# Register upload targets
env.AddPlatformTarget("upload", target_firm, upload_actions, "Upload")
env.AddPlatformTarget(
    "uploadfs", target_firm, upload_actions, "Upload Filesystem Image"
)
env.AddPlatformTarget(
    "uploadfsota",
    target_firm,
    upload_actions,
    "Upload Filesystem Image OTA",
)

# Target: Download Filesystem (auto-detect type)
env.AddPlatformTarget(
    "download_fs",
    None,
    [
        env.VerboseAction(BeforeUpload, "Looking for upload port..."),
        env.VerboseAction(download_fs_action, "Downloading and extracting filesystem")
    ],
    "Download and extract filesystem from device",
)

# Target: Erase Flash and Upload
env.AddPlatformTarget(
    "erase_upload",
    target_firm,
    [
        env.VerboseAction(BeforeUpload, "Looking for upload port..."),
        env.VerboseAction("$ERASECMD", "Erasing..."),
        env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE"),
    ],
    "Erase Flash and Upload",
)

# Target: Erase Flash
env.AddPlatformTarget(
    "erase",
    None,
    [
        env.VerboseAction(BeforeUpload, "Looking for upload port..."),
        env.VerboseAction("$ERASECMD", "Erasing..."),
    ],
    "Erase Flash",
)

# Register Custom Target for firmware metrics
env.AddCustomTarget(
    name="metrics",
    dependencies="$BUILD_DIR/${PROGNAME}.elf",
    actions=firmware_metrics,
    title="Firmware Size Metrics",
    description="Analyze firmware size using esp-idf-size "
    "(supports CLI args after --)",
    always_build=True,
)

# Additional Target without Build-Dependency when already compiled
env.AddCustomTarget(
    name="metrics-only",
    dependencies=None,
    actions=firmware_metrics,
    title="Firmware Size Metrics (No Build)",
    description="Analyze firmware size without building first",
    always_build=True,
)

# Register Custom Target for coredump analysis
env.AddCustomTarget(
    name="coredump",
    dependencies="$BUILD_DIR/${PROGNAME}.elf",
    actions=coredump_analysis,
    title="Coredump Analysis",
    description="Analyze coredumps using esp-coredump "
    "(supports CLI args after --)",
    always_build=True,
)

# Additional Target without Build-Dependency when already compiled
env.AddCustomTarget(
    name="coredump-only",
    dependencies=None,
    actions=coredump_analysis,
    title="Coredump Analysis (No Build)",
    description="Analyze coredumps without building first",
    always_build=True,
)

# Override memory inspection behavior
env.SConscript("sizedata.py", exports="env")

# Set default targets
Default([target_buildprog, target_size])
