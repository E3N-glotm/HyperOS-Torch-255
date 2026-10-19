#!/system/bin/sh

SKIPMOUNT=true
PROPFILE=false
POSTFSDATA=true
LATESTARTSERVICE=true

NODE="/sys/class/leds/yellow:flash-0"
TARGET="/odm/etc/camera/camxoverridesettings.txt"

ui_print "*******************************"
ui_print " HyperOS Control Center Torch 255"
ui_print "*******************************"
ui_print "Hardware: Xiaomi pudding, capability-verified (ROM-version independent)"

DEVICE="$(getprop ro.product.device)"

if [ "$DEVICE" != "pudding" ]; then
  abort "Unsupported device: $DEVICE. This build is calibrated for pudding only."
fi


if [ ! -r "$TARGET" ]; then
  abort "Required Camera HAL configuration is unavailable: $TARGET"
fi

TORCH_LINES="$(grep -c '^overrideFlashTorchCurrent=' "$TARGET" 2>/dev/null)"
if [ "$TORCH_LINES" != "1" ]; then
  abort "Unexpected Camera HAL config: overrideFlashTorchCurrent count=$TORCH_LINES (expected 1)."
fi

STOCK_CURRENT="$(sed -n 's/^overrideFlashTorchCurrent=//p' "$TARGET" | head -n 1)"
case "$STOCK_CURRENT" in
  ''|*[!0-9]*) abort "Invalid OEM torch current: $STOCK_CURRENT" ;;
esac

if ! grep -q '^FlashTorchCurrentSwitch=TRUE$' "$TARGET"; then
  abort "OEM FlashTorchCurrentSwitch is not enabled; refusing to alter an unknown HAL path."
fi

# Probe required runtime kernel and OEM service interfaces instead of SDK number.
if [ ! -r /sys/class/thermal/thermal_message/temp_state ]; then
  abort "Thermal temp_state capability not available; refuse governor"
fi
if [ ! -r "$NODE/flash_strobe" ] || [ ! -r "$NODE/brightness" ]; then
  abort "Torch strobe and brightness interfaces unavailable"
fi
if ! pm path com.miui.powerkeeper >/dev/null 2>&1; then
  abort "OEM PowerKeeper is absent; the per-process thermal isolation path cannot be verified"
fi
if ! find /sys/class/thermal/thermal_zone*/type -type f -exec grep -l -x flash_therm {} + 2>/dev/null | grep -q .; then
  abort "flash_therm kernel thermal sensor interface absent"
fi

if [ ! -r "$NODE/max_brightness" ]; then
  abort "Required flashlight capability node is unavailable: $NODE/max_brightness"
fi

MAX="$(cat "$NODE/max_brightness" 2>/dev/null)"
if [ "$MAX" != "255" ]; then
  abort "Unexpected kernel brightness range: max_brightness=$MAX (expected 255)."
fi

ui_print "Verified pudding Camera HAL, flash sensor, and PowerKeeper interfaces"
ui_print "OEM overrideFlashTorchCurrent: ${STOCK_CURRENT} mA"
ui_print "Module overrideFlashTorchCurrent: 500 mA"
ui_print "HyperOS still owns the native 1..100 slider and Camera HAL calls."
ui_print "Pure Magisk implementation: no LSPosed, Zygisk or Xposed hook is used."
ui_print "While torch is active, only PowerKeeper sees temp_state with its torch digit neutralized."
ui_print "SystemUI/kernel/thermal HAL and all other processes keep the real thermal sysfs view."
ui_print "Module thermal governor: >=80 C clamp enhanced brightness to 76; <=75 C release."
ui_print "Below 80 C it never writes brightness; flash_strobe and flash_brightness are never written."
ui_print "Kernel thermal trips and PMIC/driver final protection remain unchanged."
ui_print "Disable/uninstall the module and reboot to return the Camera HAL to full stock behavior."

set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/bin/thermal_governor" 0 0 0755
set_perm "$MODPATH/uninstall.sh" 0 0 0755
