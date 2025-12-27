# FFat Filesystem Test Guide

This guide explains how to test the ESP32 FFat filesystem with pre-flashed images using Wear Leveling.

## Quick Start

### 1. Prepare Test Files

Add files to the `data/` directory that you want to include in the filesystem:

```bash
# Example files already included:
data/
├── test.txt
├── README.md
├── platformio.ini
└── partitions.csv
```

### 2. Build Filesystem Image

Build the FAT filesystem image with Wear Leveling layer:

```bash
pio run -t buildfs
```

This creates `.pio/build/esp32dev/fatfs.bin` with:
- Your files from `data/` directory
- ESP32 Wear Leveling layer
- Proper FAT filesystem structure

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

## Test Configuration

Edit `src/ffat.ino` to configure tests:

```cpp
// Set to true to format the partition (erases all data!)
#define FORMAT_FFAT false

// Test settings
#define TEST_READ_EXISTING true   // Test reading pre-flashed files
#define TEST_WRITE_NEW true       // Test writing new files
#define TEST_FILE_IO true         // Test I/O performance
```

## Expected Output

### Successful Mount

```
============================================================
ESP32 FFat Filesystem Test
Testing pre-flashed image with Wear Leveling
============================================================

Mounting FFat filesystem...
✓ FFat mounted successfully!

=== Filesystem Information ===
Total space:    1486848 bytes (1.42 MB)
Used space:       12288 bytes (0.01 MB)
Free space:     1474560 bytes (1.41 MB)
Usage:       0.8%
```

### Reading Pre-Flashed Files

```
============================================================

=== Testing Pre-Flashed Files ===

Files in root directory:
Listing directory: /
  FILE: test.txt    SIZE: 12
  FILE: README.md   SIZE: 1234
  FILE: platformio.ini    SIZE: 456
  FILE: partitions.csv    SIZE: 234

Reading test files:

--- File: /test.txt ---
Reading file: /test.txt
- read from file:
Hello World!

--- File: /README.md ---
Reading file: /README.md
- read from file:
[README content...]
```

### Write Operations

```
============================================================

=== Testing Write Operations ===

1. Creating new file...
Writing file: /test_write.txt
- file written

2. Appending to file...
Appending to file: /test_write.txt
- message appended
Appending to file: /test_write.txt
- message appended

3. Reading back written file:
Reading file: /test_write.txt
- read from file:
Hello from ESP32!
This line was appended.
And another line.

4. Testing rename...
Renaming file /test_write.txt to /renamed.txt
- file renamed
Reading file: /renamed.txt
[content...]

5. Testing delete...
Deleting file: /renamed.txt
- file deleted
File successfully deleted
```

### Performance Test

```
============================================================

Testing file I/O with /benchmark.bin
- writing................................
 - 1048576 bytes written in 2345 ms
- reading................................
 - 1048576 bytes read in 1234 ms
```

## Troubleshooting

### "FFat Mount Failed"

**Possible causes:**

1. **No FFat partition in partition table**
   - Check `partitions.csv` has a `fat` partition
   - Verify partition is flashed

2. **Filesystem not flashed**
   ```bash
   pio run -t buildfs
   pio run -t uploadfs
   ```

3. **Missing Wear Leveling layer**
   - Ensure you're using the updated platform with WL support
   - Rebuild filesystem image

4. **Corrupted filesystem**
   - Set `FORMAT_FFAT true` to reformat
   - Or erase flash: `pio run -t erase`

### "File not found"

If pre-flashed files are not found:

1. Check files exist in `data/` directory
2. Rebuild filesystem: `pio run -t buildfs`
3. Upload filesystem: `pio run -t uploadfs`
4. Reset ESP32

### "Write failed"

If write operations fail:

1. Check filesystem is not full
2. Verify partition has write permissions
3. Check for filesystem corruption

## Advanced Testing

### Download and Verify Filesystem

After running tests, download the filesystem to verify changes:

```bash
pio run -t download_fatfs
```

Files will be extracted to `unpacked_fs/` directory.

### Compare Original and Downloaded

```bash
# Compare original files
diff data/test.txt unpacked_fs/test.txt

# Check for new files created by tests
ls -la unpacked_fs/
```

### Test Wear Leveling

To verify wear leveling is working:

1. Write many files
2. Download filesystem
3. Check WL state is valid:

```python
from fatfs import is_esp32_wl_image

with open('.pio/build/esp32dev/downloaded_fs_*.bin', 'rb') as f:
    data = f.read()
    
if is_esp32_wl_image(data):
    print("✓ Wear Leveling layer is intact")
else:
    print("✗ Wear Leveling layer is missing or corrupted")
```

## Test Scenarios

### Scenario 1: Fresh Filesystem

```cpp
#define FORMAT_FFAT true
#define TEST_READ_EXISTING false
#define TEST_WRITE_NEW true
#define TEST_FILE_IO true
```

Tests creating a new filesystem from scratch.

### Scenario 2: Pre-Flashed Image (Default)

```cpp
#define FORMAT_FFAT false
#define TEST_READ_EXISTING true
#define TEST_WRITE_NEW true
#define TEST_FILE_IO true
```

Tests reading pre-flashed files and writing new ones.

### Scenario 3: Read-Only Test

```cpp
#define FORMAT_FFAT false
#define TEST_READ_EXISTING true
#define TEST_WRITE_NEW false
#define TEST_FILE_IO false
```

Only tests reading pre-flashed files without modifications.

### Scenario 4: Performance Only

```cpp
#define FORMAT_FFAT false
#define TEST_READ_EXISTING false
#define TEST_WRITE_NEW false
#define TEST_FILE_IO true
```

Only tests I/O performance.

## Continuous Integration

For automated testing:

```bash
#!/bin/bash
# test_fatfs.sh

# Build and upload
pio run -t buildfs
pio run -t upload
pio run -t uploadfs

# Wait for ESP32 to boot
sleep 2

# Monitor output and check for success
pio run -t monitor | tee test_output.log

# Verify output
if grep -q "✓ All tests completed!" test_output.log; then
    echo "Tests PASSED"
    exit 0
else
    echo "Tests FAILED"
    exit 1
fi
```

## Debugging

### Enable Debug Output

```cpp
void setup() {
    Serial.begin(115200);
    Serial.setDebugOutput(true);  // Enable ESP32 debug output
    // ...
}
```

### Check Partition Table

```bash
# Read partition table from device
pio run -t monitor

# In another terminal
esptool.py --port /dev/ttyUSB0 read_flash 0x8000 0x1000 partition_table.bin

# Parse partition table
python -c "
import struct
with open('partition_table.bin', 'rb') as f:
    data = f.read()
    for i in range(0, len(data), 32):
        entry = data[i:i+32]
        if entry[:2] == b'\xAA\x50':
            print(f'Partition at {i}: {entry.hex()}')
"
```

### Verify Wear Leveling

```bash
# Download filesystem
pio run -t download_fatfs

# Check WL structure
python -c "
from fatfs import is_esp32_wl_image, ESP32WearLeveling
import struct

with open('.pio/build/esp32dev/downloaded_fs_*.bin', 'rb') as f:
    data = f.read()

if is_esp32_wl_image(data):
    wl = ESP32WearLeveling()
    state = data[:48]
    fields = struct.unpack('<IIIIIIII', state[:32])
    print(f'WL State:')
    print(f'  pos: {fields[0]}')
    print(f'  max_pos: {fields[1]}')
    print(f'  block_size: {fields[5]}')
    print(f'  version: {fields[6]}')
"
```

## References

- [FFat Library Documentation](https://github.com/espressif/arduino-esp32/tree/master/libraries/FFat)
- [ESP-IDF FAT Filesystem](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/fatfs.html)
