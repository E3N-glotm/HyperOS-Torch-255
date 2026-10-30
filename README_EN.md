# HyperOS Torch 255

**Language: [简体中文](README.md) | English**

Development version: **v1.7.0-alpha.1**. The installer measures the current native torch through CameraManager and correlates read-only LED samples across off / low / maximum / off stages. The [stable v1.6.0 release](https://github.com/E3N-glotm/HyperOS-Torch-255/releases/latest) is unchanged.

## Installer measurement

The installer scans interfaces and runs an included DEX helper without installing an APK or using LSPosed/Zygisk. Android 13+ devices with strength control report the API maximum and verify the requested level. Older systems measure on/off and default strength only; an unknown maximum remains empty.

Every valid LED class node is observed, including unnamed nodes. Each stage takes three samples. Multiple responding emitters remain a group rather than selecting the first. Zero at the lowest level is permitted for quantization or color-channel switching. Unstable maximum values, invalid ranges, or unconfirmed switch-off do not create a single-channel mapping. If the OEM hides driver nodes, the helper can still report native API success without claiming a readable LED interface.

The helper only controls light through CameraManager; it never writes unknown sysfs nodes or vendor ioctls. Maximum-strength sampling lasts about half a second, with a typical total sequence of 2–3 seconds. Camera busy, torch already on, excessive temperature, incomplete boot, and recovery installs skip the measurement with a reason. The helper has a 10-second hard deadline and the wrapper a 12-second deadline. Normal and exceptional paths close the owned torch session; CameraService reclaims the client's torch token when the helper dies.

## Meaning and reuse

API maximum, observed LED value, and driver max_brightness are different quantities. They do not establish a safe continuous current. Existing HAL overlays are recorded, so readings taken while upgrading an enhanced device are not called pristine stock measurements.

A measured mapping is bound to device, SoC, firmware fingerprint and LED topology. Boot performs read-only revalidation; changed firmware or interfaces invalidate the cached selection. Boot and the Action page never initiate an active light test. Action shows historical measurements and whether the mapping is currently reusable.

A correlated node is a verified observer, not proof that direct sysfs writes are a supported enhancement protocol. Native measurements have no device allowlist and do not require CamX. Enhanced current remains limited to the calibrated pudding / SM8850 profile: 500 mA HAL ceiling, 80/75°C hysteresis and a stock-like clamp of 76. Other hardware retains OEM current and thermal policy pending calibration.

Kernel/PMIC final protections remain. No flash_brightness writes and no forced re-light after driver shutdown. High output increases heat; a short probe is not lifetime validation.

## Installation and manual checks

Install the development ZIP in Magisk, review the short-light-test notice and result, then reboot. Open Action to inspect the API strength, observed driver range, responding channels and environment. Disable/uninstall and reboot to restore stock HAL configuration.

Create /data/adb/hyperos_torch_255/skip_native_probe to skip installer light tests, or set HYPERTORCH_SKIP_NATIVE_PROBE=1 in the installer environment. To actively repeat the test from a Root shell:

```sh
sh /data/adb/modules/hyperos_torch_255/native-probe.sh --output /data/adb/modules/hyperos_torch_255/.native-capabilities
```

The original probe.sh remains read-only. Reports contain device/SoC/build/interface measurements, not serial numbers or personal application data.

## Validation

The development version passes 53 Python/C state-machine and integration checks, 13 Java correlation checks, Android Java/DEX builds and CI packaging. On 2026-10-30, pudding / Android 17 passed the active probe and a real Magisk installation: API maximum 100 mapped to driver value 255, low level read 6, and off readings returned to zero. The helper selected yellow:flash-0 from six LED nodes and correctly recorded the existing HAL overlay.

An already-lit torch was preserved while the probe skipped; user opt-out, mapping reuse and firmware-mismatch rejection were also verified. The installation is staged and a normal reboot/cold-boot check remains pending. Other devices, older Android versions and long-duration operation have not been physically tested. See the [device test record](tests/device-results/pudding_native_probe_20261030.md) for scope.

CI rebuilds both the ARM64 governor and Camera API DEX from source and includes them in the module ZIP.

References: [CameraManager](https://developer.android.com/reference/android/hardware/camera2/CameraManager), [Linux LED class](https://docs.kernel.org/leds/leds-class.html).

