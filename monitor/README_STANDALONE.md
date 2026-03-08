# ESP32 Exception Decoder - Standalone Mode

This tool decodes ESP32 crash logs (exception backtraces) using the firmware ELF file to provide human-readable function names and source code locations.

## Features

- **Offline Operation**: Works without an active project
- **Auto-Detection**: Automatically detects architecture (RISC-V or Xtensa)
- **Auto-Discovery**: Finds toolchain binaries (addr2line, GDB) automatically
- **Multiple Architectures**: Supports ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6, ESP32-H2, etc.
- **Detailed Decoding**: Decodes register dumps, stack memory, and backtraces

## Requirements

- Python 3.10 or higher
- ESP-IDF toolchain installed (default installed from pioarduino)
- Optional: `pyelftools` for improved address filtering (default installed from pioarduino)

## Installation

No installation required! Just use the script directly:

```bash
python3 filter_exception_decoder.py <elf_file> <crash_log>
```

## Usage

### Basic Usage

Decode a crash log and print to stdout:

```bash
python3 filter_exception_decoder.py firmware.elf crash.txt
```

### Save to File

Decode and save the output to a file:

```bash
python3 filter_exception_decoder.py firmware.elf crash.txt -o decoded.txt
```

### With Full Paths

```bash
python3 filter_exception_decoder.py /path/to/firmware.elf /path/to/crash.log --output result.txt
```

### Help

```bash
python3 filter_exception_decoder.py --help
```

## How It Works

1. **Architecture Detection**: Reads the ELF header to determine if the firmware is RISC-V or Xtensa
2. **Toolchain Discovery**: Searches for `addr2line` and `gdb` in `~/.platformio/packages/toolchain-*/bin/`
3. **Address Decoding**: Uses `addr2line` to convert memory addresses to function names and source locations
4. **Stack Unwinding**: For RISC-V, optionally uses GDB for complete stack unwinding

## Output Format

The tool adds decoded information inline with the original crash log:

```text
Core  0 register dump:
MEPC    : 0x4080c1aa  RA      : 0x4080c16e  SP      : 0x40823630  GP      : 0x40813ae4
  MEPC: 0x4080c1aa: panic_abort at panic.c:491
  RA: 0x4080c16e: esp_vApplicationTickHook at freertos_hooks.c:31

Stack memory:
40823630: 0x4082376c 0x00000067 0x42090f54 0x4081107c ...
  0x4081107c: esp_libc_include_assert_impl at assert.c:96
```

## Toolchain Installation

### Via pioarduino

No manual install needed, pioarduino does install everything automatically.

## Troubleshooting

### "addr2line tool not found"

The toolchain is not installed or not in the search path. Install via:
- (re)install pioarduino / platform espressif32

### "ELF file not found"

Check that the path to the firmware ELF file is correct. The ELF file is typically:
- pioarduino: `.pio/build/<env>/firmware.elf`

### "Crash log file not found"

Ensure the crash log file path is correct. You can capture crash logs via:
- Serial monitor output
- pioarduino monitor
- ESP-IDF monitor

## Examples

### Example 1: Quick Decode

```bash
python3 filter_exception_decoder.py firmware.elf crash.txt
```

### Example 2: Decode with Output File

```bash
python3 filter_exception_decoder.py \
  .pio/build/esp32c6/firmware.elf \
  crash_log.txt \
  -o decoded_crash.txt
```

### Example 3: Pipe from Serial Monitor

```bash
# Capture crash log from serial port
cat /dev/ttyUSB0 > crash.txt

# Decode it
python3 filter_exception_decoder.py firmware.elf crash.txt
```

## Advanced Features

### ELF Section Filtering

When `pyelftools` is installed, the tool filters addresses by checking if they fall into executable ELF sections, avoiding unnecessary decoding of data addresses.

### GDB Stack Unwinding (RISC-V only)

For RISC-V targets, if GDB is available, the tool can perform complete stack unwinding to show the full call chain.

## Supported Chips

- ESP32 (Xtensa)
- ESP32-S2 (Xtensa)
- ESP32-S3 (Xtensa)
- ESP32-C2 (RISC-V)
- ESP32-C3 (RISC-V)
- ESP32-C5 (RISC-V)
- ESP32-C6 (RISC-V)
- ESP32-H2 (RISC-V)
- ESP32-H4 (RISC-V)
- ESP32-P4 (RISC-V)

## License

Apache License 2.0
