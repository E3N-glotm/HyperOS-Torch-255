#!/system/bin/sh

MODDIR=${0%/*}
TAG=HyperTorch255
TARGET=/odm/etc/camera/camxoverridesettings.txt
GENERATED="$MODDIR/.camxoverridesettings.generated"
TMP="$MODDIR/.camxoverridesettings.generated.tmp"
DESIRED_CURRENT=500

log_i() {
  /system/bin/log -p i -t "$TAG" "$*" 2>/dev/null || true
}

log_e() {
  /system/bin/log -p e -t "$TAG" "$*" 2>/dev/null || true
}

fail() {
  log_e "$*"
  rm -f "$TMP"
  exit 1
}

# post-fs-data runs before Camera Provider starts. Work in PID 1's mount namespace explicitly so
# the provider inherits this bind mount. This avoids any runtime HAL/sysfs competition.
[ -x /system/bin/nsenter ] || fail "nsenter is unavailable"
[ -x /system/bin/mount ] || fail "mount is unavailable"

# Refuse to stack over another module's live mount. A normal boot reaches this point with the
# pristine ODM file visible. If this module was invoked twice and its generated file is already
# mounted, the desired value is already active and there is nothing else to do.
MOUNT_LINE="$(/system/bin/nsenter -t 1 -m -- grep " /odm/etc/camera/camxoverridesettings.txt " /proc/self/mountinfo 2>/dev/null | head -n 1)"
if [ -n "$MOUNT_LINE" ]; then
  case "$MOUNT_LINE" in
    *hyperos_torch_255*.camxoverridesettings.generated*)
      if /system/bin/nsenter -t 1 -m -- grep -q "^overrideFlashTorchCurrent=${DESIRED_CURRENT}$" "$TARGET" 2>/dev/null; then
        log_i "HAL override already mounted: ${DESIRED_CURRENT} mA"
        exit 0
      fi
      ;;
    *) fail "refusing to stack over an existing mount at $TARGET" ;;
  esac
fi

# Copy the currently installed firmware file on every boot. This keeps every unrelated OEM camera
# setting in sync across OTA updates; only overrideFlashTorchCurrent is changed below.
/system/bin/nsenter -t 1 -m -- cat "$TARGET" > "$TMP" 2>/dev/null || fail "cannot read pristine $TARGET"

TORCH_LINES="$(grep -c '^overrideFlashTorchCurrent=' "$TMP" 2>/dev/null)"
[ "$TORCH_LINES" = "1" ] || fail "unexpected overrideFlashTorchCurrent count=$TORCH_LINES"
grep -q '^FlashTorchCurrentSwitch=TRUE$' "$TMP" || fail "FlashTorchCurrentSwitch is not TRUE"

ORIGINAL_CURRENT="$(sed -n 's/^overrideFlashTorchCurrent=//p' "$TMP" | head -n 1)"
case "$ORIGINAL_CURRENT" in
  ''|*[!0-9]*) fail "invalid OEM torch current: $ORIGINAL_CURRENT" ;;
esac

sed "s/^overrideFlashTorchCurrent=.*/overrideFlashTorchCurrent=${DESIRED_CURRENT}/" "$TMP" > "$GENERATED" || fail "cannot generate HAL override"
rm -f "$TMP"

[ "$(grep -c '^overrideFlashTorchCurrent=' "$GENERATED" 2>/dev/null)" = "1" ] || fail "generated config validation failed"
grep -q "^overrideFlashTorchCurrent=${DESIRED_CURRENT}$" "$GENERATED" || fail "generated current validation failed"

chown 0:0 "$GENERATED" || fail "cannot chown generated config"
chmod 0644 "$GENERATED" || fail "cannot chmod generated config"
chcon u:object_r:vendor_configs_file:s0 "$GENERATED" 2>/dev/null || fail "cannot apply vendor_configs_file SELinux label"

/system/bin/nsenter -t 1 -m -- /system/bin/mount --bind "$GENERATED" "$TARGET" || fail "PID1 bind mount failed"
/system/bin/nsenter -t 1 -m -- grep -q "^overrideFlashTorchCurrent=${DESIRED_CURRENT}$" "$TARGET" 2>/dev/null || fail "PID1 mount verification failed"

log_i "native Camera HAL torch current ${ORIGINAL_CURRENT} -> ${DESIRED_CURRENT} mA; OEM thermal/kernel safety unchanged"
exit 0
