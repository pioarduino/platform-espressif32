/*
 * Arduino Relinker Example for ESP32-C2
 * 
 * This example demonstrates the Arduino Relinker integration.
 * The relinker moves selected functions from IRAM to Flash,
 * freeing up precious IRAM on memory-constrained chips.
 * 
 * ESP32-C2 has only 32KB of IRAM available for user code,
 * making IRAM optimization critical for complex applications.
 */

#include <Arduino.h>

// Task handle for FreeRTOS task
TaskHandle_t taskHandle = NULL;

// Simple task that uses FreeRTOS functions
// Many of these functions are relocated from IRAM to Flash by the relinker
void backgroundTask(void *parameter) {
  while (true) {
    // These FreeRTOS functions are relocated to Flash:
    // - xTaskGetCurrentTaskHandle()
    // - xTaskGetTickCount()
    // - uxTaskGetNumberOfTasks()
    TaskHandle_t currentTask = xTaskGetCurrentTaskHandle();
    TickType_t tickCount = xTaskGetTickCount();
    UBaseType_t taskCount = uxTaskGetNumberOfTasks();
    
    Serial.printf("Task: %p, Ticks: %lu, Tasks: %u\n", 
                  currentTask, tickCount, taskCount);
    
    // These memory functions are also relocated to Flash:
    // - malloc(), free()
    // - heap_caps_malloc(), heap_caps_free()
    void *testMem = malloc(100);
    if (testMem) {
      Serial.println("Memory allocation successful");
      free(testMem);
    }
    
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n=== Arduino Relinker Example ===");
  Serial.println("ESP32-C2 IRAM Optimization Demo");
  Serial.println("================================\n");
  
  // Display memory information
  Serial.printf("Free Heap: %d bytes\n", ESP.getFreeHeap());
  Serial.printf("Heap Size: %d bytes\n", ESP.getHeapSize());
  Serial.printf("Free PSRAM: %d bytes\n", ESP.getFreePsram());
  Serial.printf("Chip Model: %s\n", ESP.getChipModel());
  Serial.printf("Chip Revision: %d\n", ESP.getChipRevision());
  Serial.printf("CPU Frequency: %d MHz\n", ESP.getCpuFreqMHz());
  Serial.printf("Flash Size: %d bytes\n", ESP.getFlashChipSize());
  Serial.println();
  
  Serial.println("Relinker Benefits:");
  Serial.println("- FreeRTOS functions moved to Flash");
  Serial.println("- Memory allocation functions moved to Flash");
  Serial.println("- Logging functions moved to Flash");
  Serial.println("- More IRAM available for critical code");
  Serial.println();
  
  // Create a FreeRTOS task
  xTaskCreate(
    backgroundTask,
    "BackgroundTask",
    4096,
    NULL,
    1,
    &taskHandle
  );
  
  Serial.println("Background task created");
  Serial.println("Monitoring system...\n");
}

void loop() {
  // Main loop - demonstrate logging functions
  // esp_log_write() is relocated to Flash by the relinker
  static uint32_t counter = 0;
  
  Serial.printf("[%lu] Main loop iteration %lu\n", millis(), counter++);
  Serial.printf("Free Heap: %d bytes\n", ESP.getFreeHeap());
  
  // Demonstrate queue operations
  // xQueueSend() and xQueueReceive() are relocated to Flash
  static QueueHandle_t queue = NULL;
  if (queue == NULL) {
    queue = xQueueCreate(10, sizeof(uint32_t));
    Serial.println("Queue created");
  }
  
  if (queue != NULL) {
    uint32_t value = counter;
    if (xQueueSend(queue, &value, 0) == pdTRUE) {
      Serial.println("Value sent to queue");
    }
    
    uint32_t received;
    if (xQueueReceive(queue, &received, 0) == pdTRUE) {
      Serial.printf("Value received from queue: %lu\n", received);
    }
  }
  
  Serial.println();
  delay(5000);
}
