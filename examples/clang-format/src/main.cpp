/*
 * clang-format example for pioarduino / platform-espressif32
 *
 * Check the formatting (this is what CI runs):
 *   pio run -t clangformat
 *
 * Apply the formatting:
 *   pio run -t clangformat-write
 */

#include <Arduino.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

namespace {

constexpr uint32_t kBlinkIntervalMs = 500;

struct BlinkState {
  bool led_on;
  uint32_t last_toggle_ms;
};

BlinkState state = {false, 0};

}  // namespace

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
  Serial.println("clang-format example");
}

void loop() {
  const uint32_t now = millis();
  if (now - state.last_toggle_ms < kBlinkIntervalMs) {
    return;
  }

  state.led_on = !state.led_on;
  state.last_toggle_ms = now;
  digitalWrite(LED_BUILTIN, state.led_on ? HIGH : LOW);
}
