# Relinker Configuration for ESP32-C6

This directory contains relinker configuration files for the ESP32-C6 chip.

## Overview

The ESP32-C6 is a RISC-V based chip with 512 KB of SRAM. It features WiFi 6 (802.11ax), Bluetooth 5.3, and IEEE 802.15.4 (Thread/Zigbee) connectivity. The relinker helps optimize IRAM usage by moving non-critical functions from IRAM to Flash.

## Key Features

- **RISC-V 32-bit**: Single-core processor @ 160 MHz
- **WiFi 6**: 802.11ax support (2.4 GHz)
- **Bluetooth 5.3**: BLE with LE Audio, Mesh, Long Range
- **IEEE 802.15.4**: Thread and Zigbee protocol support
- **512 KB SRAM**: More memory than C3, but optimization still beneficial
- **Rich peripherals**: USB Serial/JTAG, TWAI, ADC, etc.

## Files

- `library.csv` - Maps library names to their filesystem paths (23 libraries)
- `object.csv` - Maps object files within libraries to their build artifact paths (65 objects)
- `function.csv` - Lists 364 functions that can be safely moved from IRAM to Flash

## Usage

Add these lines to your `platformio.ini`:

```ini
[env:esp32c6]
platform = espressif32
board = esp32c6-devkitc-1
framework = espidf

; Relinker configuration for ESP32-C6
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c6/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c6/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c6/function.csv
```

Or copy the files to your project and reference them locally:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/esp32c6/*.csv relinker/
```

Then in `platformio.ini`:

```ini
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

## Configuration Details

The configuration includes functions from:

- **BLE/Bluetooth** - BLE 5.3 controller and NimBLE stack functions
- **WiFi 6** - WiFi 6 adapter and protocol functions
- **FreeRTOS** - Task management, queue, and scheduler functions
- **Heap** - Memory allocation functions
- **Newlib** - Standard C library functions (malloc, free, locks)
- **ESP System** - System initialization and management
- **ESP Timer** - Timer and time management functions
- **SPI Flash** - Flash operation functions
- **Power Management** - Sleep and power management functions
- **Hardware Support** - Clock, interrupt, and peripheral control

## Differences from ESP32-C3

The ESP32-C6 is similar to ESP32-C3 but with enhancements:

- **More SRAM**: 512 KB vs 400 KB
- **WiFi 6**: 802.11ax instead of 802.11n
- **Bluetooth 5.3**: Enhanced BLE features (LE Audio, etc.)
- **IEEE 802.15.4**: Additional Thread/Zigbee support
- **Same RISC-V architecture**: Compatible function list

## Memory Specifications

- **SRAM**: 512 KB total
- **ROM**: 320 KB
- **Flash**: External (typically 4-8 MB)
- **Architecture**: RISC-V 32-bit single-core @ 160 MHz

## Notes

- All functions listed have been validated to be safe to run from Flash
- Functions that must stay in IRAM (ISRs, flash operations) are excluded
- Some functions are conditionally moved based on sdkconfig options
- The configuration is based on ESP-IDF framework structure
- ESP32-C6 uses RISC-V architecture like C3

## Testing

After enabling the relinker, verify your application works correctly:

1. Build and flash your application
2. Test all functionality, especially:
   - WiFi 6 operations
   - BLE 5.3 operations
   - IEEE 802.15.4 operations (Thread/Zigbee)
   - Interrupt handlers
   - Flash read/write operations
   - Sleep/wake cycles

If you encounter crashes, you may need to adjust the function list for your specific use case.

## References

See `RELINKER_INTEGRATION.md` in the platform root for detailed documentation.
