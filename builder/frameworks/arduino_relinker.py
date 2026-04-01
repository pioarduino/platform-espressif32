"""
Arduino Framework Relinker Integration

This module provides relinker support for the Arduino framework on ESP32.
Unlike ESP-IDF which generates sections.ld during build, Arduino uses
pre-compiled libraries with a static sections.ld file.
"""

import os
import sys
import shutil
from pathlib import Path
from SCons.Script import DefaultEnvironment


def setup_arduino_relinker(env, platform, mcu, chip_variant):
    """
    Setup relinker for Arduino framework builds.
    
    Args:
        env: SCons environment
        platform: PlatformIO platform object
        mcu: MCU type (esp32, esp32c2, etc.)
        chip_variant: Chip variant name
    
    Returns:
        True if relinker was configured, False otherwise
    """
    config = env.GetProjectConfig()
    pioenv = env["PIOENV"]
    project_dir = env.subst("$PROJECT_DIR")
    build_dir = env.subst("$BUILD_DIR")
    
    # Get relinker configuration from platformio.ini
    relinker_function = config.get("env:" + pioenv, "custom_relinker_function", "")
    relinker_library = config.get("env:" + pioenv, "custom_relinker_library", "")
    relinker_object = config.get("env:" + pioenv, "custom_relinker_object", "")
    
    # Validate that all three relinker settings are provided together
    relinker_settings = {
        "custom_relinker_function": relinker_function,
        "custom_relinker_library": relinker_library,
        "custom_relinker_object": relinker_object,
    }
    relinker_set = [key for key, value in relinker_settings.items() if value]
    relinker_missing = [key for key, value in relinker_settings.items() if not value]
    
    if relinker_set and relinker_missing:
        # Some but not all settings are provided - this is an error
        sys.stderr.write(
            "Error: Incomplete relinker configuration in [env:%s]\n"
            "All three custom_relinker_* settings must be provided together:\n"
            "  - Set: %s\n"
            "  - Missing: %s\n"
            "Either provide all three settings or remove all of them.\n"
            % (pioenv, ", ".join(relinker_set), ", ".join(relinker_missing))
        )
        env.Exit(1)
    
    if not (relinker_function and relinker_library and relinker_object):
        # Relinker not configured
        return False
    
    print(f"*** Configuring Arduino Relinker for {chip_variant} ***")
    
    # Get Arduino framework paths
    framework_dir = platform.get_package_dir("framework-arduinoespressif32")
    framework_lib_dir = platform.get_package_dir("framework-arduinoespressif32-libs")
    
    if not framework_dir or not framework_lib_dir:
        sys.stderr.write("Error: Arduino framework packages not found\n")
        env.Exit(1)
    
    # Path to the original sections.ld in Arduino framework
    arduino_libs_dir = str(Path(framework_dir) / "tools" / "esp32-arduino-libs" / chip_variant)
    original_sections_ld = str(Path(arduino_libs_dir) / "ld" / "sections.ld")
    
    # Recover from interrupted previous builds - restore stale backup if exists
    backup_path = f"{original_sections_ld}.{mcu}.backup"
    if os.path.exists(backup_path):
        print(f"Restoring sections.ld from previous interrupted build...")
        shutil.copy2(backup_path, original_sections_ld)
        os.remove(backup_path)
    
    if not os.path.exists(original_sections_ld):
        sys.stderr.write(
            f"Error: sections.ld not found at {original_sections_ld}\n"
            f"Chip variant: {chip_variant}\n"
        )
        env.Exit(1)
    
    # Copy original sections.ld to build directory
    build_sections_ld = str(Path(build_dir) / "sections.ld")
    os.makedirs(build_dir, exist_ok=True)
    shutil.copy2(original_sections_ld, build_sections_ld)
    
    # Normalize relinker CSV paths to absolute paths relative to PROJECT_DIR
    _relinker_library = relinker_library if os.path.isabs(relinker_library) else str(Path(project_dir) / relinker_library)
    _relinker_object = relinker_object if os.path.isabs(relinker_object) else str(Path(project_dir) / relinker_object)
    _relinker_function = relinker_function if os.path.isabs(relinker_function) else str(Path(project_dir) / relinker_function)
    
    # Verify CSV files exist
    for csv_file, csv_name in [
        (_relinker_library, "library"),
        (_relinker_object, "object"),
        (_relinker_function, "function")
    ]:
        if not os.path.exists(csv_file):
            sys.stderr.write(
                f"Error: Relinker {csv_name} CSV file not found: {csv_file}\n"
            )
            env.Exit(1)
    
    # Process CSV files to expand $ARDUINO_LIBS_DIR variable
    arduino_lib_path = str(Path(framework_lib_dir) / chip_variant / "lib")
    _process_arduino_csv_files(
        _relinker_library,
        _relinker_object,
        _relinker_function,
        arduino_lib_path,
        build_dir
    )
    
    # Update paths to processed CSV files
    _relinker_library = str(Path(build_dir) / "relinker_library.csv")
    _relinker_object = str(Path(build_dir) / "relinker_object.csv")
    _relinker_function = str(Path(build_dir) / "relinker_function.csv")
    
    # Get relinker script and configuration
    _relinker_dir = str(Path(platform.get_dir()) / "builder" / "relinker")
    
    # Get objdump tool via toolchain package directory (same pattern as espidf.py)
    toolchain_dir = platform.get_package_dir(
        "toolchain-xtensa-esp-elf"
        if mcu in ("esp32", "esp32s2", "esp32s3")
        else "toolchain-riscv32-esp"
    )
    if toolchain_dir and os.path.isdir(toolchain_dir):
        _relinker_objdump = str(Path(toolchain_dir) / "bin" / env.subst("$CC").replace("-gcc", "-objdump"))
    else:
        _relinker_objdump = env.subst("$CC").replace("-gcc", "-objdump")
    
    # Create a minimal sdkconfig for Arduino (Arduino doesn't use sdkconfig)
    arduino_sdkconfig = str(Path(build_dir) / "sdkconfig.arduino")
    _create_arduino_sdkconfig(arduino_sdkconfig, mcu)
    
    # Get missing function info setting
    _relinker_missing_raw = config.get(
        "env:" + pioenv, "custom_relinker_missing_function_info", "no"
    ).strip().lower()
    
    # Validate the value
    valid_true_values = ("yes", "true", "1")
    valid_false_values = ("no", "false", "0")
    if _relinker_missing_raw not in valid_true_values and _relinker_missing_raw not in valid_false_values:
        sys.stderr.write(
            f"Warning: Invalid value '{_relinker_missing_raw}' for custom_relinker_missing_function_info. "
            f"Valid values are: {', '.join(valid_true_values + valid_false_values)}. "
            f"Defaulting to 'no'.\n"
        )
        _relinker_missing_raw = "no"
    
    _relinker_missing = _relinker_missing_raw in valid_true_values
    
    # Run relinker immediately (not as a build command)
    # This ensures the modified sections.ld is ready before pioarduino-build.py runs
    print("Running relinker to optimize IRAM usage...")
    
    try:
        # Import and run relinker directly
        sys.path.insert(0, _relinker_dir)
        from relinker import run_relinker
        
        run_relinker(
            input_file=build_sections_ld,
            output_file=build_sections_ld,
            library_file=_relinker_library,
            object_file=_relinker_object,
            function_file=_relinker_function,
            sdkconfig_file=arduino_sdkconfig,
            objdump=_relinker_objdump,
            idf_path=None,  # Not needed for Arduino
            missing_function_info=_relinker_missing,
            debug=False
        )
        
        print(f"Relinker completed successfully for {chip_variant}")
        
        # Now we need to make sure the Arduino build uses our modified sections.ld
        # We do this by replacing the original sections.ld in the framework directory
        # with our modified version (backup/restore is handled by component_manager)
        
        # Import component_manager to use its backup functionality
        # Ensure frameworks directory is in path for component_manager import
        _frameworks_dir = str(Path(__file__).parent)
        if _frameworks_dir not in sys.path:
            sys.path.insert(0, _frameworks_dir)
        from component_manager import ComponentManager
        component_manager = ComponentManager(env)
        
        # Create backup of the original sections.ld
        component_manager.backup_manager.backup_sections_ld(original_sections_ld)
        
        # Replace the original with our modified version
        shutil.copy2(build_sections_ld, original_sections_ld)
        
        print(f"Replaced sections.ld with relinked version for {chip_variant}")
        
        # Register restore action after build completes (same as pioarduino-build.py)
        def restore_sections_ld_wrapper(target, source, env):
            component_manager.backup_manager.restore_sections_ld(original_sections_ld, target, source, env)
        
        silent_action = env.Action(restore_sections_ld_wrapper)
        silent_action.strfunction = lambda target, source, env: ''
        env.AddPostAction("checkprogsize", silent_action)
        
        return True
        
    except Exception as e:
        sys.stderr.write(f"Error running relinker: {e}\n")
        import traceback
        traceback.print_exc()
        env.Exit(1)


def _process_arduino_csv_files(library_csv, object_csv, function_csv, arduino_lib_path, build_dir):
    """
    Process CSV files to expand $ARDUINO_LIBS_DIR variable.
    
    Args:
        library_csv: Path to library CSV file
        object_csv: Path to object CSV file
        function_csv: Path to function CSV file
        arduino_lib_path: Path to Arduino libraries directory
        build_dir: Build directory path
    """
    import csv
    
    # Process library.csv
    output_library_csv = str(Path(build_dir) / "relinker_library.csv")
    with open(library_csv, 'r', encoding='utf-8') as infile, \
         open(output_library_csv, 'w', encoding='utf-8', newline='') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row['path'] = row['path'].replace('$ARDUINO_LIBS_DIR', arduino_lib_path)
            writer.writerow(row)
    
    # Process object.csv
    output_object_csv = str(Path(build_dir) / "relinker_object.csv")
    with open(object_csv, 'r', encoding='utf-8') as infile, \
         open(output_object_csv, 'w', encoding='utf-8', newline='') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row['path'] = row['path'].replace('$ARDUINO_LIBS_DIR', arduino_lib_path)
            writer.writerow(row)
    
    # Copy function.csv as-is (no path expansion needed)
    output_function_csv = str(Path(build_dir) / "relinker_function.csv")
    shutil.copy2(function_csv, output_function_csv)


def _create_arduino_sdkconfig(sdkconfig_path, mcu):
    """
    Create a minimal sdkconfig file for Arduino framework.
    
    Arduino doesn't use sdkconfig, but the relinker needs it for
    conditional function relocation. We create a minimal one with
    common Arduino defaults.
    
    Args:
        sdkconfig_path: Path where sdkconfig should be created
        mcu: MCU type
    """
    # Common Arduino configuration options
    # Only emit keys with =y; the sdkconfig parser treats any present key as enabled,
    # so =n entries must be omitted entirely (absence = disabled).
    config_lines = [
        "# Minimal sdkconfig for Arduino framework",
        "# Generated by PlatformIO relinker integration",
        "",
        "CONFIG_FREERTOS_HZ=1000",
        "CONFIG_ESP_SYSTEM_PANIC_PRINT_REBOOT=y",
        "CONFIG_ESP_CONSOLE_UART_DEFAULT=y",
    ]
    
    # Single-core MCUs need CONFIG_FREERTOS_UNICORE=y
    # Dual-core MCUs (esp32, esp32s3) must NOT have the key at all
    single_core_mcus = ("esp32s2", "esp32c2", "esp32c3", "esp32c6", "esp32h2")
    
    # MCU-specific options
    if mcu == "esp32":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32=y",
        ])
    elif mcu == "esp32s2":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32S2=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ])
    elif mcu == "esp32s3":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32S3=y",
        ])
    elif mcu == "esp32c2":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32C2=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ])
    elif mcu == "esp32c3":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32C3=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ])
    elif mcu == "esp32c6":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32C6=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ])
    elif mcu == "esp32h2":
        config_lines.extend([
            "CONFIG_IDF_TARGET_ESP32H2=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ])
    
    with open(sdkconfig_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(config_lines))
        f.write('\n')
