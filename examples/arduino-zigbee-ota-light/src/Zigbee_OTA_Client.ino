// Copyright 2026 Espressif Systems (Shanghai) PTE LTD
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * @brief This example demonstrates OTA support on light bulb.
 *
 * The example demonstrates how to use Zigbee library to create a end device light bulb with OTA support.
 * The light bulb is a Zigbee end device, which is controlled by a Zigbee coordinator.
 *
 * Please check the README.md for instructions and more detailed description.
 */

#include <Arduino.h>
#ifndef ZIGBEE_MODE_ED
#error "Zigbee end device mode is not selected"
#endif

#include "Zigbee.h"

#define ZIGBEE_LIGHT_ENDPOINT 1
#define OTA_UPGRADE_MANUFACTURER 0x1001
#define OTA_UPGRADE_IMAGE_TYPE 0x1011
#define OTA_UPGRADE_RUNNING_FILE_VERSION 0x01010100
#define OTA_UPGRADE_DOWNLOADED_FILE_VERSION 0xFFFFFFFF
#define OTA_UPGRADE_HW_VERSION 0x0101
#define FW_VERSION_PRINT_INTERVAL_MS 10000

uint8_t led = RGB_BUILTIN;
uint8_t button = BOOT_PIN;
ZigbeeLight zbLight = ZigbeeLight(ZIGBEE_LIGHT_ENDPOINT);

volatile bool otaRunning = false;

void otaActiveCallback(bool otaActive) {
  otaRunning = otaActive;
  Serial.println(otaActive ? "OTA started" : "OTA inactive");
}

void otaCompleteCallback(bool success) {
  Serial.println(success ? "OTA finished" : "OTA aborted");
}

void setLED(bool value) {
  digitalWrite(led, value);
}

void setup() {
  Serial.begin(115200);
  pinMode(led, OUTPUT);
  digitalWrite(led, LOW);
  pinMode(button, INPUT_PULLUP);

  if (!Zigbee.role(ZIGBEE_END_DEVICE)) {
    Serial.println("Zigbee failed to init; rebooting");
    delay(1000);
    ESP.restart();
  }

  zbLight.setManufacturerAndModel("Espressif", "ZBLightBulb");
  zbLight.onLightChange(setLED);
  zbLight.addOTAClient(
    OTA_UPGRADE_RUNNING_FILE_VERSION, OTA_UPGRADE_DOWNLOADED_FILE_VERSION, OTA_UPGRADE_HW_VERSION, OTA_UPGRADE_MANUFACTURER,
    OTA_UPGRADE_IMAGE_TYPE
  );
  zbLight.onOTAStateChange(otaActiveCallback);
  zbLight.onOTAComplete(otaCompleteCallback);
  Zigbee.addEndpoint(&zbLight);

  Serial.println("Starting Zigbee...");
  if (!Zigbee.begin()) {
    Serial.println("Zigbee failed to start; rebooting");
    ESP.restart();
  }

  Serial.println("Connecting to network");
  while (!Zigbee.connected()) {
    Serial.print(".");
    delay(100);
  }
  Serial.println();
  zbLight.requestOTAUpdate();
}

void loop() {
  static uint32_t lastFwPrintMs = 0;
  if (millis() - lastFwPrintMs >= FW_VERSION_PRINT_INTERVAL_MS) {
    lastFwPrintMs = millis();
    Serial.printf("Running FW version: 0x%08lX\n", (unsigned long)OTA_UPGRADE_RUNNING_FILE_VERSION);
  }

  if (digitalRead(button) == LOW) {
    delay(100);
    const uint32_t startTime = millis();
    while (digitalRead(button) == LOW) {
      delay(50);
      if (millis() - startTime > 3000) {
        if (otaRunning) {
          Serial.println("OTA in progress, cannot reset now");
          break;
        }
        Serial.println("Resetting Zigbee to factory and rebooting in 1s.");
        delay(1000);
        Zigbee.factoryReset();
      }
    }
    zbLight.setLight(!zbLight.getLightState());
  }
  delay(100);
}
