# Relinker Configuration for ESP32-S2

This directory contains relinker configuration files for the ESP32-S2 chip.

## Overview

The ESP32-S2 is an Xtensa LX7-based single-core chip with 320 KB of SRAM. It features WiFi but no Bluetooth capability. The relinker helps optimize IRAM usage by moving non-critical functions from IRAM to Flash.

## Key Features

- **Single-core Xtensa LX7**: 240 MHz processor
- **WiFi only**: 802.11 b/g/n support, no Bluetooth
- **320 KB SRAM**: ~160 KB available IRAM
- **USB OTG**: Native USB support
- **Rich peripherals**: Touch sensors, temperature sensor, ADC/DAC

## Files

- `library.csv` - Maps library names to their filesystem paths (21 libraries)
- `object.csv` - Maps object files within libraries to their build artifact paths (61 objects)
- `function.csv` - Lists 281 functions that can be safely moved from IRAM to Flash

## Usage

Add these lines to your `platformio.ini`:

```ini
[env:esp32s2]
platform = espressif32
board = esp32s2-devkitm-1
framework = espidf

; Relinker configuration for ESP32-S2
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32s2/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32s2/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32s2/function.csv
```

Or copy the files to your project and reference them locally:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/esp32s2/*.csv relinker/
```

Then in `platformio.ini`:

```ini
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

## Configuration Details

The configuration includes functions from:

- **WiFi** - WiFi adapter and protocol functions
- **FreeRTOS** - Task management, queue, and scheduler functions (Xtensa port)
- **Heap** - Memory allocation functions
- **Newlib** - Standard C library functions (malloc, free, locks)
- **ESP System** - System initialization and management
- **ESP Timer** - Timer and time management functions
- **Power Management** - Sleep and power management functions
- **Hardware Support** - Clock, interrupt, and peripheral control
- **Xtensa** - Xtensa-specific interrupt and exception handling

## Differences from ESP32-C3

The ESP32-S2 configuration differs from ESP32-C3 in the following ways:

- **No Bluetooth**: All BLE/Bluetooth functions excluded
- **Xtensa architecture**: Uses Xtensa port instead of RISC-V
- **Additional library**: `libxtensa.a` for Xtensa-specific functions
- **Different FreeRTOS port**: Uses `portable/xtensa/port.c.obj` instead of RISC-V
- **Fewer functions**: 281 functions vs 364 for ESP32-C3

## Memory Specifications

- **SRAM**: 320 KB total
- **ROM**: 128 KB
- **Flash**: External (typically 2-4 MB)
- **Architecture**: Xtensa LX7 single-core @ 240 MHz
- **Cache**: Four-way set associative, independent instruction and data cache

## Notes

- All functions listed have been validated to be safe to run from Flash
- Functions that must stay in IRAM (ISRs, flash operations) are excluded
- Some functions are conditionally moved based on sdkconfig options
- The configuration is based on ESP-IDF framework structure
- ESP32-S2 uses Xtensa architecture, not RISC-V

## Testing

After enabling the relinker, verify your application works correctly:

1. Build and flash your application
2. Test all functionality, especially:
   - WiFi operations
   - USB operations
   - Touch sensor operations
   - Interrupt handlers
   - Flash read/write operations
   - Sleep/wake cycles

If you encounter crashes, you may need to adjust the function list for your specific use case.

## References

See `RELINKER_INTEGRATION.md` in the platform root for detailed documentation.
