# Arduino Matter Bluetooth Link Libraries

This project exercises the Arduino linker selection with and without the
framework's Matter library. Its Matter sketch is adapted from Espressif's
current [CHIPoBLE Wi-Fi](https://github.com/espressif/arduino-esp32/tree/2a9e5a89cfdefb7343dafaa24bc5f0a97f547cda/libraries/Matter/examples/Commissioning/MatterCHIPoBLEWiFi)
and [CHIPoBLE Thread](https://github.com/espressif/arduino-esp32/tree/2a9e5a89cfdefb7343dafaa24bc5f0a97f547cda/libraries/Matter/examples/Commissioning/MatterCHIPoBLEThread)
examples. Unlike those sketches, it reports light changes over serial and does
not use an LED or a decommissioning button.

| Board | Matter environment | Control environment | Matter network |
| --- | --- | --- | --- |
| ESP32-C3-DevKitM-1 | `c3-matter` | `c3-control` | Wi-Fi |
| ESP32-C5-DevKitC-1 | `c5-matter` | `c5-control` | Wi-Fi |
| ESP32-H2-DevKitM-1 | `h2-matter` | `h2-control` | Thread |

It requires Arduino >= 4.0.0 with the matching prebuilt libraries that include
Matter, CHIPoBLE, and, for the C5, `libespressif__esp_matter.wifi.a`. The
Matter-specific Bluetooth archive is optional: the linker falls back to
`libbt.a` when `libbt.matter.a` is absent.

## Verify the link

From this directory, clean and build a Matter environment and its control:

```sh
pio run -e c3-matter -t clean
pio run -e c3-matter -v
pio run -e c3-control -t clean
pio run -e c3-control -v
```

Repeat with the `c5` and `h2` pairs. In each verbose final firmware link
command, check the following:

- Matter build, with `libbt.matter.a` present for that chip: every standalone
  `-lbt` is replaced by `-lbt.matter`.
- Control build, or Matter build without that archive: `-lbt` remains
  unchanged. Other libraries, such as `-lbtdm_app`, are not renamed.

The archive must exist under the selected `framework-arduinoespressif32-libs`
package's `<chip>/lib/` directory. The control builds do not
include Matter, even when the Matter archive is installed. A clean build makes
the link command visible even when the firmware was already up to date.

## Run the Matter sketch

Upload the matching Matter environment and open its serial monitor at 115200.
Commission using the pairing information printed by the sketch. A Matter
controller is required; the H2 additionally needs a Thread border router. The
controller supplies the Wi-Fi credentials or Thread dataset over CHIPoBLE.
The sketch does not configure either network itself.
