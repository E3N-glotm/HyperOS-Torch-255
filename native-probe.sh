#!/system/bin/sh
# Active, explicit installer/manual probe. All light control uses Android CameraManager.
MODDIR=$(CDPATH= cd "$(dirname "$0")" && pwd -P) || exit 1
. "$MODDIR/lib/discovery.sh"
[ "$1" = --output ] && [ -n "$2" ] || { echo "usage: native-probe.sh --output REPORT"; exit 2; }
DEST=$2
umask 077
INPUT="$MODDIR/.native-input.$$"
RESULT="$MODDIR/.native-result.$$"
LOG="$MODDIR/.native-log.$$"
CHILD=
WATCHDOG=
cleanup() {
  if [ -n "$CHILD" ] && kill -0 "$CHILD" 2>/dev/null; then
    kill -KILL "$CHILD" 2>/dev/null || true
    wait "$CHILD" 2>/dev/null || true
  fi
  if [ -n "$WATCHDOG" ]; then kill "$WATCHDOG" 2>/dev/null || true; wait "$WATCHDOG" 2>/dev/null || true; fi
  rm -f "$INPUT" "$RESULT" "$RESULT.java-tmp" "$LOG"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
fallback() {
  {
    ht_emit native_format 1
    ht_emit native_status skipped
    ht_emit native_reason "$1"
    [ ! -s "$LOG" ] || ht_emit native_error_detail "$(head -c 1024 "$LOG")"
    ht_emit native_device "$(getprop ro.product.device 2>/dev/null)"
    ht_emit native_soc "$(getprop ro.soc.model 2>/dev/null)"
    ht_emit native_firmware "$(getprop ro.build.fingerprint 2>/dev/null)"
  } > "$RESULT"
  chmod 0600 "$RESULT"
  mv -f "$RESULT" "$DEST"
  exit 0
}
[ "${HYPERTORCH_SKIP_NATIVE_PROBE:-0}" != 1 ] || fallback user_disabled
[ ! -e "$HT_ROOT/data/adb/hyperos_torch_255/skip_native_probe" ] || fallback user_disabled
[ "${BOOTMODE:-true}" != false ] || fallback recovery_install
[ "$(getprop sys.boot_completed 2>/dev/null)" = 1 ] || fallback system_not_ready
APP_PROCESS=$(command -v app_process 2>/dev/null)
[ -n "$APP_PROCESS" ] || fallback app_process_unavailable
[ -s "$MODDIR/bin/torch_probe.dex" ] || fallback helper_unavailable
sh "$MODDIR/probe.sh" --output "$INPUT" || fallback inventory_failed
CLASSPATH="$MODDIR/bin/torch_probe.dex" "$APP_PROCESS" /system/bin TorchProbe "$INPUT" "$RESULT" > "$LOG" 2>&1 &
CHILD=$!
# CameraService releases this helper's torch token when the process dies.
# The helper also has its own 10 s hard deadline and normal try/finally cleanup.
(
  TIMER=
  trap '[ -z "$TIMER" ] || kill "$TIMER" 2>/dev/null; exit 0' HUP INT TERM
  sleep 12 &
  TIMER=$!
  wait "$TIMER" || exit 0
  kill -KILL "$CHILD" 2>/dev/null || true
) >/dev/null 2>&1 &
WATCHDOG=$!
wait "$CHILD"
NATIVE_RC=$?
CHILD=
kill "$WATCHDOG" 2>/dev/null || true
wait "$WATCHDOG" 2>/dev/null || true
WATCHDOG=
if [ ! -s "$RESULT" ]; then
  case "$NATIVE_RC" in 124|137) fallback probe_timeout ;; *) fallback helper_failed ;; esac
fi
[ "$(ht_field "$RESULT" native_format)" = 1 ] || fallback invalid_report
chmod 0600 "$RESULT" && mv -f "$RESULT" "$DEST" || exit 1
exit 0
