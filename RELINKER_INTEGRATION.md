# Relinker Integration for PlatformIO ESP32

## Overview

The **Relinker** is a linker-script post-processing tool originally developed by Espressif
(`espressif/cmake_utilities`). It selectively moves functions from **IRAM** (Internal RAM)
to **Flash**, freeing up precious IRAM on memory-constrained chips like the **ESP32-C2**
(which has only 32 KB of IRAM available for user code).

The relinker modifies the generated `sections.ld` linker script after `ldgen` has produced
it, but before the final ELF is linked. Functions that are safe to run from flash (i.e.,
they are not called from ISR context, during flash operations, or before the flash cache is
enabled) are relocated from `.iram1` sections to `.flash.text`, while functions that *must*
remain in IRAM stay there.

### How It Works

```text
┌──────────────┐     ┌────────────┐     ┌──────────────┐     ┌──────────┐
│ sections.ld  │────▶│   ldgen    │────▶│ sections.ld  │────▶│ relinker │
│   template   │     │ (ESP-IDF)  │     │ (generated)  │     │          │
└──────────────┘     └────────────┘     └──────────────┘     └─────┬────┘
                                                                   │
                                         ┌──────────────┐         │
                                         │ sections.ld  │◀────────┘
                                         │ (optimized)  │
                                         └──────┬───────┘
                                                │
                                         ┌──────▼───────┐
                                         │   Linker     │
                                         │  (ld / gcc)  │
                                         └──────────────┘
```

The relinker reads three CSV configuration files that define:

1. **Which libraries** are involved and where to find them
2. **Which object files** within those libraries are affected
3. **Which functions** should be relocated from IRAM to flash

---

## Quick Start: ESP32-C2 Example

### 1. Prepare the CSV Configuration Files

Create a `relinker/` directory in your PlatformIO project root and add three CSV files.
A ready-to-use ESP32-C2 example is included in the platform at:

```text
~/.platformio/platforms/espressif32/builder/relinker/examples/esp32c2/
```

You can copy these files as a starting point:

```bash
mkdir -p relinker
cp ~/.platformio/platforms/espressif32/builder/relinker/examples/esp32c2/*.csv relinker/
```

### 2. Configure `platformio.ini`

Add the three `custom_relinker_*` options to your build environment:

```ini
[env:esp32c2]
platform  = espressif32
board     = esp32-c2-devkitm-1
framework = espidf

; --- Relinker Configuration ---
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

### 3. Build

```bash
pio run -e esp32c2
```

During the build you will see an additional step in the output:

```text
Running relinker to optimize IRAM usage
```

That's it. The linker script is automatically patched before the final firmware is linked.

---

## CSV File Reference

### `library.csv` — Library Paths

Maps library archive names to their filesystem paths. Paths are relative to the
build directory (`$BUILD_DIR`) or absolute. The `$IDF_PATH` variable is expanded
automatically.

| Column    | Description                                          |
|-----------|------------------------------------------------------|
| `library` | Archive name (e.g. `libfreertos.a`)                  |
| `path`    | Path to the `.a` file, relative to build dir or `$IDF_PATH` |

**Example (`library.csv`):**

```csv
library,path
libble_app.a,$IDF_PATH/components/bt/controller/lib_esp32c2/esp32c2-bt-lib/libble_app.a
libpp.a,$IDF_PATH/components/esp_wifi/lib/esp32c2/libpp.a
libfreertos.a,./esp-idf/freertos/libfreertos.a
libheap.a,./esp-idf/heap/libheap.a
libnewlib.a,./esp-idf/newlib/libnewlib.a
libesp_hw_support.a,./esp-idf/esp_hw_support/libesp_hw_support.a
libesp_system.a,./esp-idf/esp_system/libesp_system.a
libesp_timer.a,./esp-idf/esp_timer/libesp_timer.a
libspi_flash.a,./esp-idf/spi_flash/libspi_flash.a
liblog.a,./esp-idf/log/liblog.a
```

> **Note:** Relative paths (starting with `./`) are resolved relative to the PlatformIO
> build output directory (`$BUILD_DIR`, typically `.pio/build/<env>/`).

---

### `object.csv` — Object File Paths

Maps individual object files within each library to their build artifact paths. This
allows the relinker to run `objdump` on specific object files to discover their sections.

| Column    | Description                                            |
|-----------|--------------------------------------------------------|
| `library` | Archive name (must match an entry in `library.csv`)    |
| `object`  | Object file name (e.g. `tasks.c.obj`)                  |
| `path`    | Path to the `.obj` file, relative to build dir or `$IDF_PATH` |

**Example (`object.csv`):**

```csv
library,object,path
libfreertos.a,tasks.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/FreeRTOS-Kernel/tasks.c.obj
libfreertos.a,queue.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/FreeRTOS-Kernel/queue.c.obj
libfreertos.a,list.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/FreeRTOS-Kernel/list.c.obj
libfreertos.a,port.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/FreeRTOS-Kernel/portable/riscv/port.c.obj
libheap.a,heap_caps.c.obj,esp-idf/heap/CMakeFiles/__idf_heap.dir/heap_caps.c.obj
libnewlib.a,locks.c.obj,esp-idf/newlib/CMakeFiles/__idf_newlib.dir/locks.c.obj
libnewlib.a,heap.c.obj,esp-idf/newlib/CMakeFiles/__idf_newlib.dir/heap.c.obj
libesp_system.a,cpu_start.c.obj,esp-idf/esp_system/CMakeFiles/__idf_esp_system.dir/port/cpu_start.c.obj
```

---

### `function.csv` — Function Relocation Rules

This is the core configuration file. Each row specifies a function that should be
**moved from IRAM to flash** (or conditionally moved based on sdkconfig options).
Functions not listed here remain in IRAM.

| Column     | Description                                                          |
|------------|----------------------------------------------------------------------|
| `library`  | Archive name                                                         |
| `object`   | Object file name within the library                                  |
| `function` | Function symbol name to move to flash                                |
| `option`   | *(optional)* sdkconfig condition(s) — function is moved only if true |

**Example (`function.csv`):**

```csv
library,object,function,option
libfreertos.a,tasks.c.obj,xTaskGetCurrentTaskHandle,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libfreertos.a,tasks.c.obj,xTaskGetSchedulerState,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libfreertos.a,tasks.c.obj,xTaskGetTickCount,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libfreertos.a,tasks.c.obj,xTaskPriorityDisinherit,FALSE
libfreertos.a,queue.c.obj,xQueueReceive,
libfreertos.a,queue.c.obj,xQueueGiveFromISR,
libheap.a,heap_caps.c.obj,heap_caps_malloc,
libheap.a,heap_caps.c.obj,heap_caps_free,
libnewlib.a,heap.c.obj,malloc,
libnewlib.a,heap.c.obj,free,
libnewlib.a,locks.c.obj,_lock_acquire,
libnewlib.a,locks.c.obj,_lock_release,
libesp_system.a,cpu_start.c.obj,call_start_cpu0,
```

#### Option Column Syntax

The `option` column controls conditional inclusion based on your project's `sdkconfig`:

| Value | Meaning |
|-------|---------|
| *(empty)* | Function is always moved to flash |
| `CONFIG_XYZ` | Moved to flash only if `CONFIG_XYZ` is defined in sdkconfig |
| `!CONFIG_XYZ` | Moved to flash only if `CONFIG_XYZ` is **not** defined |
| `CONFIG_A && CONFIG_B` | Moved only if both options are defined |
| `CONFIG_A && !CONFIG_B` | Moved only if A is defined and B is not |
| `FALSE` | Function is **never** moved to flash (always stays in IRAM) |

---

## Complete ESP32-C2 Example

Below is a minimal but functional project layout for an ESP32-C2 project with the
relinker enabled.

### Project Structure

```text
my_esp32c2_project/
├── platformio.ini
├── sdkconfig.esp32c2          # auto-generated or manually edited
├── src/
│   └── main.c
└── relinker/
    ├── library.csv
    ├── object.csv
    └── function.csv
```

### `platformio.ini`

```ini
[env:esp32c2]
platform    = espressif32
board       = esp32-c2-devkitm-1
framework   = espidf
monitor_speed = 115200

; Relinker: move non-critical functions from IRAM to Flash
; This frees up IRAM on the ESP32-C2 (only 32KB available)
custom_relinker_library  = relinker/library.csv
custom_relinker_object   = relinker/object.csv
custom_relinker_function = relinker/function.csv
```

### Minimal `relinker/library.csv`

```csv
library,path
libfreertos.a,./esp-idf/freertos/libfreertos.a
libheap.a,./esp-idf/heap/libheap.a
libnewlib.a,./esp-idf/newlib/libnewlib.a
liblog.a,./esp-idf/log/liblog.a
```

### Minimal `relinker/object.csv`

```csv
library,object,path
libfreertos.a,tasks.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/FreeRTOS-Kernel/tasks.c.obj
libfreertos.a,queue.c.obj,esp-idf/freertos/CMakeFiles/__idf_freertos.dir/FreeRTOS-Kernel/queue.c.obj
libheap.a,heap_caps.c.obj,esp-idf/heap/CMakeFiles/__idf_heap.dir/heap_caps.c.obj
libnewlib.a,heap.c.obj,esp-idf/newlib/CMakeFiles/__idf_newlib.dir/heap.c.obj
liblog.a,log.c.obj,esp-idf/log/CMakeFiles/__idf_log.dir/log.c.obj
```

### Minimal `relinker/function.csv`

```csv
library,object,function,option
libfreertos.a,tasks.c.obj,xTaskGetCurrentTaskHandle,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libfreertos.a,tasks.c.obj,xTaskGetSchedulerState,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libfreertos.a,tasks.c.obj,xTaskGetTickCount,CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH
libfreertos.a,queue.c.obj,xQueueReceive,
libfreertos.a,queue.c.obj,xQueueGiveFromISR,
libheap.a,heap_caps.c.obj,heap_caps_malloc,
libheap.a,heap_caps.c.obj,heap_caps_free,
libnewlib.a,heap.c.obj,malloc,
libnewlib.a,heap.c.obj,free,
liblog.a,log.c.obj,esp_log_write,
```

---

## Choosing Functions to Relocate

### Functions That MUST Stay in IRAM

These functions are called during flash operations or from interrupt context where the
flash cache may be disabled. **Never move these to flash:**

- Interrupt Service Routines (ISRs) and functions called from ISRs
- SPI flash operation callbacks (`spi_flash_guard_*`, `spi_flash_os_*`)
- Functions called before the flash cache is initialized (early boot code)
- FreeRTOS scheduler-critical functions (context switch, tick handler)
- Cache error handlers
- RTC/sleep functions that run with flash cache disabled
- Any function decorated with `IRAM_ATTR` in the source code

### Functions That CAN Be Moved to Flash

- Initialization functions called once during startup
- Logging functions (unless used in ISR context)
- Memory allocation functions (if not used in ISR context in your application)
- Non-critical library utility functions
- Configuration/setup routines
- Functions guarded by `CONFIG_FREERTOS_PLACE_FUNCTIONS_INTO_FLASH`

### How to Identify Candidates

1. **Check the ESP-IDF linker map:** After a build, examine `.pio/build/<env>/firmware.map`
   to see which functions consume the most IRAM.

2. **Use `objdump`:** List IRAM sections in a library:
   ```bash
   riscv32-esp-elf-objdump -h .pio/build/esp32c2/esp-idf/freertos/libfreertos.a
   ```

3. **Start with the bundled example:** The CSV files in
   `builder/relinker/examples/esp32c2/` cover a comprehensive set of functions
   validated by Espressif for the ESP32-C2. Use these as your baseline.

4. **Test incrementally:** Move a few functions at a time, rebuild, and test
   thoroughly. A crash during a flash operation usually means a function was moved
   that should have stayed in IRAM.

---

## Troubleshooting

### Build Error: `Failed to get sections from lib ...`

The library path in `library.csv` is incorrect or the library hasn't been built yet.
Ensure all paths are correct relative to `$BUILD_DIR`. Run a clean build first:

```bash
pio run -e esp32c2 -t clean
pio run -e esp32c2
```

### Build Error: `<function> failed to find section`

The function listed in `function.csv` doesn't exist in the specified object file. Check
the function name for typos. Use `objdump -t` to verify the symbol exists:

```bash
riscv32-esp-elf-objdump -t .pio/build/esp32c2/esp-idf/freertos/libfreertos.a | grep xTaskGetTickCount
```

### Runtime Crash (LoadProhibited / InstrFetchProhibited)

A function was moved to flash that gets called while the flash cache is disabled (during
a flash write/erase or from a high-priority ISR). Move the function back to IRAM by
either:
- Removing its entry from `function.csv`, or
- Changing its `option` column to `FALSE` (which keeps it in IRAM unconditionally)

### Relinker Not Running

Verify all three options are set in `platformio.ini`. All three must be present:
- `custom_relinker_library`
- `custom_relinker_object`
- `custom_relinker_function`

---

## Advanced: Using the Full ESP32-C2 Configuration

The bundled example at `builder/relinker/examples/esp32c2/` contains **365 function entries**
covering BLE, WiFi, FreeRTOS, heap, timers, SPI flash, and more. This is the same
configuration validated by Espressif for typical ESP32-C2 applications.

To use it directly:

```ini
[env:esp32c2]
platform    = espressif32
board       = esp32-c2-devkitm-1
framework   = espidf

; Use the full Espressif-validated relinker configuration
custom_relinker_library  = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c2/library.csv
custom_relinker_object   = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c2/object.csv
custom_relinker_function = ${platformio.platforms_dir}/espressif32/builder/relinker/examples/esp32c2/function.csv
```

> **Tip:** Copy the example files into your project and customize them. The full set is
> a good starting point; you can add or remove entries based on your application's needs.

---

## Disabling the Relinker

Simply remove or comment out the `custom_relinker_*` lines in `platformio.ini`:

```ini
[env:esp32c2]
platform  = espressif32
board     = esp32-c2-devkitm-1
framework = espidf

; Relinker disabled — default IRAM layout is used
; custom_relinker_library  = relinker/library.csv
; custom_relinker_object   = relinker/object.csv
; custom_relinker_function = relinker/function.csv
```

---

## Credits

The relinker script was originally developed by Espressif Systems as part of the
[cmake_utilities](https://github.com/espressif/cmake_utilities) component.
It has been adapted for seamless integration with the PlatformIO build system.
