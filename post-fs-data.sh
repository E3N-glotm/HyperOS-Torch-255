#!/system/bin/sh
MODDIR=${0%/*}
. "$MODDIR/lib/discovery.sh"
REPORT="$MODDIR/.runtime-capabilities"
TMP="$MODDIR/.camxoverridesettings.generated.tmp"
GENERATED="$MODDIR/.camxoverridesettings.generated"
log_i() { /system/bin/log -p i -t HyperTorch255 "$*" 2>/dev/null || true; }
fail() {
  rm -f "$TMP" "$MODDIR/.hal-ready"
  ht_status "$MODDIR" "未启用增强 | $*"
  log_i "$*"
  exit 1
}
# Read-only discovery runs again after every boot/OTA; never reuse installer paths.
rm -f "$MODDIR/.hal-ready"
sh "$MODDIR/probe.sh" --output "$REPORT" || fail "接口检测失败"
[ "$(ht_field "$REPORT" mode)" = calibrated ] || {
  ht_status "$MODDIR" "仅诊断 | $(ht_reason_zh "$(ht_field "$REPORT" reason)")"
  exit 0
}
TARGET=$(ht_field "$REPORT" hal)
DESIRED_CURRENT=$(ht_field "$REPORT" target_current_ma)
[ -x /system/bin/nsenter ] && [ -x /system/bin/mount ] || fail "缺少挂载工具"

MOUNT_LINE=$(/system/bin/nsenter -t 1 -m -- awk -v target="$(ht_realpath "$TARGET")" '$5 == target {print}' /proc/self/mountinfo 2>/dev/null)
if [ -n "$MOUNT_LINE" ]; then
  case "$MOUNT_LINE" in
    *hyperos_torch_255*.camxoverridesettings.generated*)
      /system/bin/nsenter -t 1 -m -- grep -q "^overrideFlashTorchCurrent=${DESIRED_CURRENT}$" "$TARGET" || fail "已有覆盖不匹配"
      cat /proc/sys/kernel/random/boot_id > "$MODDIR/.hal-ready"
      ht_status "$MODDIR" "框架配置已挂载 | 等待温控启动"
      exit 0 ;;
    *) fail "检测到其他配置挂载" ;;
  esac
fi
/system/bin/nsenter -t 1 -m -- cat "$TARGET" > "$TMP" 2>/dev/null || fail "无法读取原厂 HAL"
# Only the calibrated, known original value is enhanced; never lower a new OEM limit.
[ "$(awk -F= '/^[ \t]*overrideFlashTorchCurrent[ \t]*=/ {gsub(/[ \t\r]/,"",$2); print $2}' "$TMP")" = 150 ] || fail "原厂电流已变化，需重新校准"
awk -v current="$DESIRED_CURRENT" '
  /^[ \t]*overrideFlashTorchCurrent[ \t]*=/ {print "overrideFlashTorchCurrent=" current; next}
  {print}
' "$TMP" > "$GENERATED" || fail "生成覆盖失败"
rm -f "$TMP"
chown 0:0 "$GENERATED" && chmod 0644 "$GENERATED" || fail "配置权限失败"
chcon u:object_r:vendor_configs_file:s0 "$GENERATED" 2>/dev/null || fail "配置标签失败"
/system/bin/nsenter -t 1 -m -- /system/bin/mount --bind "$GENERATED" "$TARGET" || fail "HAL 挂载失败"
/system/bin/nsenter -t 1 -m -- grep -q "^overrideFlashTorchCurrent=${DESIRED_CURRENT}$" "$TARGET" || fail "HAL 校验失败"
cat /proc/sys/kernel/random/boot_id > "$MODDIR/.hal-ready"
ht_status "$MODDIR" "HAL 已挂载 | 等待温控启动"
log_i "Camera HAL: $TARGET, torch current 150 -> $DESIRED_CURRENT mA"
