#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  Serial.println("Arduino build without Matter");
}

void loop() {
  delay(1000);
}
