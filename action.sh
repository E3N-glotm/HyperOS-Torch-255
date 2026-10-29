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
printf '\n以下为只读接口报告，不会点亮手电筒或修改硬件参数。\n\n'
cat "$REPORT"
printf '\ncalibrated: 已匹配校准配置；diagnostic: 保留原厂亮度和温控。\n'
printf '多候选接口、缺少专用传感器或未校准时，不会自动提高电流。\n'
