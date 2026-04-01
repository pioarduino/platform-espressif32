# Arduino Relinker Example for ESP32-C2

This example demonstrates the Arduino Relinker integration for ESP32-C2, showing how to optimize IRAM usage by moving selected functions from IRAM to Flash.

## Overview

The ESP32-C2 has only 32KB of IRAM available for user code, making IRAM optimization critical for complex applications. The relinker automatically moves non-critical functions from IRAM to Flash, freeing up precious IRAM for interrupt handlers and other time-critical code.

## What This Example Does

This example demonstrates:

1. **FreeRTOS Functions**: Shows how FreeRTOS task management functions are relocated to Flash
2. **Memory Allocation**: Demonstrates that memory allocation functions work correctly after relocation
3. **Queue Operations**: Shows queue send/receive operations working from Flash
4. **Logging**: Demonstrates logging functions relocated to Flash
5. **System Monitoring**: Displays memory and system information

## Functions Relocated by Relinker

The following functions are moved from IRAM to Flash in this example:

### FreeRTOS Functions
- `xTaskGetCurrentTaskHandle()`
- `xTaskGetSchedulerState()`
- `xTaskGetTickCount()`
- `xTaskGetIdleTaskHandle()`
- `uxTaskGetNumberOfTasks()`
- `pcTaskGetName()`
- `xQueueReceive()`
- `xQueueSend()`
- `xQueueGenericSend()`

### Memory Functions
- `malloc()`, `free()`, `realloc()`, `calloc()`
- `heap_caps_malloc()`, `heap_caps_free()`
- `heap_caps_realloc()`, `heap_caps_calloc()`
- `_lock_acquire()`, `_lock_release()`

### Logging Functions
- `esp_log_write()`
- `esp_log_writev()`

## Hardware Requirements

- ESP32-C2 development board (e.g., ESP32-C2-DevKitM-1)
- USB cable for programming and serial monitor

## Software Requirements

- PlatformIO
- Espressif32 platform with Arduino framework
- Relinker integration (included in platform)

## Building and Running

### 1. Build the project

```bash
pio run -e esp32-c2-devkitm-1
```

During the build, you should see:

```text
*** Arduino Relinker configured for esp32c2 ***
Running relinker to optimize IRAM usage
```

### 2. Upload to board

```bash
pio run -e esp32-c2-devkitm-1 -t upload
```

### 3. Monitor serial output

```bash
pio device monitor -e esp32-c2-devkitm-1
```

## Expected Output

```text
=== Arduino Relinker Example ===
ESP32-C2 IRAM Optimization Demo
================================

Free Heap: 45000 bytes
Heap Size: 50000 bytes
Chip Model: ESP32-C2
Chip Revision: 1
CPU Frequency: 120 MHz
Flash Size: 2097152 bytes

Relinker Benefits:
- FreeRTOS functions moved to Flash
- Memory allocation functions moved to Flash
- Logging functions moved to Flash
- More IRAM available for critical code

Background task created
Monitoring system...

Task: 0x3fcxxxxx, Ticks: 1000, Tasks: 3
Memory allocation successful
[5000] Main loop iteration 0
Free Heap: 44800 bytes
Queue created
Value sent to queue
Value received from queue: 0
```

## Customizing the Configuration

To customize which functions are relocated:

### 1. Copy the configuration files

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/arduino/<chip>/*.csv relinker/
```

### 2. Update platformio.ini

```ini
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

### 3. Edit function.csv

Add or remove functions as needed. See `ARDUINO_RELINKER_INTEGRATION.md` for details.

## Troubleshooting

### Build fails with "sections.ld not found"

Make sure the Arduino framework is properly installed:
```bash
pio pkg install -p espressif32
```

### Runtime crash after enabling relinker

A function that must stay in IRAM was relocated. Check the crash backtrace and remove that function from `function.csv` or set its option to `FALSE`.

### No IRAM savings observed

The functions listed may already be in Flash. Check the memory map:
```bash
cat .pio/build/esp32-c2-devkitm-1/firmware.map | grep -A 50 ".iram0.text"
```

## Memory Comparison

### Without Relinker
- IRAM usage: ~28KB
- Available IRAM: ~4KB

### With Relinker
- IRAM usage: ~20KB
- Available IRAM: ~12KB
- **Savings: ~8KB IRAM**

## References

- [ARDUINO_RELINKER_INTEGRATION.md](../../ARDUINO_RELINKER_INTEGRATION.md) - Complete Arduino relinker documentation
- [RELINKER_INTEGRATION.md](../../RELINKER_INTEGRATION.md) - General relinker documentation
- [ESP32-C2 Datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-c2_datasheet_en.pdf)

## License

This example is provided under the same license as the PlatformIO Espressif32 platform.
