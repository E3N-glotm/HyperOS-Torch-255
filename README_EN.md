# HyperOS Torch 255

[简体中文](README.md) | **English**

A Magisk flashlight enhancement module for Xiaomi 17 (`pudding`, Android 16 / HyperOS). It keeps the stock HyperOS Control Center flashlight and strength slider, while extending the maximum continuous output to the normal driver `brightness` ceiling of `255`, without replacing SystemUI or relying on LSPosed/Zygisk/Xposed.

> [!WARNING]
> This module substantially increases sustained LED output and heat. `100% / brightness=255` should be treated as an extreme mode, not a normal long-duration lighting level. Kernel, Camera HAL and PMIC final protections remain in place, but that does not make sustained high-temperature operation risk-free.

## Compatibility

- Validated device: **Xiaomi 17**
- Codename: **`pudding`**
- Validated OS: Android 16 / HyperOS
- Root: Magisk
- Module architecture: AArch64

The module contains Xiaomi 17-specific Camera HAL keys, LED sysfs paths and PowerKeeper thermal-state handling. **Other devices have not been validated and should not be assumed compatible.**

## Features

- Keeps the native HyperOS Control Center flashlight UI and strength slider.
- Systemlessly changes Camera HAL `overrideFlashTorchCurrent` from stock `150` to `500`.
- On the validated Xiaomi 17, native `strength=100` changes from roughly `brightness=76` to `brightness=255`.
- Only while a torch session is active, filters the final torch-state digit of the `temp_state` view seen by PowerKeeper; the rest of the system continues to see the real thermal sysfs state.
- Narrow module-side thermal governor:
  - at `flash_therm >= 80°C`, enhanced brightness is reduced to the stock-like `76`;
  - at `flash_therm <= 75°C`, the previous user target is restored if the torch session is still active;
  - 80/75°C hysteresis prevents rapid boundary oscillation.
- Does not change kernel thermal trips.
- Never writes `flash_brightness`, so photo-flash burst current is not requested as continuous illumination.
- Never re-asserts `flash_strobe=1`; if the driver, kernel or PMIC shuts the LED down, the module does not force it back on.
- Fully systemless Magisk installation; uninstall + reboot restores the stock Camera HAL view and PowerKeeper behavior.

## Validated Results

Observed Camera HAL current mapping on the test device:

| Torch current | `yellow:flash-0/brightness` |
| ---: | ---: |
| 150 mA | 76 |
| 250 mA | 127 |
| 350 mA | 178 |
| 450 mA | 229 |
| 500 mA | 255 |

The v1.5.0 device validation covered:

- Native HyperOS slider maximum: `yellow:flash-0 = 255`, `flash_strobe = 1`.
- Enhanced brightness remained active at approximately 77.6°C `flash_therm`.
- At `flash_therm = 80.006°C`, the governor reduced `255` to `76`.
- At roughly 74.9°C, the prior enhanced target was restored.
- A full rollback loop was completed: uninstall → reboot → verify stock → reinstall → reboot → verify enhanced mode again.

## Installation

1. Download `HyperOS-Torch-255-v1.5.0.zip` from [Releases](../../releases).
2. In Magisk, choose installation from local storage and select the ZIP.
3. Reboot.
4. Continue using the stock HyperOS Control Center flashlight and strength slider.

The release also contains the optional `RootTorch-v1.0.2.apk`. It is a standalone root torch controller and is **not required** for the Magisk module itself:

- after installation, tap **Get Root** once and approve RootTorch in your root manager;
- after the first successful grant, the app remembers that the explicit grant was completed;
- later launches automatically recreate the app's `su` session using the authorization already persisted by the root manager;
- if root authorization is revoked/reset or automatic connection fails, the app falls back to an explicit **Get Root Again** action.

## Uninstall

Remove the module in Magisk and reboot.

The v1.5.0 rollback validation confirmed that after removal and reboot:

- `/data/adb/modules/hyperos_torch_255` is gone;
- the module thermal governor no longer runs;
- no module `temp_state` proxy mount remains in the PowerKeeper namespace;
- the system view of `/odm/etc/camera/camxoverridesettings.txt` returns to stock `overrideFlashTorchCurrent=150`;
- stock `strength=100` returns to approximately `brightness=76`.

The ROM partitions are never permanently modified.

## How It Works

The normal HyperOS flashlight chain remains intact:

```text
MiFlashlightActivity
  -> Camera2 torch strength 1..100
  -> Xiaomi/QCOM Camera HAL
  -> PMIC
  -> /sys/class/leds/yellow:flash-0
```

### 1. Camera HAL ceiling

The stock `/odm/etc/camera/camxoverridesettings.txt` contains:

```text
overrideFlashTorchCurrent=150
```

At boot, the module copies the pristine ROM configuration, validates the expected keys, changes only that setting to `500`, applies the normal vendor configuration SELinux label, and presents the generated copy to Camera HAL with a Magisk/systemless bind mount before Camera Provider starts.

It does not modify `overrideFlashVideoLightCurrent`, `overrideFlashPreviewLightCurrent`, `overrideTorchScanCurrent`, `overrideFlashSnapshotLightCurrent`, or `FlashTorchTemperatureLevels`.

### 2. HyperOS early thermal shutoff around 57°C

Device investigation traced the early torch policy to `com.miui.powerkeeper`, which reads:

```text
/sys/class/thermal/thermal_message/temp_state
```

and emits `action_temp_state_change`. SystemUI/plugin logic interprets the final decimal digit of this composite value as the torch thermal state and can reduce or force-off the torch for selected states.

v1.5.0 does not globally fake thermal state. While the physical torch session is active, a short-lived helper enters **only PowerKeeper's mount namespace** and replaces that one path with a read-only module proxy. The proxy preserves the higher-order composite thermal state and filters only the final torch-state digit to `0`. Other processes and the kernel continue reading the real sysfs file. The proxy mount is removed immediately when the torch session ends.

### 3. Module 80/75°C governor

The same native AArch64 process samples `flash_therm`, `yellow:flash-0/brightness` and `flash_strobe` every 100 ms. Below 80°C it does not remap the native slider. At 80°C, only enhanced values above the stock level are clamped to `76`; at 75°C the previous user target is restored once if the session remains active.

This is an additional policy layer. It does not replace kernel or PMIC final protections.

The native governor source is available at [`src/thermal_governor.c`](src/thermal_governor.c). The `bin/thermal_governor` file shipped in the Release/Magisk package is the corresponding AArch64 Android executable.

## RootTorch v1.0.2

The companion APK keeps package name `io.e3n.roottorch`. v1.0.2 changes only the root authorization UX: the user explicitly grants root once, then subsequent launches automatically reuse the authorization persisted by the root manager and create a fresh long-lived `su` shell for the current app process.

The app does not store a root password, Magisk token or secret. Its local preference only records a boolean indicating that the user previously completed a successful grant; the root manager remains authoritative.

> Per request, v1.0.2 received local source review, build validation and APK static verification only. No new phone-side validation was performed for this APK build. The v1.5.0 module hardware/thermal results above come from the earlier Xiaomi 17 device validation.

## Safety Boundaries

- No kernel thermal-trip modification.
- No bypass of PMIC/driver final shutdown.
- No `flash_brightness` writes.
- No forced `flash_strobe=1` persistence.
- Enhanced 100% output produces substantial heat; avoid unnecessary sustained high-temperature use.

## Versions

- Magisk module: **v1.5.0 / versionCode 150**
- Companion APK: **RootTorch v1.0.2 / versionCode 12**

