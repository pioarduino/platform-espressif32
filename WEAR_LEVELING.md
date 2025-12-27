# ESP32 Wear Leveling Implementation for FAT Filesystem

## Overview

This implementation adds ESP32 Wear Leveling layer support to FAT filesystem images created with `fatfs-python`. The wear leveling layer is required by the ESP32 Arduino Core's `FFat` library, which uses ESP-IDF's `esp_vfs_fat_spiflash_mount_rw_wl()` function.

## Problem

The ESP32 Arduino Core expects FAT partitions to be wrapped with a wear leveling layer:
- **Without WL**: Raw FAT filesystem → **Mount fails**
- **With WL**: WL State + FAT filesystem + WL metadata → **Mount succeeds**

## Wear Leveling Structure

```
┌─────────────────────────────────────────────────────────────┐
│ Sector 0: WL State Copy 1                                   │
├─────────────────────────────────────────────────────────────┤
│ Sector 1: WL State Copy 2                                   │
├─────────────────────────────────────────────────────────────┤
│ Sector 2-N: FAT Filesystem Data                             │
│             (Boot sector, FATs, Root dir, Data area)        │
├─────────────────────────────────────────────────────────────┤
│ Sector N+1: Temp Sector (for WL operations)                 │
├─────────────────────────────────────────────────────────────┤
│ Sector N+2: WL State Copy 3                                 │
├─────────────────────────────────────────────────────────────┤
│ Sector N+3: WL State Copy 4                                 │
└─────────────────────────────────────────────────────────────┘
```

## WL_State Structure (48 bytes)

```c
typedef struct {
    uint32_t pos;           // Current position (0)
    uint32_t max_pos;       // Maximum position (number of FAT sectors)
    uint32_t move_count;    // Move counter (0)
    uint32_t access_count;  // Access counter (0)
    uint32_t max_count;     // Maximum count (update_rate * fat_sectors)
    uint32_t block_size;    // Block/sector size (4096)
    uint32_t version;       // WL version (2)
    uint32_t device_id;     // Device ID (0)
    uint8_t  reserved[12];   // Reserved (0xFF)
    uint32_t crc32;         // CRC32 of structure
} WL_State;
```

## Configuration

### Default Values
- **Sector Size**: 4096 bytes (ESP32 standard)
- **Update Rate**: 16 (triggers WL after 16 * sectors writes)
- **WL State Sectors**: 2 copies at start, 2 at end (4 total)
- **Temp Sectors**: 1 sector for WL operations

### Overhead Calculation
```
Total Sectors = Partition Size / Sector Size
WL Overhead = (2 + 2 + 1) = 5 sectors
FAT Sectors = Total Sectors - 5
```

Example for 1.5 MB partition:
- Total: 1,507,328 bytes / 4096 = 368 sectors
- WL Overhead: 5 sectors = 20,480 bytes
- FAT Data: 363 sectors = 1,486,848 bytes

## Usage

### Building FAT Image with WL

The `build_fatfs_image()` function in `main.py` automatically wraps FAT images:

```bash
pio run -t buildfs
```

Output:
```
Building FS image from 'data' directory to .pio/build/esp32dev/fatfs.bin
Wrapping FAT image with ESP32 Wear Leveling layer...
  Partition size: 1507328 bytes (368 sectors)
  FAT data size: 1486848 bytes (363 sectors)
  WL overhead: 5 sectors
Successfully created wear-leveling FAT image
```

### Downloading and Extracting

The `download_fatfs` target automatically detects and extracts WL-wrapped images:

```bash
pio run -t download_fatfs
```

Output:
```
Detected Wear Leveling layer, extracting FAT data...
  Extracted FAT data: 1486848 bytes
Extracting files:
  FILE: /test.txt (12 bytes)
Successfully extracted 1 file(s) to unpacked_fs
```

## Technical Details

### CRC32 Calculation

The WL_State CRC32 is calculated over the first 44 bytes (excluding the CRC field itself):

```python
state_data = struct.pack('<IIIIIIII12s',
    pos, max_pos, move_count, access_count, max_count,
    block_size, version, device_id, reserved)
crc = zlib.crc32(state_data) & 0xFFFFFFFF
```

### Sector Alignment

All data must be aligned to sector boundaries (4096 bytes):
- WL State is padded with 0xFF to fill the sector
- FAT data is padded with 0xFF to sector boundary
- Total image size must equal partition size exactly

### Erased Flash Value

Unused areas are filled with `0xFF` (erased flash state):
- Reserved bytes in WL_State: `0xFF`
- Padding after FAT data: `0xFF`
- Temp sector: `0xFF`

## Compatibility

### ESP-IDF Versions
- Tested with ESP-IDF v4.x and v5.x
- Compatible with Arduino-ESP32 core 2.x and 3.x

### Sector Sizes
- **Supported**: 4096 bytes (recommended)
- **Theoretical**: 512, 1024, 2048 bytes (not tested)

### FAT Types
- FAT12 (small partitions)
- FAT16 (medium partitions)
- FAT32 (large partitions, >32MB)

## Verification

### Check WL State

```python
from esp32_wl import WearLevelingLayer

wl = WearLevelingLayer()
with open('fatfs.bin', 'rb') as f:
    data = f.read()
    
# Verify first state sector
state = data[:48]
is_valid = wl.verify_wl_state(state)
print(f"WL State valid: {is_valid}")
```

### Extract FAT Data

```python
from esp32_wl import extract_fat_from_wl_image

with open('fatfs.bin', 'rb') as f:
    wl_image = f.read()

fat_data = extract_fat_from_wl_image(wl_image)
if fat_data:
    with open('fat_only.bin', 'wb') as f:
        f.write(fat_data)
```

## Troubleshooting

### "FFat Mount Failed"

**Cause**: Image doesn't have wear leveling layer

**Solution**: Rebuild with updated `build_fatfs_image()`:
```bash
pio run -t buildfs
pio run -t uploadfs
```

### "Invalid sector size"

**Cause**: Sector size mismatch between build and ESP32 config

**Solution**: Ensure `CONFIG_WL_SECTOR_SIZE=4096` in sdkconfig

### "Partition too small"

**Cause**: FAT data + WL overhead exceeds partition size

**Solution**: Increase partition size in `partitions.csv` or reduce data

## References

- [ESP-IDF Wear Levelling Component](https://github.com/espressif/esp-idf/tree/master/components/wear_levelling)
- [ESP-IDF FAT Filesystem](https://github.com/espressif/esp-idf/tree/master/components/fatfs)
- [Arduino-ESP32 FFat Library](https://github.com/espressif/arduino-esp32/tree/master/libraries/FFat)
- [mk_esp32fat Tool](https://github.com/TobleMiner/mk_esp32fat) (alternative C implementation)

## License

Same as platform-espressif32 (Apache 2.0)
