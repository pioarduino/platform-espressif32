# FatFS Integration for Platform-Espressif32

This platform now supports FatFS as a filesystem option, analogous to the existing LittleFS integration.

## Features

- **Build FatFS Image**: Creates a FatFS filesystem image from a directory
- **Upload FatFS Image**: Uploads the FatFS image to the ESP32 device
- **Download FatFS Image**: Downloads the FatFS image from the device and extracts it

## Configuration

### platformio.ini

```ini
[env:myenv]
platform = espressif32
board = esp32dev
framework = arduino

; Select FatFS as filesystem
board_build.filesystem = fatfs

; Optional: Directory for extracted files (default: unpacked_fs)
board_build.unpack_dir = unpacked_fs
```

### Partition Table

The partition table must contain a FAT partition (Subtype 0x81):

```csv
# Name,   Type, SubType, Offset,  Size, Flags
nvs,      data, nvs,     0x9000,  0x5000,
otadata,  data, ota,     0xe000,  0x2000,
app0,     app,  ota_0,   0x10000, 0x140000,
app1,     app,  ota_1,   0x150000,0x140000,
ffat,     data, fat,     0x290000,0x170000,
```

## Usage

### Build FatFS Image

```bash
# Place files in data/ directory
mkdir -p data
echo "Hello FatFS" > data/test.txt

# Build image
pio run -t buildfs
```

### Upload FatFS Image

```bash
pio run -t uploadfs
```

### Download FatFS Image from Device

```bash
pio run -t download_fatfs
```

Files will be extracted to the configured directory (default: `unpacked_fs`).

## Technical Details

### Python Dependencies

The integration uses the `fatfs-ng` package, which is automatically installed.

### Build Process

1. A RAM disk is created with the configured FAT data size (partition size minus WL overhead)
2. The FatFS is formatted with proper parameters (2 FATs, LFN support)
3. All files from the `data/` directory are copied
4. The FAT image is wrapped with ESP32 Wear Leveling layer
5. The final image is saved as a `.bin` file

**Important**: The build process automatically adds the ESP32 Wear Leveling layer, which is required by the Arduino FFat library. See [WEAR_LEVELING.md](WEAR_LEVELING.md) for details.

### Wear Leveling Layer

ESP32's FFat library requires a wear leveling layer around the FAT filesystem. The build process automatically:
- Reserves sectors for wear leveling metadata
- Wraps the FAT filesystem with WL_State structures
- Calculates proper CRC32 checksums

### Download Process

1. The partition table is downloaded from the device
2. The FAT partition is identified (Subtype 0x81)
3. The filesystem image is downloaded
4. The wear leveling layer is automatically detected and removed
5. The FAT data is mounted and extracted

## Extended Features

The `pyfatfs` package includes extended features for complete directory traversal:

- **Complete Directory Traversal**: `walk()`, `listdir()`, `stat()`
- **Path Operations**: `exists()`, `isfile()`, `isdir()`
- **File Operations**: `remove()`, `rmdir()`, `rename()`, `makedirs()`
- **Convenience Methods**: `read_file()`, `write_file()`
- **Bulk Operations**: `copy_tree_from()`, `copy_tree_to()`

These features enable full filesystem extraction and manipulation.

## Comparison: LittleFS vs FatFS

| Feature | LittleFS | FatFS |
|---------|----------|-------|
| Wear Leveling | Yes | Yes |
| Power-Loss Protection | Yes | Limited |
| Compatibility | ESP-IDF specific | Standard FAT |
| Sector Size | 4096 | 4096 |
| Filesystem Size | Flexible | Larger |

## Example Code (Arduino)

```cpp
#include <FFat.h>

void setup() {
    Serial.begin(115200);
    
    // Mount FatFS
    if (!FFat.begin(true)) {
        Serial.println("FFat Mount Failed");
        return;
    }
    
    // Read file
    File file = FFat.open("/test.txt", "r");
    if (file) {
        Serial.println(file.readString());
        file.close();
    }
    
    // Write file
    file = FFat.open("/output.txt", "w");
    if (file) {
        file.println("Hello from ESP32!");
        file.close();
    }
}

void loop() {
    // ...
}
```

## Troubleshooting

### "No FAT filesystem partition found"

- Check the partition table
- Ensure a partition with subtype `fat` (0x81) exists

### Build Errors

```bash
# Recreate Python environment
rm -rf ~/.platformio/penv
pio run
```

## Further Information

- [FatFS Documentation](http://elm-chan.org/fsw/ff/00index_e.html)
- [ESP-IDF FFat Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/fatfs.html)
- [fatfs-ng Repository](https://github.com/Jason2866/pyfatfs)
- [Original fatfs-python](https://github.com/krakonos/fatfs-python)
