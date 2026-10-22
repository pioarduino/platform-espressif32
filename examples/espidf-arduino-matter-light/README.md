# Arduino ESP-Matter over WiFi (Thread) example using ESP32-C6
This is an Arduino as IDF Project to build an ESP-Matter over WiFi or Thread RGB Light using ESP32-C6 and ESP-Matter Arduino API \

Example from [ESP32 Matter Library examples](https://github.com/espressif/arduino-esp32/tree/master/libraries/Matter/examples)

The `main/idf_component.yml` file holds the ESP-Matter component.\

# Instructions:

1- Compile with `pio run`

2- Try to add the Matter RGB light to your Matter environment.

# Thread variant:

1- Rename `sdkconfig.defaults` to `sdkconfig.defaults.wifi` and `sdkconfig.defaults.thread` to `sdkconfig.defaults`

2- Compile with `pio run`

3- Try to add the Matter RGB light to your Matter environment.
