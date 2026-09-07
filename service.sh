#!/system/bin/sh

MODDIR=${0%/*}
BIN="$MODDIR/bin/thermal_governor"
PROXY="$MODDIR/.temp_state.filtered"
TEMP_STATE=/sys/class/thermal/thermal_message/temp_state
TEMP_STATE_CANON=/sys/devices/virtual/thermal/thermal_message/temp_state
STOPFILE=/dev/.hyperos_torch255_stop
TAG=HyperTorch255

[ -x "$BIN" ] || exit 1

log_i() {
  /system/bin/log -p i -t "$TAG" "$*" 2>/dev/null || true
}

log_e() {
  /system/bin/log -p e -t "$TAG" "$*" 2>/dev/null || true
}

powerkeeper_pid() {
  pidof com.miui.powerkeeper 2>/dev/null | awk '{print $1}'
}

cleanup_filter_mount() {
  PID="$(powerkeeper_pid)"
  [ -n "$PID" ] || return 0

  # Only remove mounts whose source is this module's proxy. Never unmount an unrelated module or
  # the stock sysfs node. Accept both the active module path and modules_update so a staged upgrade
  # can be hot-tested safely before reboot. Repeated unmount handles an interrupted older launch.
  while /system/bin/nsenter -t "$PID" -m -- grep -Eq \
      "/adb/modules(_update)?/hyperos_torch_255/.temp_state.filtered ${TEMP_STATE_CANON} " \
      /proc/self/mountinfo 2>/dev/null; do
    /system/bin/nsenter -t "$PID" -m -- /system/bin/umount "$TEMP_STATE" 2>/dev/null || break
  done
}

rm -f "$STOPFILE"
cleanup_filter_mount

# The proxy is a regular module-owned file. While the torch is physically active the native daemon
# bind-mounts it ONLY inside com.miui.powerkeeper's private mount namespace. The daemon continuously
# copies the real composite temp_state with only its decimal torch-state digit forced to 0. SystemUI,
# the kernel, thermal HAL and every other process keep seeing the real sysfs node.
REAL_STATE="$(cat "$TEMP_STATE" 2>/dev/null)"
case "$REAL_STATE" in
  ''|*[!0-9]*) REAL_STATE=0 ;;
esac
FILTERED_STATE=$((REAL_STATE - (REAL_STATE % 10)))
printf '%s\n' "$FILTERED_STATE" > "$PROXY" || exit 1
chown 0:0 "$PROXY" || exit 1
chmod 0644 "$PROXY" || exit 1
chcon u:object_r:hypertorch_temp_state:s0 "$PROXY" 2>/dev/null || {
  log_e "cannot label temp_state proxy with hypertorch_temp_state"
  exit 1
}

export HYPERTORCH_TEMP_STATE_PROXY="$PROXY"

# Do not exec the daemon: this wrapper is the fail-safe cleanup owner. If the native process exits
# unexpectedly, its PowerKeeper-only bind mount is removed before any restart is attempted.
while [ ! -e "$STOPFILE" ] && [ ! -e "$MODDIR/disable" ] && [ ! -e "$MODDIR/remove" ]; do
  "$BIN"
  RC=$?
  cleanup_filter_mount
  [ -e "$STOPFILE" ] && break
  [ -e "$MODDIR/disable" ] && break
  [ -e "$MODDIR/remove" ] && break
  log_e "thermal governor exited rc=$RC; PowerKeeper filter restored; retry in 2s"
  sleep 2
done

cleanup_filter_mount
rm -f "$PROXY" "$STOPFILE"
log_i "service stopped; stock PowerKeeper temp_state view restored"
exit 0
