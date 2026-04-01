# Relinker Configuration for Arduino Framework

This directory contains relinker configuration files for the Arduino framework on ESP32 chips.

## Overview

The Arduino framework for ESP32 uses pre-compiled libraries from the ESP-IDF. The relinker helps optimize IRAM usage by moving selected functions from IRAM to Flash, which is especially important for memory-constrained chips like the ESP32-C2.

## Key Differences from ESP-IDF Framework

When using Arduino framework, the relinker works differently:

- **Pre-compiled libraries**: Arduino uses pre-built libraries from `framework-arduinoespressif32-libs`
- **Static sections.ld**: The linker script is located in `framework-arduinoespressif32-libs/<mcu>/ld/sections.ld`
- **Build directory**: The relinker creates a modified copy in your project's build directory
- **No ldgen**: Arduino doesn't run ldgen during build, so the sections.ld is used as-is

## Chip-Specific Configurations

Each ESP32 chip variant has its own configuration directory:

- `esp32/` - Original ESP32 (Xtensa LX6 dual-core)
- `esp32c2/` - ESP32-C2 (RISC-V, 32KB IRAM)
- `esp32c3/` - ESP32-C3 (RISC-V single-core)
- `esp32c6/` - ESP32-C6 (RISC-V with WiFi 6)
- `esp32h2/` - ESP32-H2 (RISC-V, Zigbee/Thread)
- `esp32s2/` - ESP32-S2 (Xtensa LX7 single-core)
- `esp32s3/` - ESP32-S3 (Xtensa LX7 dual-core)

## Usage

### Quick Start

Add these lines to your `platformio.ini`:

```ini
[env:myboard]
platform = espressif32
board = esp32-c2-devkitm-1
framework = arduino

; Relinker configuration
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/arduino/esp32c2/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/arduino/esp32c2/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/arduino/esp32c2/function.csv
```

Replace `esp32c2` with your chip variant (esp32, esp32c3, esp32c6, esp32h2, esp32s2, esp32s3).

### Custom Configuration

To customize the configuration for your project:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/arduino/<chip>/*.csv relinker/
```

Then in `platformio.ini`:

```ini
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

## Configuration Files

### library.csv

Maps library names to their filesystem paths in the Arduino framework:

```csv
library,path
libfreertos.a,$ARDUINO_LIBS_DIR/libfreertos.a
libheap.a,$ARDUINO_LIBS_DIR/libheap.a
```

The `$ARDUINO_LIBS_DIR` variable is automatically expanded to the correct path for your chip.

### object.csv

Maps object files within libraries to their paths. For Arduino, these paths point to the pre-compiled objects:

```csv
library,object,path
libfreertos.a,tasks.c.obj,$ARDUINO_LIBS_DIR/libfreertos.a
libheap.a,heap_caps.c.obj,$ARDUINO_LIBS_DIR/libheap.a
```

### function.csv

Lists functions to relocate from IRAM to Flash:

```csv
library,object,function,option
libfreertos.a,tasks.c.obj,xTaskGetCurrentTaskHandle,
libheap.a,heap_caps.c.obj,heap_caps_malloc,
```

## Important Notes

1. **Arduino-specific paths**: The CSV files use `$ARDUINO_LIBS_DIR` which expands to the correct library directory for your chip
2. **Pre-compiled libraries**: You cannot modify the source code, only relocate existing functions
3. **Testing required**: Always test thoroughly after enabling the relinker, especially interrupt handlers and flash operations
4. **Chip-specific**: Each chip has different memory constraints and library configurations

## Troubleshooting

### Build Error: Library not found

The library path in `library.csv` is incorrect. Verify the path:

```bash
ls ~/.platformio/packages/framework-arduinoespressif32-libs/esp32c2/lib/
```

### Runtime Crash

A function was moved to flash that gets called during flash operations or from ISR. Remove it from `function.csv` or set its option to `FALSE`.

### No IRAM savings

The functions listed may not be in IRAM in the first place. Check the original `sections.ld` file to see which functions are actually in IRAM.

## References

- See `RELINKER_INTEGRATION.md` in the platform root for detailed documentation
- Arduino ESP32 documentation: https://docs.espressif.com/projects/arduino-esp32/
- ESP-IDF documentation: https://docs.espressif.com/projects/esp-idf/

