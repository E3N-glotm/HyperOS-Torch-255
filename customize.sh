#!/system/bin/sh
SKIPMOUNT=true
PROPFILE=false
POSTFSDATA=true
LATESTARTSERVICE=true

ui_print "*******************************"
ui_print " HyperOS Torch 255"
ui_print "*******************************"
[ "$ARCH" = arm64 ] || abort "需要 arm64；当前架构: $ARCH"
[ -x "$MODPATH/bin/thermal_governor" ] || [ -f "$MODPATH/bin/thermal_governor" ] || abort "缺少温控程序"
. "$MODPATH/lib/discovery.sh"
sh "$MODPATH/probe.sh" --output "$MODPATH/.install-capabilities" || abort "接口检测失败"
REPORT="$MODPATH/.install-capabilities"
ui_print "机型: $(ht_field "$REPORT" device)"
ui_print "LED 候选: $(ht_field "$REPORT" led_count) | HAL 候选: $(ht_field "$REPORT" hal_count)"
ui_print "LED 上限: $(ht_field "$REPORT" max_brightness) | 温度传感器: $(ht_field "$REPORT" thermal_count)"
if [ "$(ht_field "$REPORT" mode)" = calibrated ]; then
  ui_print "已匹配经过校准的增强配置，重启后启用。"
  ht_status "$MODPATH" "待重启检测"
else
  ui_print "接口报告已生成；当前保留原厂亮度和温控。"
  ui_print "检测结果: $(ht_reason_zh "$(ht_field "$REPORT" reason)")"
  ui_print "重启后点击模块操作可查看完整兼容性报告。"
  ht_status "$MODPATH" "仅诊断 | 待校准或接口不完整"
fi
set_perm_recursive "$MODPATH" 0 0 0755 0644
for FILE in post-fs-data.sh service.sh uninstall.sh action.sh probe.sh bin/thermal_governor; do
  set_perm "$MODPATH/$FILE" 0 0 0755
done
set_perm "$MODPATH/.install-capabilities" 0 0 0600
