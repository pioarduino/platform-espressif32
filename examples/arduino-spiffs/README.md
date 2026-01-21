# ESP32 SPIFFS Filesystem Test Project

This project tests the SPIFFS filesystem implementation on ESP32.

## Overview

This project demonstrates:
- Building SPIFFS filesystem images
- Uploading SPIFFS images to ESP32
- Mounting and reading SPIFFS filesystem on ESP32
- Downloading and extracting SPIFFS images from ESP32

## Requirements

- PlatformIO
- ESP32 development board
- USB cable

## Project Structure

```
arduino-spiffs/
├── data/                    # Files to be included in SPIFFS image
│   ├── test.txt
│   ├── README.md
│   └── ...
├── src/
│   └── spiffs_test.ino     # Main Arduino sketch
├── partitions.csv          # Partition table with SPIFFS partition
├── platformio.ini          # PlatformIO configuration
└── unpacked_fs/            # Downloaded files (created by download_spiffs)
```

## Usage

### 1. Build Firmware

```bash
pio run
```

### 2. Build SPIFFS Filesystem Image

Place your files in the `data/` directory, then:

```bash
pio run -t buildfs
```

This creates a SPIFFS filesystem image at:
`.pio/build/esp32dev/spiffs.bin`

### 3. Upload Firmware and Filesystem

```bash
# Upload firmware
pio run -t upload

# Upload filesystem
pio run -t uploadfs
```

### 4. Monitor Serial Output

```bash
pio run -t monitor
```

Expected output:
```
SPIFFS mounted successfully
Total space:    1507328
Used space:     12345
Listing directory: /
  FILE: test.txt    SIZE: 12
  FILE: README.md   SIZE: 456
Test complete
```

### 5. Download Filesystem from Device

To download and extract the filesystem from the device:

```bash
pio run -t download_spiffs
```

Files will be extracted to `unpacked_fs/` directory.

## Partition Table

The `partitions.csv` defines the flash layout:

```csv
# Name,   Type, SubType, Offset,  Size, Flags
nvs,      data, nvs,     0x9000,  0x5000,
otadata,  data, ota,     0xe000,  0x2000,
app0,     app,  ota_0,   0x10000, 0x140000,
app1,     app,  ota_1,   0x150000,0x140000,
spiffs,   data, spiffs,  0x290000,0x170000,
```

The `spiffs` partition:
- **Type**: data
- **SubType**: spiffs (0x82)
- **Offset**: 0x290000 (2,686,976 bytes)
- **Size**: 0x170000 (1,507,328 bytes = ~1.44 MB)

## SPIFFS Configuration

Default SPIFFS configuration (can be customized in `platformio.ini`):

```ini
board_build.spiffs.page_size = 256
board_build.spiffs.block_size = 4096
board_build.spiffs.obj_name_len = 32
board_build.spiffs.meta_len = 4
board_build.spiffs.use_magic = true
board_build.spiffs.use_magic_len = true
board_build.spiffs.aligned_obj_ix_tables = false
```

These match ESP-IDF defaults:
- `CONFIG_SPIFFS_PAGE_SIZE = 256`
- `CONFIG_SPIFFS_OBJ_NAME_LEN = 32`
- `CONFIG_SPIFFS_META_LENGTH = 4`
- `CONFIG_SPIFFS_USE_MAGIC = true`
- `CONFIG_SPIFFS_USE_MAGIC_LENGTH = true`

## Troubleshooting

### "SPIFFS Mount Failed"

**Possible causes:**
1. Filesystem not uploaded
2. Wrong partition table
3. Corrupted filesystem

**Solutions:**
```bash
# Rebuild and upload filesystem
pio run -t buildfs
pio run -t uploadfs

# Or erase flash and start fresh
pio run -t erase
pio run -t upload
pio run -t uploadfs
```

### "No SPIFFS filesystem partition found"

**Cause:** Partition table doesn't have a SPIFFS partition

**Solution:** Check `partitions.csv` has a partition with `SubType: spiffs`

### Files not appearing

**Cause:** Files not in `data/` directory when building

**Solution:**
1. Add files to `data/` directory
2. Rebuild filesystem: `pio run -t buildfs`
3. Upload: `pio run -t uploadfs`

## Code Example

```cpp
#include "FS.h"
#include "SPIFFS.h"

void setup() {
    Serial.begin(115200);
    
    // Mount SPIFFS filesystem
    if (!SPIFFS.begin(false)) {
        Serial.println("SPIFFS Mount Failed");
        return;
    }
    
    // List files
    File root = SPIFFS.open("/");
    File file = root.openNextFile();
    while (file) {
        Serial.printf("File: %s, Size: %d\n", 
                     file.name(), file.size());
        file = root.openNextFile();
    }
    
    // Read file
    File f = SPIFFS.open("/test.txt", "r");
    if (f) {
        String content = f.readString();
        Serial.println(content);
        f.close();
    }
    
    // Write file
    f = SPIFFS.open("/output.txt", "w");
    if (f) {
        f.println("Hello from ESP32!");
        f.close();
    }
}

void loop() {
    // Your code here
}
```

## Platform Configuration

This project uses a custom platform with SPIFFS filesystem support:

```ini
[env:esp32dev]
platform = espressif32
framework = arduino
board = esp32dev
board_build.filesystem = spiffs
board_build.partitions = partitions.csv
```

## Comparison with Other Filesystems

| Feature | SPIFFS | LittleFS | FatFS |
|---------|--------|----------|-------|
| Wear Leveling | Built-in | Built-in | Requires WL layer |
| Max File Size | ~1MB | Limited by partition | 4GB |
| Directories | No | Yes | Yes |
| Performance | Medium | Fast | Fast |
| RAM Usage | Low | Low | Medium |
| Reliability | Good | Excellent | Good |

## References

- [ESP32 SPIFFS Library](https://github.com/espressif/arduino-esp32/tree/master/libraries/SPIFFS)
- [ESP-IDF SPIFFS](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/spiffs.html)
- [SPIFFS Specification](https://github.com/pellepl/spiffs)

## Notes

- SPIFFS does not support directories (flat filesystem)
- File names are limited to 32 characters by default
- SPIFFS has built-in wear leveling
- Maximum file size depends on available RAM
- SPIFFS is being deprecated in favor of LittleFS in newer ESP-IDF versions
