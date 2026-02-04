# pioarduino (p)eople (i)nitiated (o)ptimized (arduino)

[![Build Status](https://github.com/pioarduino/platform-espressif32/actions/workflows/examples.yml/badge.svg)](https://github.com/pioarduino/platform-espressif32/actions)
[![Discord](https://img.shields.io/discord/1263397951829708871.svg?logo=discord&logoColor=white&color=5865F2&label=Discord)](https://discord.gg/Nutz9crnZr)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/pioarduino/platform-espressif32)
[![GitHub latest release](https://img.shields.io/github/downloads/pioarduino/platform-espressif32/total?label=Downloads)](https://github.com/pioarduino/platform-espressif32/releases/latest)
[![Downloads latest release](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.github.com%2Frepos%2Fespressif%2Farduino-esp32%2Freleases%2Flatest&query=%24.assets%5B0%5D.download_count&label=Downloads%20latest)](https://github.com/pioarduino/platform-espressif32/releases/latest)

Espressif Systems is a privately held, fabless semiconductor company renowned for delivering cost-effective wireless communication microcontrollers. Their innovative solutions are widely adopted in mobile devices and Internet of Things (IoT) applications around the globe.

## General
* Issues with boards (wrong / missing). All issues caused from boards will not be fixed from the maintainer(s). A PR needs to be provided against branch `develop` to solve.
* No support for the Arduino Nora Nano board, issues needs to be solved by the community
## IDE Preparation
Prerequisites:
-	Python (3.10, 3.11, 3.12, 3.13, 3.14) and git is required for pioarduino to function properly.

## Installation
- [Download and install Microsoft Visual Studio Code](https://code.visualstudio.com/). pioarduino IDE is on top of it.
- Open the extension manager.
- Search for the `pioarduino ide` extension.
- Install pioarduino IDE extension.

## Usage
1. Setup new VSCode pioarduino project.
1. Check the `platform` setting in platformio.ini file:

## Documentation
[pioarduino Wiki](https://deepwiki.com/pioarduino/platform-espressif32)
The Wiki is AI generated and insane detailed and accurate.

# Features

## Filesystem Support

pioarduino provides native support for multiple filesystem options, allowing you to choose the best solution for your project's needs:

- **LittleFS** (default) - Modern wear-leveling filesystem designed specifically for flash memory. Offers excellent reliability and performance for ESP32 projects.
- **SPIFFS** - Simple legacy filesystem. While still functional, LittleFS is recommended for new projects due to better wear-leveling and reliability.
- **FatFS** - Industry-standard FAT filesystem with broad compatibility across platforms and operating systems.

### FatFS Integration

FatFS support has been fully integrated as a Python module, providing the same seamless experience as LittleFS. Configuration is straightforward - simply specify your preferred filesystem in your project settings: See [FATFS_INTEGRATION.md](FATFS_INTEGRATION.md) for detailed documentation.

**Quick Start:**

```ini
[env:myenv]
board_build.filesystem = fatfs
```

**Available Commands:**

```bash
pio run -t buildfs        # Build FatFS image
pio run -t uploadfs       # Upload FatFS image
pio run -t download_fatfs # Download and extract FatFS from device
```

See the [arduino-fatfs example](examples/arduino-fatfs/) for a complete working example.

### Stable Arduino
currently espressif Arduino 3.3.6 and IDF v5.5.2.260116

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

###  ESP32-C2, ESP32-C61 and ESP32-solo1 Arduino support (via pioarduino only feature: *Hybrid compile*)
Example configuration:

```ini
[env:esp32-c2-devkitm-1]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
framework = arduino
board = esp32-c2-devkitm-1
monitor_speed = 115200

[env:esp32-c61-devkitc1-n8r2]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
framework = arduino
board = esp32-c61-devkitc1-n8r2
monitor_speed = 115200

[env:esp32solo1]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
framework = arduino
board = esp32-solo1
monitor_speed = 115200

```

Looking for sponsor button? There is none. If you want to donate, please spend a litte to a charity organization.
