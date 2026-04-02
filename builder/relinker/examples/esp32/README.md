# Relinker Configuration for ESP32 (Classic)

This directory contains relinker configuration files for the original ESP32 chip.

## Overview

The ESP32 is the original Xtensa LX6-based dual-core chip with 520 KB of SRAM. It features WiFi and Bluetooth Classic + BLE. Despite having more total SRAM than newer chips, the relinker helps optimize IRAM usage due to technical limitations in static DRAM allocation.

## Key Features

- **Dual-core Xtensa LX6**: 2x 240 MHz processors (600 MIPS total)
- **WiFi**: 802.11 b/g/n support (2.4 GHz)
- **Bluetooth**: Classic BR/EDR + BLE 4.2
- **520 KB SRAM**: 320 KB DRAM + 200 KB IRAM (after cache)
- **Technical limitation**: Maximum 160 KB statically allocated DRAM
- **Rich peripherals**: Ethernet MAC, CAN, Hall sensor, touch sensors

## Files

- `library.csv` - Maps library names to their filesystem paths (23 libraries)
- `object.csv` - Maps object files within libraries to their build artifact paths (62 objects)
- `function.csv` - Lists 335 functions that can be safely moved from IRAM to Flash

## Usage

Add these lines to your `platformio.ini`:

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = espidf

; Relinker configuration for ESP32
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32/function.csv
```

Or copy the files to your project and reference them locally:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/esp32/*.csv relinker/
```

Then in `platformio.ini`:

```ini
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

## Configuration Details

The configuration includes functions from:

- **Bluetooth** - Classic BR/EDR and BLE controller functions
- **WiFi** - WiFi adapter and protocol functions
- **FreeRTOS** - Task management, queue, and scheduler functions (Xtensa dual-core port)
- **Heap** - Memory allocation functions
- **Newlib** - Standard C library functions (malloc, free, locks)
- **ESP System** - System initialization and management
- **ESP Timer** - Timer and time management functions (LAC timer implementation)
- **SPI Flash** - Flash operation functions
- **Power Management** - Sleep and power management functions
- **Hardware Support** - Clock, interrupt, and peripheral control
- **Xtensa** - Xtensa-specific interrupt and exception handling

## Differences from Newer Chips

The ESP32 Classic differs from newer chips:

- **Dual-core**: Uses dual-core FreeRTOS port (no port_systick.c.obj)
- **Xtensa LX6**: Older Xtensa architecture
- **Bluetooth Classic**: Uses `libbtdm_app.a` instead of BLE-only libraries
- **LAC timer**: Uses `esp_timer_impl_lac.c.obj` instead of systimer
- **No systimer ROM patches**: Different ROM patch files
- **Legacy architecture**: First generation ESP32

## Memory Specifications

- **SRAM**: 520 KB total (320 KB DRAM + 200 KB IRAM)
- **ROM**: 448 KB
- **Flash**: External (typically 4 MB)
- **Architecture**: Xtensa LX6 dual-core @ 240 MHz
- **Cache**: Two-way set associative
- **Static DRAM limit**: 160 KB (technical limitation)

## Notes

- All functions listed have been validated to be safe to run from Flash
- Functions that must stay in IRAM (ISRs, flash operations) are excluded
- Some functions are conditionally moved based on sdkconfig options
- The configuration is based on ESP-IDF framework structure
- ESP32 uses Xtensa architecture with dual-core support
- Despite having more total SRAM, static allocation limits make optimization valuable

## Testing

After enabling the relinker, verify your application works correctly:

1. Build and flash your application
2. Test all functionality, especially:
   - WiFi operations
   - Bluetooth Classic and BLE operations
   - Dual-core operations
   - Interrupt handlers
   - Flash read/write operations
   - Sleep/wake cycles
   - Ethernet operations (if used)

If you encounter crashes, you may need to adjust the function list for your specific use case.

## References

See `RELINKER_INTEGRATION.md` in the platform root for detailed documentation.
