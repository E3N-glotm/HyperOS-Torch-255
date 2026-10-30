#!/system/bin/sh
MODDIR=${0%/*}
. "$MODDIR/lib/discovery.sh"
REPORT="$MODDIR/.probe-report.$$"
trap 'rm -f "$REPORT"' EXIT HUP INT TERM
sh "$MODDIR/probe.sh" --output "$REPORT" || exit 1
printf '\nHyperOS Torch 255 — 兼容性检测\n\n'
printf '当前状态: %s\n' "$(cat "$MODDIR/.status" 2>/dev/null)"
printf '本次检测: %s\n' "$(ht_reason_zh "$(ht_field "$REPORT" reason)")"
printf '机型: %s | SoC: %s\n' "$(ht_field "$REPORT" device)" "$(ht_field "$REPORT" soc)"
printf 'LED 最大值: %s\n' "$(ht_field "$REPORT" max_brightness)"
NATIVE="$MODDIR/.native-capabilities"
if [ -r "$NATIVE" ]; then
  printf '\n安装历史实测: %s | %s\n' "$(ht_native_status_zh "$(ht_field "$NATIVE" native_status)")" "$(ht_native_reason_zh "$(ht_field "$NATIVE" native_reason)")"
  printf '本次接口与构建校验可复用: %s（0 表示未复用，需重新实测）\n' "$(ht_field "$REPORT" native_cache_usable)"
  printf 'Camera API 最高档: %s | 实测驱动值: %s | 驱动量程: %s\n' "$(ht_field "$NATIVE" native_api_max_strength)" "$(ht_field "$NATIVE" native_observed_max)" "$(ht_field "$NATIVE" native_driver_max)"
  printf '响应接口: %s | 响应通道数: %s\n' "$(ht_field "$NATIVE" native_selected_led)" "$(ht_field "$NATIVE" native_channel_count)"
  printf '测量环境: %s | 构建: %s\n' "$(ht_field "$NATIVE" native_environment)" "$(ht_field "$NATIVE" native_firmware)"
fi
printf '\n以下为只读接口报告，不会点亮手电筒或修改硬件参数。\n\n'
cat "$REPORT"
[ ! -r "$NATIVE" ] || { printf '\n安装时原生实测原始报告：\n'; cat "$NATIVE"; }
printf '\ncalibrated: 已匹配校准配置；diagnostic: 保留原厂亮度和温控。\n'
printf '多候选接口、缺少专用传感器或未校准时，不会自动提高电流。\n'
