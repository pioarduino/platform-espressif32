#include <Arduino.h>
#include <Matter.h>

MatterOnOffLight light;

bool onLightChange(bool state) {
  Serial.printf("Light: %s\n", state ? "on" : "off");
  return true;
}

void setup() {
  Serial.begin(115200);

#ifdef ARDUINO_MATTER_NETWORK_THREAD
  const matterNetwork_t network = MATTER_NETWORK_THREAD;
#else
  const matterNetwork_t network = MATTER_NETWORK_WIFI;
#endif

  if (!Matter.isNetworkSupported(network) || !Matter.isBLECommissioningEnabled() || !Matter.selectNetwork(network)) {
    Serial.println("The selected network or CHIPoBLE is unavailable in this framework build.");
    return;
  }

  if (!light.begin()) {
    Serial.println("Failed to initialize the Matter light.");
    return;
  }
  light.onChange(onLightChange);
  matterSetExampleIdentity("OnOff Light");
  Matter.begin();
  if (!Matter.isStackStarted()) {
    Serial.println("Failed to start Matter.");
    return;
  }
  matterWaitUntilReady();
}

void loop() {
  if (Matter.isStackStarted()) {
    matterRestartIfNoFabric();
  }
  delay(500);
}
