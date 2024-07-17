# Fork of Platformio Espressif 32: development platform for [PlatformIO](https://platformio.org)

> [!NOTE]  
> This fork was created due to the lack of ongoing development for the Espressif 32 Arduino Core in the PlatformIO registry to support developers who have used PlatformIO for their ESP32 projects.
>
> For additional information, please refer to these GitHub links:
> 
> https://github.com/espressif/arduino-esp32/discussions/10039
> https://github.com/platformio/platform-espressif32/issues/1225
> https://github.com/espressif/arduino-esp32/pull/8606
>
> The discussions are self-explanatory, allowing you to draw your own conclusions.

[![Build Status](https://github.com/pioarduino/platform-espressif32/workflows/Examples/badge.svg)](https://github.com/pioarduino/platform-espressif32/actions)

ESP32 is a series of low-cost, low-power system on a chip microcontrollers with integrated Wi-Fi and Bluetooth. ESP32 integrates an antenna switch, RF balun, power amplifier, low-noise receive amplifier, filters, and power management modules.

* [Documentation](https://docs.platformio.org/page/platforms/espressif32.html) (advanced usage, packages, boards, frameworks, etc.)

# Usage

1. [Install PlatformIO](https://platformio.org)
2. Create PlatformIO project and configure a platform option in [platformio.ini](https://docs.platformio.org/page/projectconf.html) file:

## Stable version
espressif Arduino 3.0.3 and IDF 5.1.4

See `platform` [documentation](https://docs.platformio.org/en/latest/projectconf/sections/env/options/platform/platform.html#projectconf-env-platform) for details.

```ini
[env:stable]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/51.03.03/platform-espressif32.zip
board = ...
...
```

## Development version

```ini
[env:development]
platform = https://github.com/pioarduino/platform-espressif32.git#development
board = ...
...
```

# Configuration

Please navigate to [documentation](https://docs.platformio.org/page/platforms/espressif32.html).
