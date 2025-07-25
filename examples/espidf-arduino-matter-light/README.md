| Supported Targets | ESP32-C3 | ESP32-C6 |
| ----------------- | -------- | -------- |


# Managed Component Light

This example is configured by default to work with the ESP32-C6, which has the RGB LED GPIO set as pin 8 and the BOOT button on GPIO 9.

This example creates a Color Temperature Light device using the esp_matter component automatically downloaded from the [Espressif Component Registry](https://components.espressif.com/). See the [docs](https://docs.espressif.com/projects/esp-matter/en/latest/esp32/developing.html) for more information about matter.

The code is based on the Arduino API and uses Arduino as an IDF Component.

## How to use it

Once the device runs for the first time, it must be commissioned to the Matter Fabric of the available Matter Environment.
Possible Matter Environments are:
- Amazon Alexa
- Google Home Assistant (*)
- Apple Home
- Open Source Home Assistant

(*) Google Home Assistant requires the user to set up a Matter Light using the [Google Home Developer Console](https://developers.home.google.com/codelabs/matter-device#2). It is necessary to create a Matter Light device with VID = 0xFFF1 and PID = 0x8000. Otherwise, the Light won't show up in the GHA APP. This action is necessary because the Firmware uses Testing credentials and Google requires the user to create the testing device before using it.

There is no QR Code to be used when the Smartphone APP wants to add the Matter Device.
Please enter the code manually: `34970112332`

The devboard has a built-in LED that will be used as the Matter Light.
The default setting of the code uses pin 8 for the ESP32-C6,
Please change it in `main/matter_accessory_driver.h` or in the `sdkconfig.defaults` file.

## LED Status and Factory Mode

The WS2812b built-in LED will turn purple as soon as the device is flashed and runs for the first time.
The purple color indicates that the Matter Accessory has not been commissioned yet.
After using a Matter provider Smartphone APP to add a Matter device to your Home Application, it may turn orange to indicate that it has no WiFi connection.

Once it connects to the WiFi network, the LED will turn white to indicate that Matter is working and the device is connected to the Matter Environment.
Please note that Matter over WiFi using an ESP32 device will connect to a 2.4GHz WiFi SSID, therefore the Commissioner APP Smartphone shall be connected to this SSID.

The Matter and WiFi configuration will be stored in NVS to ensure that it will connect to the Matter Fabric and WiFi Network again once it is reset.

The Matter Smartphone APP will control the light state (ON/OFF), temperature (Warm/Cold White), and brightness.

## On Board Light toggle button

The built-in BOOT button will toggle On/Off and replicate the new state to the Matter Environment, making it visible in the Matter Smartphone APP as well.

## Returning to the Factory State

Holding the BOOT button pressed for more than 10 seconds and then releasing it will erase all Matter and WiFi configuration, forcing it to reset to factory state. After that, the device needs to be commissioned again. Previous setups done in the Smartphone APP won't work again; therefore, the virtual device shall be removed from the APP.

## Building the Application using WiFi and Matter

This example has been tested with Arduino Core 3.2.0. It should work with newer versions too.

There is a configuration file for these SoCs: esp32c3, esp32c6.
Those are the tested devices that have a WS2812 RGB LED and can run BLE, WiFi and Matter.

In case it is necessary to change the Button Pin or the REG LED Pin, please use the `menuconfig` and change the Menu Option `Light Matter Accessory`

## Using OpenThread with Matter

This is possible with the ESP32-C6.
It is necessary to have a Thread Border Router in the Matter Environment. Check your Matter hardware provider.

