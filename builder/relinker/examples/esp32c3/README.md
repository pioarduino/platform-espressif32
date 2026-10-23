# Relinker Configuration for ESP32-C3

This directory contains relinker configuration files for the ESP32-C3 chip.

## Overview

The ESP32-C3 is a RISC-V based chip with 400 KB of SRAM (including IRAM). While it has more IRAM than the ESP32-C2 (32 KB), the relinker can still be beneficial for applications that need to maximize available IRAM by moving non-critical functions from IRAM to Flash.

## Files

- `library.csv` - Maps library names to their filesystem paths
- `object.csv` - Maps object files within libraries to their build artifact paths  
- `function.csv` - Lists 365 functions that can be safely moved from IRAM to Flash

## Usage

Add these lines to your `platformio.ini`:

```ini
[env:esp32c3]
platform = espressif32
board = esp32-c3-devkitm-1
framework = espidf

; Relinker configuration for ESP32-C3
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c3/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c3/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c3/function.csv
```

Or copy the files to your project and reference them locally:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/esp32c3/*.csv relinker/
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
- **WiFi** - WiFi adapter and protocol functions
- **FreeRTOS** - Task management, queue, and scheduler functions
- **Heap** - Memory allocation functions
- **Newlib** - Standard C library functions (malloc, free, locks)
- **ESP System** - System initialization and management
- **ESP Timer** - Timer and time management functions
- **SPI Flash** - Flash operation functions
- **Power Management** - Sleep and power management functions
- **Hardware Support** - Clock, interrupt, and peripheral control

## Notes

- All functions listed have been validated to be safe to run from Flash
- Functions that must stay in IRAM (ISRs, flash operations) are excluded
- Some functions are conditionally moved based on sdkconfig options
- The configuration is based on ESP-IDF framework structure

## Testing

After enabling the relinker, verify your application works correctly:

1. Build and flash your application
2. Test all functionality, especially:
   - WiFi/BLE operations
   - Interrupt handlers
   - Flash read/write operations
   - Sleep/wake cycles

If you encounter crashes, you may need to adjust the function list for your specific use case.

## References

See `RELINKER_INTEGRATION.md` in the platform root for detailed documentation.
