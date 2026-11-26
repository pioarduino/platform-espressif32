# Zigbee OTA Client Example

This example turns an ESP32-H2 or ESP32-C6 into a Zigbee end-device light with a Zigbee OTA Upgrade client. It accepts full OTA images (not delta images) and requires a dual-application partition table.

## Build and upload

Build or upload one of the configured environments:

```sh
pio run -e esp32-h2-devkitm-1
pio run -e esp32-c6-devkitc-1
pio run -e esp32-h2-devkitm-1 -t upload
```

The configurations select dual-OTA partition tables (`zigbee.csv` for H2 and `zigbee_8MB.csv` for C6). Join the device to a Zigbee coordinator that provides an OTA Upgrade server, such as Home Assistant ZHA or the ESP Zigbee SDK `ota_server` example.

## Generate and install an OTA image

When available in the installed Arduino framework, its OTA image generator runs after the application binary is rebuilt and writes the `.zigbee` image under `.pio/build/<environment>/`. The image metadata is read from the sketch:

- `OTA_UPGRADE_MANUFACTURER` and `OTA_UPGRADE_IMAGE_TYPE` must match the OTA client and server.
- `OTA_UPGRADE_RUNNING_FILE_VERSION` is the currently running firmware version and is also placed in the generated image. Increment it for each new update image.
- Keep `OTA_UPGRADE_DOWNLOADED_FILE_VERSION` at `0xFFFFFFFF` unless tracking an already stored image.

To update a device, first flash and join the initial version over USB. Then increment `OTA_UPGRADE_RUNNING_FILE_VERSION` and rebuild without uploading. The OTA image version must be greater than the version running on the device.

For Home Assistant ZHA, copy the generated `.zigbee` file into `/config/zigpy_ota` and configure the advanced OTA provider in `configuration.yaml`:

```yaml
zha:
  zigpy_config:
    ota:
      extra_providers:
        - type: advanced
          path: /config/zigpy_ota
          warning: >-
            I understand I can *destroy* my devices by enabling OTA updates from files.
            Some OTA updates can be mistakenly applied to the wrong device, breaking it.
            I am consciously using this at my own risk.
```

Reload the ZHA integration and start the update from the device page.

The sketch requests an update after joining the network and periodically thereafter. It reports OTA state and the running firmware version on the serial monitor. Hold the BOOT button for three seconds to factory-reset Zigbee; a reset is blocked while an OTA transfer is active.
