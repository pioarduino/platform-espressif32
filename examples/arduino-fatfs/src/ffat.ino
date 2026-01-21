#include "FS.h"
#include "FFat.h"
#include "esp_partition.h"

// Test configuration
// Set to true to format the partition (will erase all data!)
// Set to false to test the pre-flashed image from data/ directory
#define FORMAT_FFAT false  // Test pre-flashed image

// Test settings
#define TEST_READ_EXISTING true   // Test reading files from flashed image
#define TEST_WRITE_NEW true       // Test writing new files
#define TEST_FILE_IO true         // Test file I/O performance

void listDir(fs::FS &fs, const char *dirname, uint8_t levels) {
  Serial.printf("Listing directory: %s\r\n", dirname);

  File root = fs.open(dirname);
  if (!root) {
    Serial.println("- failed to open directory");
    return;
  }
  if (!root.isDirectory()) {
    Serial.println(" - not a directory");
    return;
  }

  File file = root.openNextFile();
  while (file) {
    if (file.isDirectory()) {
      Serial.print("  DIR : ");
      Serial.println(file.name());
      if (levels) {
        listDir(fs, file.path(), levels - 1);
      }
    } else {
      Serial.print("  FILE: ");
      Serial.print(file.name());
      Serial.print("\tSIZE: ");
      Serial.println(file.size());
    }
    file = root.openNextFile();
  }
}

void readFile(fs::FS &fs, const char *path) {
  Serial.printf("Reading file: %s\r\n", path);

  File file = fs.open(path);
  if (!file || file.isDirectory()) {
    Serial.println("- failed to open file for reading");
    return;
  }

  Serial.println("- read from file:");
  while (file.available()) {
    Serial.write(file.read());
  }
  file.close();
}

void writeFile(fs::FS &fs, const char *path, const char *message) {
  Serial.printf("Writing file: %s\r\n", path);

  File file = fs.open(path, FILE_WRITE);
  if (!file) {
    Serial.println("- failed to open file for writing");
    return;
  }
  if (file.print(message)) {
    Serial.println("- file written");
  } else {
    Serial.println("- write failed");
  }
  file.close();
}

void appendFile(fs::FS &fs, const char *path, const char *message) {
  Serial.printf("Appending to file: %s\r\n", path);

  File file = fs.open(path, FILE_APPEND);
  if (!file) {
    Serial.println("- failed to open file for appending");
    return;
  }
  if (file.print(message)) {
    Serial.println("- message appended");
  } else {
    Serial.println("- append failed");
  }
  file.close();
}

void renameFile(fs::FS &fs, const char *path1, const char *path2) {
  Serial.printf("Renaming file %s to %s\r\n", path1, path2);
  if (fs.rename(path1, path2)) {
    Serial.println("- file renamed");
  } else {
    Serial.println("- rename failed");
  }
}

void deleteFile(fs::FS &fs, const char *path) {
  Serial.printf("Deleting file: %s\r\n", path);
  if (fs.remove(path)) {
    Serial.println("- file deleted");
  } else {
    Serial.println("- delete failed");
  }
}

void testFileIO(fs::FS &fs, const char *path) {
  Serial.printf("Testing file I/O with %s\r\n", path);

  static uint8_t buf[512];
  size_t len = 0;
  File file = fs.open(path, FILE_WRITE);
  if (!file) {
    Serial.println("- failed to open file for writing");
    return;
  }

  size_t i;
  Serial.print("- writing");
  uint32_t start = millis();
  for (i = 0; i < 2048; i++) {
    if ((i & 0x001F) == 0x001F) {
      Serial.print(".");
    }
    file.write(buf, 512);
  }
  Serial.println("");
  uint32_t end = millis() - start;
  Serial.printf(" - %u bytes written in %lu ms\r\n", 2048 * 512, end);
  file.close();

  file = fs.open(path);
  start = millis();
  end = start;
  i = 0;
  if (file && !file.isDirectory()) {
    len = file.size();
    size_t flen = len;
    start = millis();
    Serial.print("- reading");
    while (len) {
      size_t toRead = len;
      if (toRead > 512) {
        toRead = 512;
      }
      file.read(buf, toRead);
      if ((i++ & 0x001F) == 0x001F) {
        Serial.print(".");
      }
      len -= toRead;
    }
    Serial.println("");
    end = millis() - start;
    Serial.printf("- %u bytes read in %lu ms\r\n", flen, end);
    file.close();
  } else {
    Serial.println("- failed to open file for reading");
  }
}

void testExistingFiles(fs::FS &fs) {
  Serial.println("\n=== Testing Pre-Flashed Files ===");
  
  // List all files in root
  Serial.println("\nFiles in root directory:");
  listDir(fs, "/", 2);
  
  // Test reading specific files that should exist
  const char* testFiles[] = {
    "/test.txt",
    "/README.md",
    "/platformio.ini",
    "/partitions.csv"
  };
  
  Serial.println("\nReading test files:");
  for (int i = 0; i < 4; i++) {
    if (fs.exists(testFiles[i])) {
      Serial.printf("\n--- File: %s ---\n", testFiles[i]);
      readFile(fs, testFiles[i]);
    } else {
      Serial.printf("File not found: %s\n", testFiles[i]);
    }
  }
}

void testWriteOperations(fs::FS &fs) {
  Serial.println("\n=== Testing Write Operations ===");
  
  // Test creating new file
  Serial.println("\n1. Creating new file...");
  writeFile(fs, "/test_write.txt", "Hello from ESP32!\n");
  
  // Test appending
  Serial.println("\n2. Appending to file...");
  appendFile(fs, "/test_write.txt", "This line was appended.\n");
  appendFile(fs, "/test_write.txt", "And another line.\n");
  
  // Read back
  Serial.println("\n3. Reading back written file:");
  readFile(fs, "/test_write.txt");
  
  // Test rename
  Serial.println("\n4. Testing rename...");
  renameFile(fs, "/test_write.txt", "/renamed.txt");
  readFile(fs, "/renamed.txt");
  
  // Test delete
  Serial.println("\n5. Testing delete...");
  deleteFile(fs, "/renamed.txt");
  
  // Verify deletion
  if (!fs.exists("/renamed.txt")) {
    Serial.println("File successfully deleted");
  } else {
    Serial.println("ERROR: File still exists!");
  }
}

void testFileSystem(fs::FS &fs) {
  Serial.println("\n=== Filesystem Information ===");
  Serial.printf("Total space: %10u bytes (%.2f MB)\n", 
                FFat.totalBytes(), FFat.totalBytes() / 1024.0 / 1024.0);
  Serial.printf("Used space:  %10u bytes (%.2f MB)\n", 
                FFat.usedBytes(), FFat.usedBytes() / 1024.0 / 1024.0);
  Serial.printf("Free space:  %10u bytes (%.2f MB)\n", 
                FFat.freeBytes(), FFat.freeBytes() / 1024.0 / 1024.0);
  
  float usage = (FFat.usedBytes() * 100.0) / FFat.totalBytes();
  Serial.printf("Usage:       %.1f%%\n", usage);
}

void printSeparator() {
  Serial.println("\n============================================================");
}

void setup() {
  Serial.begin(115200);
  delay(1000);  // Wait for serial monitor
  
  // Enable ESP-IDF debug logging
  esp_log_level_set("*", ESP_LOG_DEBUG);
  esp_log_level_set("vfs_fat", ESP_LOG_VERBOSE);
  esp_log_level_set("wear_levelling", ESP_LOG_VERBOSE);
  
  Serial.println("\n\n");
  printSeparator();
  Serial.println("ESP32 FFat Filesystem Test");
  Serial.println("Testing pre-flashed image with Wear Leveling");
  printSeparator();
  
  // Format if requested
  if (FORMAT_FFAT) {
    Serial.println("\n============================================================");
    Serial.println("WARNING: Formatting FFat partition...");
    Serial.println("This will erase all data!");
    Serial.println("============================================================");
    delay(2000);
    
    // First try to mount the WL layer without formatting
    Serial.println("\nStep 1: Checking if WL layer can be mounted...");
    if (FFat.begin(false, "/ffat", 10, "ffat")) {
      Serial.println("✓ WL layer mounted successfully!");
      Serial.println("  Now formatting filesystem...");
      FFat.end();
    } else {
      Serial.println("✗ WL layer mount failed - will try to format anyway");
    }
    
    Serial.println("\nStep 2: Formatting partition...");
    if (!FFat.format(false, (char*)"ffat")) {
      Serial.println("ERROR: FFat Format Failed");
      Serial.println("\nThis means the Wear Leveling layer itself is broken.");
      Serial.println("The WL structure on flash is not compatible with ESP-IDF.");
      return;
    }
    Serial.println("✓ FFat formatted successfully");
    
    Serial.println("\nStep 3: Mounting formatted partition...");
    if (!FFat.begin(false, "/ffat", 10, "ffat")) {
      Serial.println("ERROR: Cannot mount even after format!");
      return;
    }
    Serial.println("✓ Mounted successfully after format");
    
    // Write some test files so we have data to compare
    Serial.println("\nWriting test files...");
    writeFile(FFat, "/test.txt", "This is a test file created by ESP32\n");
    writeFile(FFat, "/README.md", "# ESP32 Formatted Filesystem\n\nThis was formatted on device.\n");
    
    Serial.println("\n*** IMPORTANT: Now download this filesystem ***");
    Serial.println("Run: pio run -t download_fatfs");
    Serial.println("This will save the ESP32-formatted image for comparison");
    
    delay(5000);  // Give time to read the message
  }
  
  // Mount the filesystem
  Serial.println("\nMounting FFat filesystem...");
  Serial.println("Partition label: 'ffat'");
  Serial.println("Format on fail: false");
  Serial.println("Max open files: 10");
  
  if (!FFat.begin(false, "/ffat", 10, "ffat")) {  // formatOnFail = false
    Serial.println("\nERROR: FFat Mount Failed");
    Serial.println("\nDiagnostics:");
    Serial.println("1. Checking partition...");
    
    // Try to get partition info
    const esp_partition_t* partition = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, 
      ESP_PARTITION_SUBTYPE_DATA_FAT, 
      "ffat"
    );
    
    if (partition) {
      Serial.printf("   ✓ Partition found: %s\n", partition->label);
      Serial.printf("     Address: 0x%06X\n", partition->address);
      Serial.printf("     Size: %u bytes (%.2f MB)\n", 
                    partition->size, partition->size / 1024.0 / 1024.0);
      
      // Check FAT boot sector at offset 0 (RAW FAT, no WL layer in flash)
      Serial.println("\n2. Checking FAT boot sector...");
      uint8_t buffer[512];
      if (esp_partition_read(partition, 0, buffer, 512) == ESP_OK) {
        Serial.println("   First 64 bytes at offset 0 (RAW FAT):");
        for (int i = 0; i < 64; i++) {
          Serial.printf("%02X ", buffer[i]);
          if ((i + 1) % 16 == 0) Serial.println();
        }
        Serial.println();
        
        // Check boot signature
        if (buffer[510] == 0x55 && buffer[511] == 0xAA) {
          Serial.println("   ✓ Boot signature found (0x55AA)");
          
          // Parse boot sector
          char oem[9];
          memcpy(oem, buffer + 3, 8);
          oem[8] = 0;
          uint16_t bytes_per_sector = buffer[11] | (buffer[12] << 8);
          uint16_t total_sectors = buffer[19] | (buffer[20] << 8);
          
          Serial.printf("   OEM Name: '%s'\n", oem);
          Serial.printf("   Bytes per sector: %u\n", bytes_per_sector);
          Serial.printf("   Total sectors: %u\n", total_sectors);
          
          if (bytes_per_sector == 4096 && total_sectors == 362) {
            Serial.println("   ✓ Correct format for ESP32 FFat!");
          }
        } else {
          Serial.printf("   ✗ Invalid boot signature: 0x%02X%02X (expected 0x55AA)\n", 
                       buffer[511], buffer[510]);
        }
      }
      
      // Check FAT table
      Serial.println("\n3. Checking FAT table...");
      if (esp_partition_read(partition, 4096, buffer, 32) == ESP_OK) {
        Serial.println("   FAT1 (first 32 bytes at offset 4096):");
        for (int i = 0; i < 32; i++) {
          Serial.printf("%02X ", buffer[i]);
          if ((i + 1) % 16 == 0) Serial.println();
        }
        Serial.println();
        
        if (buffer[0] == 0xF8 && buffer[1] == 0xFF && buffer[2] == 0xFF) {
          Serial.println("   ✓ Media descriptor correct (F8 FF FF)");
          
          // Check if rest is 00
          bool clean = true;
          for (int i = 3; i < 32; i++) {
            if (buffer[i] != 0x00) {
              clean = false;
              break;
            }
          }
          
          if (clean) {
            Serial.println("   ✓ FAT table clean (all zeros after media descriptor)");
          } else {
            Serial.println("   ✗ FAT table has non-zero bytes after media descriptor");
          }
        }
      }
      
      // Check WL metadata at end of partition
      Serial.println("\n4. Checking WL metadata at end...");
      // WL state1 should be at partition_size - 3 * sector_size
      uint32_t wl_state1_offset = partition->size - (3 * 4096);
      if (esp_partition_read(partition, wl_state1_offset, buffer, 48) == ESP_OK) {
        Serial.printf("   WL State at offset 0x%06X (first 48 bytes):\n", wl_state1_offset);
        for (int i = 0; i < 48; i++) {
          Serial.printf("%02X ", buffer[i]);
          if ((i + 1) % 16 == 0) Serial.println();
        }
        Serial.println();
        
        // Parse WL_State
        uint32_t* words = (uint32_t*)buffer;
        Serial.printf("   pos:          %u\n", words[0]);
        Serial.printf("   max_pos:      %u\n", words[1]);
        Serial.printf("   block_size:   %u\n", words[5]);
        Serial.printf("   version:      %u\n", words[6]);
        
        if (words[5] == 4096 && words[6] == 2) {
          Serial.println("   ✓ WL metadata looks valid");
        } else {
          Serial.println("   ✗ WL metadata invalid");
        }
      }
    } else {
      Serial.println("   ✗ Partition 'ffat' not found!");
      Serial.println("   Check partition table in platformio.ini");
    }
    
    Serial.println("\nPossible causes:");
    Serial.println("- Corrupted FAT filesystem");
    Serial.println("- Wrong sector size (should be 4096)");
    Serial.println("- Wrong sector count (should be 362)");
    Serial.println("\nTry: pio run -t erase && pio run -t upload && pio run -t uploadfs");
    return;
  }
  
  Serial.println("✓ FFat mounted successfully!");
  
  // Show filesystem info
  testFileSystem(FFat);
  
  // Test reading existing files
  if (TEST_READ_EXISTING) {
    printSeparator();
    testExistingFiles(FFat);
  }
  
  // Test write operations
  if (TEST_WRITE_NEW) {
    printSeparator();
    testWriteOperations(FFat);
    
    // Show updated filesystem info
    printSeparator();
    Serial.println("\nFilesystem after write tests:");
    testFileSystem(FFat);
  }
  
  // Test file I/O performance
  if (TEST_FILE_IO) {
    printSeparator();
    testFileIO(FFat, "/benchmark.bin");
    
    // Clean up benchmark file
    deleteFile(FFat, "/benchmark.bin");
  }
  
  // Final directory listing
  printSeparator();
  Serial.println("\nFinal directory listing:");
  listDir(FFat, "/", 2);
  
  printSeparator();
  Serial.println("\n✓ All tests completed!");
  Serial.println("\nFilesystem remains mounted for further testing.");
  Serial.println("You can now:");
  Serial.println("- Download filesystem: pio run -t download_fatfs");
  Serial.println("- Reset to re-run tests");
  printSeparator();
}

void loop() {
  // Keep the filesystem mounted
  // You can add interactive commands here if needed
}
