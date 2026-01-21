#include "FS.h"
#include "LittleFS.h"

// Test configuration
#define FORMAT_LITTLEFS false  // Set to true to format (will erase all data!)

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
                LittleFS.totalBytes(), LittleFS.totalBytes() / 1024.0 / 1024.0);
  Serial.printf("Used space:  %10u bytes (%.2f MB)\n", 
                LittleFS.usedBytes(), LittleFS.usedBytes() / 1024.0 / 1024.0);
  
  float usage = (LittleFS.usedBytes() * 100.0) / LittleFS.totalBytes();
  Serial.printf("Usage:       %.1f%%\n", usage);
}

void printSeparator() {
  Serial.println("\n============================================================");
}

void setup() {
  Serial.begin(115200);
  delay(1000);  // Wait for serial monitor
  
  Serial.println("\n\n");
  printSeparator();
  Serial.println("ESP32 LittleFS Filesystem Test");
  Serial.println("Testing pre-flashed LittleFS image");
  printSeparator();
  
  // Format if requested
  if (FORMAT_LITTLEFS) {
    Serial.println("\n============================================================");
    Serial.println("WARNING: Formatting LittleFS partition...");
    Serial.println("This will erase all data!");
    Serial.println("============================================================");
    delay(2000);
    
    if (!LittleFS.format()) {
      Serial.println("ERROR: LittleFS Format Failed");
      return;
    }
    Serial.println(" LittleFS formatted successfully");
  }
  
  // Mount the filesystem
  Serial.println("\nMounting LittleFS filesystem...");
  Serial.println("Format on fail: false");
  
  if (!LittleFS.begin(false)) {  // formatOnFail = false
    Serial.println("\nERROR: LittleFS Mount Failed");
    Serial.println("\nPossible causes:");
    Serial.println("- Filesystem not uploaded");
    Serial.println("- Corrupted LittleFS filesystem");
    Serial.println("- Wrong partition table");
    Serial.println("\nTry: pio run -t uploadfs");
    return;
  }
  
  Serial.println(" LittleFS mounted successfully!");
  
  // Show filesystem info
  testFileSystem(LittleFS);
  
  // Test reading existing files
  if (TEST_READ_EXISTING) {
    printSeparator();
    testExistingFiles(LittleFS);
  }
  
  // Test write operations
  if (TEST_WRITE_NEW) {
    printSeparator();
    testWriteOperations(LittleFS);
    
    // Show updated filesystem info
    printSeparator();
    Serial.println("\nFilesystem after write tests:");
    testFileSystem(LittleFS);
  }
  
  // Test file I/O performance
  if (TEST_FILE_IO) {
    printSeparator();
    testFileIO(LittleFS, "/benchmark.bin");
    
    // Clean up benchmark file
    deleteFile(LittleFS, "/benchmark.bin");
  }
  
  // Final directory listing
  printSeparator();
  Serial.println("\nFinal directory listing:");
  listDir(LittleFS, "/", 2);
  
  printSeparator();
  Serial.println("\n All tests completed!");
  Serial.println("\nFilesystem remains mounted for further testing.");
  Serial.println("You can now:");
  Serial.println("- Download filesystem: pio run -t download_fs");
  Serial.println("- Reset to re-run tests");
  printSeparator();
}

void loop() {
  // Keep the filesystem mounted
  // You can add interactive commands here if needed
}
