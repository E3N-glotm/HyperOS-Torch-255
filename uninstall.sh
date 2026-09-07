#!/system/bin/sh

MODDIR=${0%/*}
TEMP_STATE=/sys/class/thermal/thermal_message/temp_state
TEMP_STATE_CANON=/sys/devices/virtual/thermal/thermal_message/temp_state
STOPFILE=/dev/.hyperos_torch255_stop

# Tell the service wrapper not to restart the native daemon, then let SIGTERM trigger the daemon's
# own namespace cleanup. No torch/strobe/thermal sysfs value is changed during uninstall.
touch "$STOPFILE" 2>/dev/null || true
pkill -TERM -f '/hyperos_torch_255/bin/thermal_governor' 2>/dev/null || true
sleep 1

# Crash-safe fallback: remove only this module's PowerKeeper-private bind mount. This immediately
# restores the stock ~57 C user-space policy view, even before the reboot that finalizes Magisk
# module removal.
PID="$(pidof com.miui.powerkeeper 2>/dev/null | awk '{print $1}')"
if [ -n "$PID" ]; then
  while /system/bin/nsenter -t "$PID" -m -- grep -Eq \
      "/adb/modules(_update)?/hyperos_torch_255/.temp_state.filtered ${TEMP_STATE_CANON} " \
      /proc/self/mountinfo 2>/dev/null; do
    /system/bin/nsenter -t "$PID" -m -- /system/bin/umount "$TEMP_STATE" 2>/dev/null || break
  done
fi
rm -f "$MODDIR/.temp_state.filtered" "$STOPFILE"

# Remove state files left by older v1.1/v1.2 hot-upgrade implementations.
rm -f /dev/.hyperos_torch255_pid \
      /dev/.hyperos_torch255_seq \
      /dev/.hyperos_torch255_target \
      /dev/.hyperos_torch255_active \
      /dev/.hyperos_torch255_throttle

/system/bin/log -p i -t HyperTorch255 \
  "module removed; PowerKeeper policy restored now, stock Camera HAL config returns after reboot" \
  2>/dev/null || true
