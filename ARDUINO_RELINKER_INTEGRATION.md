# Arduino Framework Relinker Integration

## Overview

The relinker is now available for the Arduino framework on ESP32 chips. This integration allows moving functions from IRAM to Flash, freeing up valuable IRAM memory - especially important for memory-constrained chips like the ESP32-C2.

## Differences from ESP-IDF Integration

The Arduino framework integration differs in several important ways from the ESP-IDF integration:

### ESP-IDF Framework
- Generates `sections.ld` during build with `ldgen`
- Uses CMake build system
- Full access to source code and build configuration
- Relinker modifies the generated `sections.ld` before linking

### Arduino Framework
- Uses pre-compiled libraries from `framework-arduinoespressif32-libs`
- Static `sections.ld` file in framework directory
- No `ldgen` during build
- Relinker copies and modifies the static `sections.ld` in build directory

## Quick Start

### 1. Identify Chip Variant

Determine your ESP32 chip variant:
- `esp32` - Original ESP32 (Xtensa LX6 dual-core)
- `esp32c2` - ESP32-C2 (RISC-V, 32KB IRAM)
- `esp32c3` - ESP32-C3 (RISC-V single-core)
- `esp32c6` - ESP32-C6 (RISC-V mit WiFi 6)
- `esp32h2` - ESP32-H2 (RISC-V, Zigbee/Thread)
- `esp32s2` - ESP32-S2 (Xtensa LX7 single-core)
- `esp32s3` - ESP32-S3 (Xtensa LX7 dual-core)

### 2. Configure platformio.ini

Add the relinker configuration to your `platformio.ini`:

```ini
[env:myboard]
platform = espressif32
board = esp32-c2-devkitm-1
framework = arduino

; Relinker configuration for ESP32-C2
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/arduino/esp32c2/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/arduino/esp32c2/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/arduino/esp32c2/function.csv

; Optional: Warnings instead of errors for missing functions
; custom_relinker_missing_function_info = yes
```

Replace `esp32c2` with your chip variant.

### 3. Build

```bash
pio run -e myboard
```

Während des Builds sehen Sie:

```text
*** Arduino Relinker configured for esp32c2 ***
Running relinker to optimize IRAM usage
```

## Available Chip Configurations

Pre-configured examples are available for:

| Chip | Path | Description |
|------|------|-------------|
| ESP32 | `builder/relinker/examples/arduino/esp32/` | Original ESP32, Xtensa dual-core |
| ESP32-C2 | `builder/relinker/examples/arduino/esp32c2/` | RISC-V, 32KB IRAM |
| ESP32-C3 | `builder/relinker/examples/arduino/esp32c3/` | RISC-V single-core |
| ESP32-C6 | `builder/relinker/examples/arduino/esp32c6/` | RISC-V with WiFi 6 |
| ESP32-H2 | `builder/relinker/examples/arduino/esp32h2/` | RISC-V, Zigbee/Thread |
| ESP32-S2 | `builder/relinker/examples/arduino/esp32s2/` | Xtensa single-core |
| ESP32-S3 | `builder/relinker/examples/arduino/esp32s3/` | Xtensa dual-core |

## Creating Custom Configuration

### 1. Copy Example Configuration

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/arduino/esp32c2/*.csv relinker/
```

### 2. Update platformio.ini

```ini
[env:myboard]
platform = espressif32
board = esp32-c2-devkitm-1
framework = arduino

; Local relinker configuration
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

### 3. Customize CSV Files

#### library.csv

Defines libraries and their paths:

```csv
library,path
libfreertos.a,$ARDUINO_LIBS_DIR/libfreertos.a
libheap.a,$ARDUINO_LIBS_DIR/libheap.a
```

The `$ARDUINO_LIBS_DIR` variable is automatically expanded to the correct path:
```
~/.platformio/packages/framework-arduinoespressif32-libs/<chip>/lib/
```

#### object.csv

Defines object files within libraries:

```csv
library,object,path
libfreertos.a,tasks.c.obj,$ARDUINO_LIBS_DIR/libfreertos.a
libheap.a,heap_caps.c.obj,$ARDUINO_LIBS_DIR/libheap.a
```

For Arduino, all paths point to the `.a` archive file since object files are contained within.

#### function.csv

Defines functions to be moved from IRAM to Flash:

```csv
library,object,function,option
libfreertos.a,tasks.c.obj,xTaskGetCurrentTaskHandle,
libfreertos.a,tasks.c.obj,xTaskGetSchedulerState,
libheap.a,heap_caps.c.obj,heap_caps_malloc,
```

The `option` column can be empty or contain conditions:
- Empty: Function is always moved
- `CONFIG_XYZ`: Only move if CONFIG_XYZ is defined
- `!CONFIG_XYZ`: Only move if CONFIG_XYZ is NOT defined
- `FALSE`: Function is NEVER moved (stays in IRAM)

## Selecting Functions

### Functions That MUST Stay in IRAM

These functions must NOT be moved to Flash:

- ISRs and functions called from ISRs
- SPI Flash operations (`spi_flash_*`)
- Functions that run before Flash cache initialization
- FreeRTOS scheduler-critical functions
- Cache error handlers
- RTC/Sleep functions
- Functions with `IRAM_ATTR` attribute in source code

### Functions That CAN Be Moved to Flash

- Initialization functions (called once at startup)
- Logging functions (unless used in ISR context)
- Memory management (if not used in ISR)
- Non-critical library functions
- Configuration/setup routines

### Identifying Candidates

1. **Check Memory Map**: After build, examine `.pio/build/<env>/firmware.map` file

2. **Use objdump**:
   ```bash
   # For RISC-V Chips (C2, C3, C6, H2)
   riscv32-esp-elf-objdump -h ~/.platformio/packages/framework-arduinoespressif32-libs/esp32c2/lib/libfreertos.a
   
   # For Xtensa Chips (ESP32, S2, S3)
   xtensa-esp32-elf-objdump -h ~/.platformio/packages/framework-arduinoespressif32-libs/esp32/lib/libfreertos.a
   ```

3. **Use Example Configurations**: The included examples contain already validated functions

## Configuration Options

| Option | Required | Description |
|--------|----------|-------------|
| `custom_relinker_library` | Yes | Path to library.csv file |
| `custom_relinker_object` | Yes | Path to object.csv file |
| `custom_relinker_function` | Yes | Path to function.csv file |
| `custom_relinker_missing_function_info` | No | Warnings instead of errors for missing functions. Values: `yes`, `true`, `1` (enabled) or `no`, `false`, `0` (disabled, default) |

**Important**: All three CSV options must be provided together. If only some are set, the build will fail with an error message.

### When to Use `custom_relinker_missing_function_info`

This option is useful when:
- Working with CSV files across different ESP-IDF versions
- Function names or locations may have changed
- Using a shared relinker configuration
- Developing/testing new configurations

Beispiel:
```ini
custom_relinker_missing_function_info = yes
```

## Troubleshooting

### Build Error: "sections.ld not found"

The `sections.ld` file was not found in the Arduino framework. Check:
- Framework is correctly installed
- Chip variant is correct
- Path: `~/.platformio/packages/framework-arduinoespressif32/tools/esp32-arduino-libs/<chip>/ld/sections.ld`

### Build Error: "Library not found"

The library path in `library.csv` is incorrect. Check:
```bash
ls ~/.platformio/packages/framework-arduinoespressif32-libs/<chip>/lib/
```

### Build Error: "Failed to get sections from lib"

The library doesn't exist or the path is incorrect. Ensure `$ARDUINO_LIBS_DIR` is used correctly.

### Build Error: "function failed to find section"

The function doesn't exist in the specified object file. Check with:
```bash
# RISC-V
riscv32-esp-elf-objdump -t ~/.platformio/packages/framework-arduinoespressif32-libs/esp32c2/lib/libfreertos.a | grep xTaskGetTickCount

# Xtensa
xtensa-esp32-elf-objdump -t ~/.platformio/packages/framework-arduinoespressif32-libs/esp32/lib/libfreertos.a | grep xTaskGetTickCount
```

### Runtime Crash (LoadProhibited / InstrFetchProhibited)

A function was moved to Flash that gets called during Flash operations or from an ISR. Solution:
- Remove function from `function.csv`, or
- Set option to `FALSE` (stays in IRAM)

### No IRAM Savings

The listed functions may not be in IRAM. Check the original `sections.ld`:
```bash
cat ~/.platformio/packages/framework-arduinoespressif32/tools/esp32-arduino-libs/<chip>/ld/sections.ld | grep -A 50 ".iram0.text"
```

### Relinker Not Running

Verify that all three options are set:
```ini
custom_relinker_library  = ...
custom_relinker_object   = ...
custom_relinker_function = ...
```

## Advanced Usage

### Wildcard Patterns

For pre-compiled blob libraries, you can use wildcard patterns:

```csv
library,object,function,option
libpp.a,pp.o,.text.*,
libpp.a,trc.o,.wifi0iram.*,
```

Available wildcards:
- `.text.*` - All text sections
- `.iram1.*` - All IRAM1 sections
- `.wifi0iram.*` - WiFi IRAM sections
- `.wifirxiram.*` - WiFi RX IRAM sections

### Conditional Relocation

Functions can be moved based on configuration options:

```csv
library,object,function,option
libfreertos.a,tasks.c.obj,xTaskGetCurrentTaskHandle,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libheap.a,heap_caps.c.obj,heap_caps_malloc,!CONFIG_HEAP_PLACE_FUNCTION_INTO_FLASH
```

**Note**: Arduino doesn't use `sdkconfig`, so these options are treated as undefined by default. The relinker creates a minimal `sdkconfig` with Arduino default values.

## Example Project

Complete example for ESP32-C2:

### Project Structure
```
my_arduino_project/
├── platformio.ini
├── src/
│   └── main.cpp
└── relinker/
    ├── library.csv
    ├── object.csv
    └── function.csv
```

### platformio.ini
```ini
[env:esp32c2]
platform = espressif32
board = esp32-c2-devkitm-1
framework = arduino
monitor_speed = 115200

; Relinker: Move functions from IRAM to Flash
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

### src/main.cpp
```cpp
#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  Serial.println("Arduino Relinker Test");
  Serial.printf("Free IRAM: %d bytes\n", ESP.getFreeHeap());
}

void loop() {
  delay(1000);
}
```

## Technical Details

### How It Works

1. **Build Start**: Arduino build system starts
2. **Relinker Detection**: `arduino_relinker.py` checks for relinker configuration
3. **Copy sections.ld**: Original `sections.ld` is copied to build directory
4. **CSV Processing**: `$ARDUINO_LIBS_DIR` is expanded to actual path
5. **Run Relinker**: `relinker.py` modifies the `sections.ld`
6. **Linking**: Modified `sections.ld` is used for linking

### Path Expansion

The `$ARDUINO_LIBS_DIR` variable is expanded to:
```
~/.platformio/packages/framework-arduinoespressif32-libs/<chip>/lib/
```

Example for ESP32-C2:
```
/Users/username/.platformio/packages/framework-arduinoespressif32-libs/esp32c2/lib/
```

### Minimal sdkconfig

Since Arduino doesn't use `sdkconfig`, the relinker creates a minimal version with:
- `CONFIG_FREERTOS_UNICORE` (chip-dependent)
- `CONFIG_FREERTOS_HZ=1000`
- `CONFIG_IDF_TARGET_<CHIP>=y`
- Additional Arduino default values

## Comparison: ESP-IDF vs Arduino

| Aspect | ESP-IDF | Arduino |
|--------|---------|---------|
| Linker Script | Generated with ldgen | Statically pre-compiled |
| Libraries | Source code available | Pre-compiled |
| Build System | CMake | PlatformIO/Arduino |
| sdkconfig | Complete | Minimal (generated) |
| Customizability | High | Medium |
| Simplicity | Medium | High |

## Best Practices

1. **Start Small**: Begin with example configurations
2. **Test Incrementally**: Move a few functions at a time
3. **Test Thoroughly**: Test all functionality, especially:
   - WiFi operations
   - Bluetooth operations
   - Interrupt handlers
   - Flash read/write operations
   - Sleep/wake cycles
4. **Check Memory Map**: Review IRAM savings in the `.map` file
5. **Document**: Note which functions you moved and why

## References

- [RELINKER_INTEGRATION.md](RELINKER_INTEGRATION.md) - Complete relinker documentation
- [Arduino ESP32 Documentation](https://docs.espressif.com/projects/arduino-esp32/)
- [ESP-IDF Documentation](https://docs.espressif.com/projects/esp-idf/)
- [Espressif cmake_utilities](https://github.com/espressif/cmake_utilities) - Original relinker

## Credits

The relinker was originally developed by Espressif Systems as part of the [cmake_utilities](https://github.com/espressif/cmake_utilities) project and has been adapted for seamless integration with PlatformIO and the Arduino framework.
