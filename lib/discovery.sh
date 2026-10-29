#!/system/bin/sh
# Read-only capability discovery. Never probe hardware by writing to a candidate.
HT_ROOT=${HYPERTORCH_TEST_ROOT:-}

ht_uint() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ ${#1} -le 7 ]; }
ht_read() { [ -r "$1" ] && tr -d '\r\n' < "$1"; }
ht_realpath() { readlink -f "$1" 2>/dev/null || printf '%s\n' "$1"; }
ht_field() { awk -F '\t' -v key="$2" '$1 == key {print $2; exit}' "$1"; }
ht_emit() {
  printf '%s\t' "$1"
  printf '%s' "$2" | tr '\t\r\n' '   '
  printf '\n'
}

ht_discover() {
  DEVICE=$(getprop ro.product.device 2>/dev/null)
  SOC=$(getprop ro.soc.model 2>/dev/null)
  ht_emit format 1
  ht_emit device "$DEVICE"
  ht_emit soc "$SOC"

  # Class symlinks are resolved to avoid treating aliases as separate LEDs.
  LED_COUNT=0; LED_SEEN='|'; LED_PATH=; LED_MAX=; LED_KIND=; STROBE=
  PROFILE_LED=; PROFILE_STROBE=; PROFILE_LED_UNEXPECTED=0
  for LED in "$HT_ROOT"/sys/class/leds/*; do
    [ -d "$LED" ] || continue
    NAME=$(basename "$(ht_realpath "$LED")" | tr '[:upper:]' '[:lower:]')
    case "$NAME" in
      *torch*|*flashlight*) KIND=dedicated_torch ;;
      *flash*) KIND=flash_candidate ;;
      *) continue ;;
    esac
    MAX=$(ht_read "$LED/max_brightness")
    VALUE=$(ht_read "$LED/brightness")
    ht_uint "$MAX" && ht_uint "$VALUE" || continue
    [ "$MAX" -gt 0 ] && [ "$MAX" -le 1000000 ] && [ "$VALUE" -le "$MAX" ] || continue
    CANON=$(ht_realpath "$LED")
    case "$LED_SEEN" in *"|$CANON|"*) continue ;; esac
    LED_SEEN="$LED_SEEN$CANON|"
    S=
    if [ -r "$LED/flash_strobe" ]; then
      S="$LED/flash_strobe"
      [ "$KIND" = flash_candidate ] && KIND=shared_flash_torch
    fi
    ht_emit led_candidate "$LED|$KIND|max=$MAX|strobe=$S"
    # A bare flash name may be an indicator or pulse-only device; do not select it.
    [ "$KIND" = flash_candidate ] && continue
    LED_COUNT=$((LED_COUNT + 1))
    LED_PATH="$CANON"; LED_MAX="$MAX"; LED_KIND="$KIND"; STROBE="$S"
    # The validated device exposes three color channels. Its calibrated continuous
    # channel is explicit; this is not a first-candidate rule for unknown hardware.
    case "$DEVICE:$SOC:$NAME:$KIND:$MAX" in
      pudding:SM8850:yellow:flash-0:shared_flash_torch:255)
        PROFILE_LED="$CANON"; PROFILE_STROBE="$S" ;;
      pudding:SM8850:white:flash-1:shared_flash_torch:255|pudding:SM8850:amber:flash-2:shared_flash_torch:255) ;;
      *) PROFILE_LED_UNEXPECTED=1 ;;
    esac
  done
  ht_emit led_count "$LED_COUNT"
  LED_SELECTED=0
  if [ "$LED_COUNT" = 1 ]; then
    LED_SELECTED=1
    ht_emit led_selection unique_interface
  elif [ -n "$PROFILE_LED" ] && [ "$PROFILE_LED_UNEXPECTED" = 0 ]; then
    LED_SELECTED=1
    LED_PATH="$PROFILE_LED"; LED_MAX=255; LED_KIND=shared_flash_torch; STROBE="$PROFILE_STROBE"
    ht_emit led_selection calibrated_profile
  fi
  if [ "$LED_SELECTED" = 1 ]; then
    ht_emit led "$LED_PATH"
    ht_emit led_kind "$LED_KIND"
    ht_emit max_brightness "$LED_MAX"
    ht_emit strobe "$STROBE"
  fi

  # Scan bounded Camera HAL locations, including common multi-camera subdirectories.
  HAL_COUNT=0; HAL_SEEN='|'; HAL_PATH=; HAL_CURRENT=
  for BASE in odm vendor product system/vendor system/odm; do
    for FILE in "$HT_ROOT/$BASE"/etc/camera/camxoverridesettings.txt \
                "$HT_ROOT/$BASE"/etc/camera/*/camxoverridesettings.txt \
                "$HT_ROOT/$BASE"/etc/camera/*/*/camxoverridesettings.txt; do
      [ -r "$FILE" ] && [ -f "$FILE" ] || continue
      CANON=$(ht_realpath "$FILE")
      case "$HAL_SEEN" in *"|$CANON|"*) continue ;; esac
      HAL_SEEN="$HAL_SEEN$CANON|"
      TORCH_KEY_COUNT=$(awk '/^[ \t]*overrideFlashTorchCurrent[ \t]*=/ {n++} END {print n+0}' "$FILE")
      CURRENT=$(awk -F= '/^[ \t]*overrideFlashTorchCurrent[ \t]*=/ {gsub(/[ \t\r]/,"",$2); print $2}' "$FILE")
      SWITCH=$(awk -F= '/^[ \t]*FlashTorchCurrentSwitch[ \t]*=/ {gsub(/[ \t\r]/,"",$2); print $2}' "$FILE")
      ht_emit hal_candidate "$FILE|torch_keys=$TORCH_KEY_COUNT|current=$CURRENT|switch=$SWITCH"
      [ "$TORCH_KEY_COUNT" = 1 ] && [ "$SWITCH" = TRUE ] && ht_uint "$CURRENT" || continue
      [ "$CURRENT" -gt 0 ] && [ "$CURRENT" -le 5000 ] || continue
      HAL_COUNT=$((HAL_COUNT + 1)); HAL_PATH="$FILE"; HAL_CURRENT="$CURRENT"
    done
  done
  ht_emit hal_count "$HAL_COUNT"
  if [ "$HAL_COUNT" = 1 ]; then
    ht_emit hal "$HAL_PATH"; ht_emit hal_current_ma "$HAL_CURRENT"
  fi

  SENSOR_COUNT=0; SENSOR=; SENSOR_TYPE=; SENSOR_SEEN='|'
  for ZONE in "$HT_ROOT"/sys/class/thermal/thermal_zone*; do
    TYPE=$(ht_read "$ZONE/type" | tr '[:upper:]' '[:lower:]')
    case "$TYPE" in flash_therm|flash-therm|torch_therm|torch-therm|flashlight_therm|led_therm) ;;
      *) continue ;; esac
    SENSOR_CANON=$(ht_realpath "$ZONE/temp")
    case "$SENSOR_SEEN" in *"|$SENSOR_CANON|"*) continue ;; esac
    SENSOR_SEEN="$SENSOR_SEEN$SENSOR_CANON|"
    TEMP=$(ht_read "$ZONE/temp")
    ht_uint "$TEMP" && [ "$TEMP" -ge 1000 ] && [ "$TEMP" -le 200000 ] || {
      ht_emit thermal_rejected "$ZONE|$TYPE|invalid_millicelsius=$TEMP"; continue;
    }
    ht_emit thermal_candidate "$ZONE/temp|$TYPE|millicelsius=$TEMP"
    SENSOR_COUNT=$((SENSOR_COUNT + 1)); SENSOR="$ZONE/temp"; SENSOR_TYPE="$TYPE"
  done
  ht_emit thermal_count "$SENSOR_COUNT"
  if [ "$SENSOR_COUNT" = 1 ]; then ht_emit thermal "$SENSOR"; ht_emit thermal_type "$SENSOR_TYPE"; fi

  # Vendor-specific controls are reported, never opened for write or ioctl-guessed.
  for NODE in "$HT_ROOT"/sys/class/flashlight/* "$HT_ROOT"/sys/class/camera/flash \
              "$HT_ROOT"/proc/driver/flashlight "$HT_ROOT"/dev/v4l-subdev*; do
    [ -e "$NODE" ] && ht_emit vendor_candidate "$NODE"
  done
  TEMP_STATE="$HT_ROOT/sys/class/thermal/thermal_message/temp_state"
  PK=0
  if [ -r "$TEMP_STATE" ]; then ht_emit temp_state "$TEMP_STATE"; fi
  # post-fs-data precedes PackageManager. Read its persisted inventory first;
  # a Binder query here would misclassify every early boot or block on startup.
  if grep -q '^com\.miui\.powerkeeper ' "$HT_ROOT/data/system/packages.list" 2>/dev/null; then
    PK=1
  elif [ "$(getprop sys.boot_completed 2>/dev/null)" = 1 ] &&
       pm path com.miui.powerkeeper 2>/dev/null | grep -q '^package:'; then
    PK=1
  fi
  ht_emit powerkeeper "$PK"

  # Enhancement calibration is separate from interface discovery. 255 is a device
  # scale, not a universal LED current limit. New hardware can install and diagnose.
  PROFILE=; REASON=calibration_required
  if [ "$LED_SELECTED" != 1 ]; then REASON=led_missing_or_ambiguous
  elif [ "$HAL_COUNT" != 1 ]; then REASON=hal_missing_or_ambiguous
  elif [ "$SENSOR_COUNT" != 1 ]; then REASON=thermal_missing_or_ambiguous
  elif [ "$DEVICE" = pudding ] && [ "$SOC" = SM8850 ] && [ "$LED_KIND" = shared_flash_torch ] && \
       [ "$(basename "$LED_PATH")" = yellow:flash-0 ] && [ "$LED_MAX" = 255 ] && \
       [ "$SENSOR_TYPE" = flash_therm ] && [ -r "$TEMP_STATE" ] && [ "$PK" = 1 ] && \
       { [ "$HAL_CURRENT" = 150 ] || [ "$HAL_CURRENT" = 500 ]; }; then
    PROFILE=pudding_v1; REASON=calibrated
  fi
  if [ -n "$PROFILE" ]; then ht_emit mode calibrated; else ht_emit mode diagnostic; fi
  ht_emit profile "$PROFILE"
  ht_emit reason "$REASON"
  if [ -n "$PROFILE" ]; then
    ht_emit target_current_ma 500
    ht_emit stock_brightness 76
    ht_emit trip_on_mc 80000
    ht_emit trip_off_mc 75000
    ht_emit powerkeeper_filter 1
  fi
}

# Atomic status updates; punctuation in public descriptions is literal text.
ht_status() {
  HT_MOD=$1
  HT_MESSAGE=$2
  printf '%s\n' "$HT_MESSAGE" > "$HT_MOD/.status"
  awk -v text="状态: $HT_MESSAGE" '
    /^description=/ {print "description=" text; next}
    {print}
  ' "$HT_MOD/module.prop" > "$HT_MOD/.module.prop.$$" &&
    chmod 0644 "$HT_MOD/.module.prop.$$" &&
    mv -f "$HT_MOD/.module.prop.$$" "$HT_MOD/module.prop"
}

ht_reason_zh() {
  case "$1" in
    calibrated) printf '已匹配校准配置' ;;
    calibration_required) printf '尚无匹配的电流校准配置' ;;
    led_missing_or_ambiguous) printf '照明节点缺失或存在多个候选' ;;
    hal_missing_or_ambiguous) printf 'HAL 接口缺失、无效或存在多个候选' ;;
    thermal_missing_or_ambiguous) printf '专用温度接口缺失、无效或存在多个候选' ;;
    *) printf '接口检测未完成' ;;
  esac
}
