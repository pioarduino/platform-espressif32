# ESP32 FAT Filesystem Test Project

This project tests the FAT filesystem implementation with ESP32 Wear Leveling support.

## Overview

This project demonstrates:
- Building FAT filesystem images with wear leveling layer
- Uploading FAT images to ESP32
- Mounting and reading FAT filesystem on ESP32
- Downloading and extracting FAT images from ESP32

## Requirements

- PlatformIO
- ESP32 development board
- USB cable

## Project Structure

```
arduino-fatfs/
├── data/                    # Files to be included in FAT image
│   ├── test.txt
│   ├── README.md
│   └── ...
├── src/
│   └── ffat.ino            # Main Arduino sketch
├── partitions.csv          # Partition table with FAT partition
├── platformio.ini          # PlatformIO configuration
└── unpacked_fs/            # Downloaded files (created by download_fatfs)
```

## Usage

### 1. Build Firmware

```bash
pio run
```

### 2. Build FAT Filesystem Image

Place your files in the `data/` directory, then:

```bash
pio run -t buildfs
```

This creates a FAT filesystem image with ESP32 wear leveling layer at:
`.pio/build/esp32dev/fatfs.bin`

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
FFat mounted successfully
Test begin
Total space:    1486848
Free space:     1482752
Listing directory: /
  FILE: test.txt    SIZE: 12
  FILE: README.md   SIZE: 1234
Test complete
```

### 5. Download Filesystem from Device

To download and extract the filesystem from the device:

```bash
pio run -t download_fatfs
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
ffat,     data, fat,     0x290000,0x170000,
```

The `ffat` partition:
- **Type**: data
- **SubType**: fat (0x81)
- **Offset**: 0x290000 (2,686,976 bytes)
- **Size**: 0x170000 (1,507,328 bytes = ~1.44 MB)

## Wear Leveling

The FAT filesystem is automatically wrapped with ESP32's wear leveling layer:

- **Total partition**: 1,507,328 bytes (368 sectors × 4096 bytes)
- **WL overhead**: 20,480 bytes (5 sectors)
- **FAT data**: 1,486,848 bytes (363 sectors)

Structure:
```
[WL State 1][WL State 2][FAT Data][Temp][WL State 3][WL State 4]
```

See [WEAR_LEVELING.md](../../WEAR_LEVELING.md) for details.

## Troubleshooting

### "FFat Mount Failed"

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

### "No FAT filesystem partition found"

**Cause:** Partition table doesn't have a FAT partition

**Solution:** Check `partitions.csv` has a partition with `SubType: fat`

### Files not appearing

**Cause:** Files not in `data/` directory when building

**Solution:**
1. Add files to `data/` directory
2. Rebuild filesystem: `pio run -t buildfs`
3. Upload: `pio run -t uploadfs`

## Code Example

```cpp
#include "FFat.h"

void setup() {
    Serial.begin(115200);
    
    // Mount FAT filesystem
    if (!FFat.begin(false)) {
        Serial.println("FFat Mount Failed");
        return;
    }
    
    // List files
    File root = FFat.open("/");
    File file = root.openNextFile();
    while (file) {
        Serial.printf("File: %s, Size: %d\n", 
                     file.name(), file.size());
        file = root.openNextFile();
    }
    
    // Read file
    File f = FFat.open("/test.txt", "r");
    if (f) {
        String content = f.readString();
        Serial.println(content);
        f.close();
    }
    
    // Write file
    f = FFat.open("/output.txt", "w");
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

This project uses a custom platform with FAT filesystem support:

```ini
[env:esp32dev]
platform = espressif32
framework = arduino
board = esp32dev
board_build.filesystem = fatfs
board_build.partitions = partitions.csv
```

## References

- [ESP32 FFat Library](https://github.com/espressif/arduino-esp32/tree/master/libraries/FFat)
- [ESP-IDF FAT Filesystem](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/fatfs.html)
- [ESP-IDF Wear Levelling](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/wear-levelling.html)
- [Platform-Espressif32 FAT Integration](../../FATFS_INTEGRATION.md)
- [Wear Leveling Implementation](../../platform-espressif32/WEAR_LEVELING.md)
