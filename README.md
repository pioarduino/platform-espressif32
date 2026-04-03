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
-	Python (3.10, 3.11, 3.12, 3.13, 3.14) and git is required for pioarduino to function properly.

## Installation
- [Download and install Microsoft Visual Studio Code](https://code.visualstudio.com/). pioarduino IDE is on top of it.
- Open the extension manager.
- Search for the `pioarduino ide` extension.
- Install pioarduino IDE extension.

## Usage
- Setup new VSCode pioarduino project.
- Check the `platform` setting in platformio.ini file:


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
