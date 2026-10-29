# HyperOS Torch 255

**Language: [简体中文](README.md) | English**

Development version: **v1.6.0-alpha.1**. Installation is no longer restricted to a device codename. Read-only capability discovery is independent from high-output calibration: calibrated hardware can enable enhancement; other devices retain stock current and thermal policy and receive an actionable interface report.

## Discovery and compatibility

- Enumerates LED class nodes, recognizes dedicated torch/flashlight LEDs and shared flash/torch nodes with a strobe interface, and resolves duplicate symlinks.
- Reads each driver's `max_brightness`; 255 is not assumed for other devices.
- Inspects CamX files in odm/vendor/product/system vendor and odm directories, including two subdirectory levels; validates unique current keys and enabled OEM switches.
- Identifies flash/torch/LED thermal sensors. Ambiguous sensors are reported instead of substituting a CPU sensor.
- Inventories vendor flashlight, proc and V4L2 paths without guessing ioctls or writing unknown controls.
- Rechecks on each boot/OTA. Changed OEM current values invalidate the old calibration.
- The Magisk action displays candidates, ranges and fallback reasons without turning on the torch.

Only the historical Xiaomi `pudding` profile is calibrated for enhanced output. Other devices can install and diagnose, but increased brightness is **not** claimed to be validated. An LED brightness range does not reveal safe sustained current; the module does not apply the pudding 500 mA value to unknown hardware.

## Calibrated profile

The pudding profile requires the expected LED, 255 range, CamX keys and original 150 mA current, flash_therm and PowerKeeper capabilities. It retains a 500 mA HAL override and an 80°C/75°C hysteresis governor with a stock clamp at 76. Temperature sensor failure clamps enhanced output, removes the private PowerKeeper policy filter and cancels the pending restoration target. Unreadable LED state and failed thermal-state proxy updates restore OEM policy as well.

Kernel thermal trips and PMIC shutdown remain unchanged. No `flash_brightness` writes and no forced `flash_strobe=1`. A driver-terminated session is never reasserted. Namespace filtering is refused if PowerKeeper shares PID 1's mount namespace.

High output increases LED heat; historical tests are not lifetime validation. This revision has fixture-based discovery and native state-machine tests, but no new phone cold-boot or multi-device validation yet.

## Installation

Install the module ZIP with Magisk and reboot. Open its Action page to inspect the capability report. Diagnostic mode preserves stock behavior and starts no enhancement daemon. Disable/uninstall and reboot to restore stock HAL configuration. Do not stack modules altering the same Camera HAL file.

Read-only CLI:

```sh
sh /data/adb/modules/hyperos_torch_255/probe.sh
```

Reports contain device codename, SoC and interface paths, not serial numbers, account data, images or application data. Supporting another enhanced-output profile requires verifying the actual continuous-light channel, current mapping and temperature behavior, rather than adding a codename allowlist.

## Historical device results

The earlier **v1.5.0**, not this revision, was tested on Xiaomi 17 (`pudding`):

| HAL torch current | Observed brightness |
| ---: | ---: |
| 150 mA | 76 |
| 250 mA | 127 |
| 350 mA | 178 |
| 450 mA | 229 |
| 500 mA | 255 |

The earlier device tests covered the native slider reaching 255, an 80.006°C clamp to 76, restoration near 74.9°C, and uninstall/reboot/stock/reinstall rollback. They are historical results and do not validate this revision on other hardware.

The optional RootTorch-v1.0.2 APK from older releases is unchanged. It is not required by the Magisk module and its APK behavior is outside this compatibility change.

## Tests and implementation

```sh
python3 -m unittest discover -s tests -v
```

`lib/discovery.sh` and `probe.sh` implement read-only discovery. The boot manifest is separate from action-page reports, so diagnostic actions cannot change the active configuration. `thermal_governor.c` accepts validated paths/ranges/thresholds and provides a read-only `--check` preflight. CI compiles the native binary from source and packages all scripts.

Interface references: [Linux LED class](https://docs.kernel.org/leds/leds-class.html) and [Linux Flash LED class](https://docs.kernel.org/leds/leds-class-flash.html).
