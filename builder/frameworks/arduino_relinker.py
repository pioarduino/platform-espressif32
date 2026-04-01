"""
Arduino Framework Relinker Integration

This module provides relinker support for the Arduino framework on ESP32.
Unlike ESP-IDF which generates sections.ld during build, Arduino uses
pre-compiled libraries with a static sections.ld file.

The relinked linker script is written into $BUILD_DIR/sections.ld and the
build directory is prepended to LIBPATH so the linker picks it up before the
package-owned copy.  The shared framework package is never modified.
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

    # ------------------------------------------------------------------
    # Recover from interrupted previous builds that may have left
    # a stale backup of the package-owned sections.ld (from older
    # versions of this integration that replaced the file in-place).
    # This block runs unconditionally so the framework is always
    # restored even when the relinker is later disabled.
    # ------------------------------------------------------------------
    framework_lib_dir = platform.get_package_dir(
        "framework-arduinoespressif32-libs"
    )
    if framework_lib_dir:
        _original_ld = str(
            Path(framework_lib_dir) / chip_variant / "ld" / "sections.ld"
        )
        _stale_backup = f"{_original_ld}.{mcu}.backup"
        if os.path.exists(_stale_backup):
            print("Restoring sections.ld from previous interrupted build...")
            shutil.copy2(_stale_backup, _original_ld)
            os.remove(_stale_backup)

    # ------------------------------------------------------------------
    # Read and validate relinker configuration from platformio.ini
    # ------------------------------------------------------------------
    relinker_function = config.get(
        "env:" + pioenv, "custom_relinker_function", ""
    )
    relinker_library = config.get(
        "env:" + pioenv, "custom_relinker_library", ""
    )
    relinker_object = config.get(
        "env:" + pioenv, "custom_relinker_object", ""
    )

    relinker_settings = {
        "custom_relinker_function": relinker_function,
        "custom_relinker_library": relinker_library,
        "custom_relinker_object": relinker_object,
    }
    relinker_set = [k for k, v in relinker_settings.items() if v]
    relinker_missing = [k for k, v in relinker_settings.items() if not v]

    if relinker_set and relinker_missing:
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
        return False

    print(f"*** Configuring Arduino Relinker for {chip_variant} ***")

    # ------------------------------------------------------------------
    # Resolve framework paths
    # ------------------------------------------------------------------
    framework_dir = platform.get_package_dir("framework-arduinoespressif32")
    idf_framework_dir = platform.get_package_dir("framework-espidf")

    if not framework_dir or not framework_lib_dir:
        sys.stderr.write("Error: Arduino framework packages not found\n")
        env.Exit(1)

    # sections.ld lives in the -libs package at <chip>/ld/sections.ld
    original_sections_ld = str(
        Path(framework_lib_dir) / chip_variant / "ld" / "sections.ld"
    )

    if not os.path.exists(original_sections_ld):
        sys.stderr.write(
            f"Error: sections.ld not found at {original_sections_ld}\n"
            f"Chip variant: {chip_variant}\n"
        )
        env.Exit(1)

    # ------------------------------------------------------------------
    # Copy the original linker script into $BUILD_DIR and relink there.
    # The package-owned file is never modified.
    # ------------------------------------------------------------------
    build_sections_ld = str(Path(build_dir) / "sections.ld")
    os.makedirs(build_dir, exist_ok=True)
    shutil.copy2(original_sections_ld, build_sections_ld)

    # Prepend $BUILD_DIR to LIBPATH so the linker resolves
    # "-T sections.ld" from our relinked copy before the package copy.
    env.Prepend(LIBPATH=[build_dir])

    # ------------------------------------------------------------------
    # Normalise CSV paths to absolute paths relative to PROJECT_DIR
    # ------------------------------------------------------------------
    _relinker_library = (
        relinker_library
        if os.path.isabs(relinker_library)
        else str(Path(project_dir) / relinker_library)
    )
    _relinker_object = (
        relinker_object
        if os.path.isabs(relinker_object)
        else str(Path(project_dir) / relinker_object)
    )
    _relinker_function = (
        relinker_function
        if os.path.isabs(relinker_function)
        else str(Path(project_dir) / relinker_function)
    )

    for csv_file, csv_name in [
        (_relinker_library, "library"),
        (_relinker_object, "object"),
        (_relinker_function, "function"),
    ]:
        if not os.path.exists(csv_file):
            sys.stderr.write(
                f"Error: Relinker {csv_name} CSV file not found: {csv_file}\n"
            )
            env.Exit(1)

    # ------------------------------------------------------------------
    # Expand $ARDUINO_LIBS_DIR in CSV files
    # ------------------------------------------------------------------
    arduino_lib_path = str(Path(framework_lib_dir) / chip_variant / "lib")
    _process_arduino_csv_files(
        _relinker_library,
        _relinker_object,
        _relinker_function,
        arduino_lib_path,
        build_dir,
    )

    _relinker_library = str(Path(build_dir) / "relinker_library.csv")
    _relinker_object = str(Path(build_dir) / "relinker_object.csv")
    _relinker_function = str(Path(build_dir) / "relinker_function.csv")

    # ------------------------------------------------------------------
    # Resolve objdump via the toolchain package (same as espidf.py)
    # ------------------------------------------------------------------
    _relinker_dir = str(Path(platform.get_dir()) / "builder" / "relinker")

    toolchain_dir = platform.get_package_dir(
        "toolchain-xtensa-esp-elf"
        if mcu in ("esp32", "esp32s2", "esp32s3")
        else "toolchain-riscv32-esp"
    )
    if toolchain_dir and os.path.isdir(toolchain_dir):
        _relinker_objdump = str(
            Path(toolchain_dir)
            / "bin"
            / env.subst("$CC").replace("-gcc", "-objdump")
        )
    else:
        _relinker_objdump = env.subst("$CC").replace("-gcc", "-objdump")

    # ------------------------------------------------------------------
    # Create a minimal sdkconfig for Arduino
    # ------------------------------------------------------------------
    arduino_sdkconfig = str(Path(build_dir) / "sdkconfig.arduino")
    _create_arduino_sdkconfig(arduino_sdkconfig, mcu)

    # ------------------------------------------------------------------
    # Parse missing-function-info setting
    # ------------------------------------------------------------------
    _relinker_missing_raw = (
        config.get(
            "env:" + pioenv, "custom_relinker_missing_function_info", "no"
        )
        .strip()
        .lower()
    )

    valid_true_values = ("yes", "true", "1")
    valid_false_values = ("no", "false", "0")
    if (
        _relinker_missing_raw not in valid_true_values
        and _relinker_missing_raw not in valid_false_values
    ):
        sys.stderr.write(
            f"Warning: Invalid value '{_relinker_missing_raw}' for "
            f"custom_relinker_missing_function_info. "
            f"Valid values are: {', '.join(valid_true_values + valid_false_values)}. "
            f"Defaulting to 'no'.\n"
        )
        _relinker_missing_raw = "no"

    _relinker_missing = _relinker_missing_raw in valid_true_values

    # ------------------------------------------------------------------
    # Run the relinker on the build-local copy of sections.ld
    # ------------------------------------------------------------------
    print("Running relinker to optimize IRAM usage...")

    try:
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
            idf_path=idf_framework_dir or None,
            missing_function_info=_relinker_missing,
            debug=False,
        )

        print(f"Relinker completed successfully for {chip_variant}")
        return True

    except Exception as e:
        sys.stderr.write(f"Error running relinker: {e}\n")
        import traceback

        traceback.print_exc()
        env.Exit(1)


def _process_arduino_csv_files(
    library_csv, object_csv, function_csv, arduino_lib_path, build_dir
):
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
    with open(library_csv, "r", encoding="utf-8") as infile, open(
        output_library_csv, "w", encoding="utf-8", newline=""
    ) as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row["path"] = row["path"].replace(
                "$ARDUINO_LIBS_DIR", arduino_lib_path
            )
            writer.writerow(row)

    # Process object.csv
    output_object_csv = str(Path(build_dir) / "relinker_object.csv")
    with open(object_csv, "r", encoding="utf-8") as infile, open(
        output_object_csv, "w", encoding="utf-8", newline=""
    ) as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row["path"] = row["path"].replace(
                "$ARDUINO_LIBS_DIR", arduino_lib_path
            )
            writer.writerow(row)

    # Copy function.csv as-is (no path expansion needed)
    output_function_csv = str(Path(build_dir) / "relinker_function.csv")
    shutil.copy2(function_csv, output_function_csv)


def _create_arduino_sdkconfig(sdkconfig_path, mcu):
    """
    Create a minimal sdkconfig file for Arduino framework.

    Arduino doesn't use sdkconfig, but the relinker needs it for
    conditional function relocation.  We create a minimal one with
    common Arduino defaults.

    Only keys that should be *enabled* are emitted (with ``=y``).
    The sdkconfig parser in ``configuration.py`` treats any present
    key as enabled regardless of its value, so disabled booleans
    must be omitted entirely.

    Args:
        sdkconfig_path: Path where sdkconfig should be created
        mcu: MCU type
    """
    config_lines = [
        "# Minimal sdkconfig for Arduino framework",
        "# Generated by PlatformIO relinker integration",
        "",
        "CONFIG_FREERTOS_HZ=1000",
        "CONFIG_ESP_SYSTEM_PANIC_PRINT_REBOOT=y",
        "CONFIG_ESP_CONSOLE_UART_DEFAULT=y",
    ]

    # MCU-specific options.
    # Single-core MCUs get CONFIG_FREERTOS_UNICORE=y;
    # dual-core MCUs (esp32, esp32s3) omit the key entirely.
    mcu_configs = {
        "esp32": ["CONFIG_IDF_TARGET_ESP32=y"],
        "esp32s2": [
            "CONFIG_IDF_TARGET_ESP32S2=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ],
        "esp32s3": ["CONFIG_IDF_TARGET_ESP32S3=y"],
        "esp32c2": [
            "CONFIG_IDF_TARGET_ESP32C2=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ],
        "esp32c3": [
            "CONFIG_IDF_TARGET_ESP32C3=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ],
        "esp32c6": [
            "CONFIG_IDF_TARGET_ESP32C6=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ],
        "esp32h2": [
            "CONFIG_IDF_TARGET_ESP32H2=y",
            "CONFIG_FREERTOS_UNICORE=y",
        ],
    }

    config_lines.extend(mcu_configs.get(mcu, []))

    with open(sdkconfig_path, "w", encoding="utf-8") as f:
        f.write("\n".join(config_lines))
        f.write("\n")
