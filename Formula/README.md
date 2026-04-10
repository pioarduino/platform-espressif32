# Homebrew Tap for pioarduino

## Installation

```bash
# Add the tap
brew tap pioarduino/pioarduino https://github.com/pioarduino/homebrew-pioarduino

# Install pioarduino
brew install pioarduino/pioarduino/pioarduino
```

Or as a one-liner:

```bash
brew install pioarduino/pioarduino/pioarduino
```

## What gets installed

- **pioarduino** (PlatformIO Core fork v6.1.19) — provides the `pio`, `platformio`, and `piodebuggdb` CLI commands
- **platform-espressif32** (stable) — registered as the default ESP32 platform
- **Python dependencies** for PlatformIO core (via Homebrew virtualenv)
- **uv** (dependency) — used by pioarduino at runtime to install build-time Python packages (esptool, littlefs-python, cryptography, etc.) into an isolated virtual environment

## Runtime behavior

When you first build an ESP32 project, pioarduino will:

1. Create a Python virtual environment using `uv`
2. Install ESP32-specific Python packages (esptool, littlefs-python, fatfs-ng, cryptography, etc.)
3. Download the required toolchains (xtensa-gcc, riscv-gcc, etc.)

This all happens automatically — no manual `pip install` needed.

## Usage

```bash
# Create a new project
mkdir my-project && cd my-project
pio project init --board esp32dev

# Build
pio run

# Upload
pio run --target upload

# Serial monitor
pio device monitor
```

## Uninstall

```bash
brew uninstall pioarduino
brew untap pioarduino/pioarduino
```

## Conflicts

This formula conflicts with the official `platformio` Homebrew formula since both provide the `pio` command. Uninstall one before installing the other:

```bash
brew uninstall platformio  # if installed
brew install pioarduino/pioarduino/pioarduino
```
