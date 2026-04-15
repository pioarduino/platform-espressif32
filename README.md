# pioarduino (p)eople (i)nitiated (o)ptimized (arduino)

[![Build Status](https://github.com/pioarduino/platform-espressif32/actions/workflows/examples.yml/badge.svg)](https://github.com/pioarduino/platform-espressif32/actions)
[![Discord](https://img.shields.io/discord/1263397951829708871.svg?logo=discord&logoColor=white&color=5865F2&label=Discord)](https://discord.gg/Nutz9crnZr)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/pioarduino/platform-espressif32)
[![GitHub latest release](https://img.shields.io/github/downloads/pioarduino/platform-espressif32/total?label=Downloads)](https://github.com/pioarduino/platform-espressif32/releases/latest)
[![Downloads latest release](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.github.com%2Frepos%2Fespressif%2Farduino-esp32%2Freleases%2Flatest&query=%24.assets%5B0%5D.download_count&label=Downloads%20latest)](https://github.com/pioarduino/platform-espressif32/releases/latest)

Espressif Systems is a privately held, fabless semiconductor company renowned for delivering cost-effective wireless communication microcontrollers. Their innovative solutions are widely adopted in mobile devices and Internet of Things (IoT) applications around the globe.

## General
* **Do not open issues with this experimental build**
- Feedback in Discord to fix bugs is welcome.
- **NO** questions how to use and when something is not working as expected

**You walk alone using this experimental setup!**

Prerequisites:
-	Python (3.10, 3.11, 3.12, 3.13 or 3.14) and git is required for pioarduino to function properly.

## Installation

### VSCode Extension
- [Download and install Microsoft Visual Studio Code](https://code.visualstudio.com/). pioarduino IDE is on top of it.
- Open the extension manager.
- Search for the `pioarduino ide` extension.
- Install pioarduino IDE extension.

### CLI
```bash
curl -fsSL -o get-platformio.py https://raw.githubusercontent.com/pioarduino/pioarduino-core-installer/pioarduino/get-platformio.py
python3 get-platformio.py
source ~/.platformio/penv/bin/activate
```
> **Note:** The pioarduino platform installer automatically fixes the virtual environment if a conflict with the system Python is detected.

## Usage

### VSCode
Setup new VSCode pioarduino project.

### CLI
```bash
mkdir my-project && cd my-project
pio project init --board esp32dev
```

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


## Experimental Arduino 4.0 based on IDF 6.0
pioarduino Arduino repo branch `release/v4.0.x`, used to compile Arduino libs with IDF 6.0

```ini
[env:experimental]
platform = https://github.com/pioarduino/platform-espressif32.git#prep_IDF6
board = ...
...
```

## Removed
- Matter
- Rainmaker
- Speech recognition

## Known limitations / bugs
- Ethernet PHY (wired Ethernet) is not implemented in Arduino


Looking for sponsor button? There is none. If you want to donate, please spend a litte to a charity organization.
