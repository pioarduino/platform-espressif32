# pioarduino (p)eople (i)nitiated (o)ptimized (arduino)

[![Build Status](https://github.com/pioarduino/platform-espressif32/workflows/Examples/badge.svg)](https://github.com/pioarduino/platform-espressif32/actions)
[![Discord](https://img.shields.io/discord/1263397951829708871.svg?logo=discord&logoColor=white&color=5865F2&label=Discord)](https://discord.gg/Nutz9crnZr)
[![GitHub Releases](https://img.shields.io/github/downloads/pioarduino/platform-espressif32/total?label=downloads)](https://github.com/pioarduino/platform-espressif32/releases/latest)

ESP32 is a series of low-cost, low-power system on a chip microcontrollers with integrated Wi-Fi and Bluetooth. ESP32 integrates an antenna switch, RF balun, power amplifier, low-noise receive amplifier, filters, and power management modules.

* Issues with boards (wrong / missing). All issues caused from boards will not be fixed from the maintainer(s). A PR needs to be provided against branch `develop` to solve.

## IDE Preparation

- [Download and install official Microsoft Visual Studio Code](https://code.visualstudio.com/). pioarduino IDE is built on top of it.
- Open the extension manager.
- Search for the `pioarduino ide` extension.
- Install pioarduino IDE extension.

# Usage
1. Setup new VSCode pioarduino project.
1. Configure a platform option in platformio.ini file:

### Stable Arduino
currently espressif Arduino 3.1.0 and IDF 5.3.2.241210

```ini
[env:stable]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board = ...
...
```

### Development Arduino
espressif Arduino repo branch master and latest compiled Arduino libs

```ini
[env:development]
platform = https://github.com/pioarduino/platform-espressif32.git#develop
board = ...
...
```

### ESP32-solo1 and ESP32-C2 Arduino support (with pioarduino only feature: *Hybrid compile*)
Example configuration:

```ini
[env:esp32solo1]
platform = https://github.com/pioarduino/platform-espressif32.git#develop
framework = arduino
board = esp32-solo1
monitor_speed = 115200

[env:esp32-c2-devkitm-1]
platform = https://github.com/pioarduino/platform-espressif32.git#develop
framework = arduino
board = esp32-c2-devkitm-1
monitor_speed = 115200
```

Looking for sponsor button? There is none. If you want to donate, please spend a litte to a charity organization.
