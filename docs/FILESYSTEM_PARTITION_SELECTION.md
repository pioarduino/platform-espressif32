# Filesystem Partition Selection in pioarduino

## Overview

pioarduino ESP32 platform now supports explicit filesystem partition selection via `board_build.filesystem_partition` option. This allows targeting specific filesystem partitions when multiple partitions are present in the partition table.

## Configuration

Add the following option to your `platformio.ini`:

```ini
[env:esp32s3]
# ... other settings ...
board_build.filesystem_partition = spiffs1
```

## Supported Partition Types

The system recognizes both string and numeric partition types:

### Data Partition Types
- `"data"` - String representation
- `"1"` - Decimal representation  
- `"0x01"` - Hexadecimal representation

### Filesystem Subtypes
- `"spiffs"`, `"fat"`, `"littlefs"` - String representations
- `"0x82"`, `"0x81"`, `"0x83"` - Hexadecimal representations
- `"130"`, `"129"`, `"131"` - Decimal representations (via `str()` conversion)

## Behavior

1. **Priority**: If `board_build.filesystem_partition` is specified, the system first looks for a partition with that exact name
2. **Fallback**: If the named partition is not found or not specified, the system falls back to the last available filesystem partition (original behavior)
3. **Warning**: When a named partition is specified but not found, a warning is displayed before fallback

## Example Partition Table

```csv
# Name,   Type, SubType, Offset,  Size, Flags
nvs,      data, nvs,     0x9000,  0x5000,
spiffs1,  data, spiffs,  0xC0000, 0x100000,
spiffs2,  data, spiffs,  0x1C0000,0x200000,
```

With `board_build.filesystem_partition = spiffs1`:
- Upload targets partition at offset `0xC0000`
- If `spiffs1` doesn't exist, falls back to `spiffs2`

## Backward Compatibility

Existing projects without `board_build.filesystem_partition` continue to work unchanged - they will use the last filesystem partition as before.
