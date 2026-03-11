# Arduino-Only ULP Blink for ESP32-C6

| Supported Targets | ESP32-C5 | ESP32-C6 | ESP32-P4 |
| ----------------- | -------- | -------- | -------- |

This example demonstrates running a C program on the LP-Core (ULP) coprocessor using **Arduino framework only** — no ESP-IDF CMake pipeline or hybrid build required.

## Two programs run in parallel

1. **Arduino on the HP Core:** Prints the ULP's shared `led_state` variable over serial.
2. **C program on the LP Core:** Blinks an external LED connected to GPIO3 via the ultra-low-power coprocessor.

## How it works

Place LP-Core sources in the `ulp/` directory. The platform automatically:
- Detects the `ulp/` directory and configures ULP support (sdkconfig, components, lib recompilation)
- Compiles ULP sources with the RISC-V LP-Core toolchain
- Generates `ulp_main.h` (symbol map) and `ulp_main_bin.h` (binary declarations)
- Embeds the binary into the main firmware
- Links `libulp.a` for `ulp_lp_core_load_binary()` and `ulp_lp_core_run()` APIs

No `custom_sdkconfig`, `custom_component_remove`, or `lib_ignore` entries are needed — the platform handles everything. The first build triggers a one-time lib recompilation.

## Hardware Required

- ESP32-C6 (or C5/P4) development board
- LED + resistor on GPIO3 (active high)

## Example Output

```text
Starting ULP blink program...
ULP binary size: 8192 bytes
ULP program running — LED on GPIO3 should blink
ULP led_state: 1
ULP led_state: 0
ULP led_state: 1
```

## Comparison with espidf-arduino-C6-ULP-blink

That example uses `framework = arduino, espidf` (hybrid) and requires CMakeLists.txt, sdkconfig.defaults, and component management. This example uses `framework = arduino` only — the platform handles ULP compilation natively.
