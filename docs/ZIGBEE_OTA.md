# Zigbee OTA images

Arduino-only builds with `ZIGBEE_MODE_ED` or `ZIGBEE_MODE_ZCZR` generate a Zigbee
OTA image after building the application binary, using the Arduino framework's
`tools/zb_ota_image.py`. The image is written to `.pio/build/<environment>/`
as `<manufacturer>-<image type>-<file version>-ota-file.zigbee`. The generator
runs when the application binary is rebuilt, not when it is already up to date.
Images from earlier versions remain in the build directory.

For example, set the Zigbee mode in `platformio.ini`:

```ini
build_flags = -DZIGBEE_MODE_ED
```

Define the OTA metadata as literal integers in a source file directly inside
the project's source directory (`src/` by default), as in the Arduino Zigbee
OTA light example:

```cpp
#define OTA_UPGRADE_MANUFACTURER 0x1001
#define OTA_UPGRADE_IMAGE_TYPE 0x1011
#define OTA_UPGRADE_RUNNING_FILE_VERSION 0x01010100
```

The upstream generator also accepts `OTA_UPGRADE_FILE_VERSION`, and uses it in
preference to `OTA_UPGRADE_RUNNING_FILE_VERSION`. Manufacturer and image type
default to `0x1001` and `0x1011`; a version is required. Optional header and
hardware-version fields are supported by the upstream generator. It scans only
files directly in the source directory, not `include/`, subdirectories, or
preprocessor definitions supplied through `build_flags`.

Like the Arduino IDE hook, the generator skips projects without usable OTA
metadata. It only creates the file; an OTA server and an OTA-enabled client are
required to deliver and install it. Framework versions without the generator
cannot produce an image.
