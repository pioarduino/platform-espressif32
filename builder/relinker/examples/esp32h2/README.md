# Relinker Configuration for ESP32-H2

This directory contains relinker configuration files for the ESP32-H2 chip.

## Overview

The ESP32-H2 is a RISC-V-based chip designed for Bluetooth LE and IEEE 802.15.4 (Thread/Zigbee) connectivity. It has 320 KB of SRAM (including IRAM). The relinker helps optimize IRAM usage by moving non-critical functions from IRAM to Flash.

## Key Features

- **No WiFi**: ESP32-H2 does not have WiFi capability, so WiFi-related functions are excluded
- **Bluetooth LE**: Full BLE 5.2 support with optimized IRAM usage
- **IEEE 802.15.4**: Thread and Zigbee protocol support
- **RISC-V**: 32-bit RISC-V single-core processor

## Files

- `library.csv` - Maps library names to their filesystem paths (21 libraries)
- `object.csv` - Maps object files within libraries to their build artifact paths (64 objects)
- `function.csv` - Lists 336 functions that can be safely moved from IRAM to Flash

## Usage

Add these lines to your `platformio.ini`:

```ini
[env:esp32h2]
platform = espressif32
board = esp32h2-devkitm-1
framework = espidf

; Relinker configuration for ESP32-H2
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32h2/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32h2/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32h2/function.csv
```

Or copy the files to your project and reference them locally:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/esp32h2/*.csv relinker/
```

Then in `platformio.ini`:

```ini
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

## Configuration Details

The configuration includes functions from:

- **BLE/Bluetooth** - BLE controller and NimBLE stack functions
- **FreeRTOS** - Task management, queue, and scheduler functions
- **Heap** - Memory allocation functions
- **Newlib** - Standard C library functions (malloc, free, locks)
- **ESP System** - System initialization and management
- **ESP Timer** - Timer and time management functions
- **SPI Flash** - Flash operation functions
- **Power Management** - Sleep and power management functions
- **Hardware Support** - Clock, interrupt, and peripheral control

## Differences from ESP32-C3

The ESP32-H2 configuration differs from ESP32-C3 in the following ways:

- **No WiFi libraries**: `libesp_wifi.a` and `libpp.a` are excluded
- **Different BT library path**: Uses `lib_esp32h2/esp32h2-bt-lib/libble_app.a`
- **Chip-specific paths**: All hardware-specific paths use `esp32h2` instead of `esp32c3`
- **Fewer functions**: 336 functions vs 364 for ESP32-C3 (WiFi functions removed)

## Memory Specifications

- **SRAM**: 320 KB total
- **ROM**: 128 KB
- **Flash**: External (typically 2-4 MB)
- **Architecture**: RISC-V 32-bit single-core @ 96 MHz

## Notes

- All functions listed have been validated to be safe to run from Flash
- Functions that must stay in IRAM (ISRs, flash operations) are excluded
- Some functions are conditionally moved based on sdkconfig options
- The configuration is based on ESP-IDF framework structure

## Testing

After enabling the relinker, verify your application works correctly:

1. Build and flash your application
2. Test all functionality, especially:
   - BLE operations
   - IEEE 802.15.4 operations (Thread/Zigbee)
   - Interrupt handlers
   - Flash read/write operations
   - Sleep/wake cycles

If you encounter crashes, you may need to adjust the function list for your specific use case.

## References

See `RELINKER_INTEGRATION.md` in the platform root for detailed documentation.
