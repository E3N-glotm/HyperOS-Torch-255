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
ui_print "准备原生手电筒实测：将短时点亮后置灯，比较低档、最高档与关灯读数。"
ui_print "相机占用、灯已开启、温度过高或系统未就绪时会跳过；不直接写入未知驱动。"
sh "$MODPATH/native-probe.sh" --output "$MODPATH/.native-capabilities" || ui_print "原生实测未完成，保留接口诊断结果。"
sh "$MODPATH/probe.sh" --output "$MODPATH/.install-capabilities" || abort "实测后接口检测失败"
REPORT="$MODPATH/.install-capabilities"
NATIVE="$MODPATH/.native-capabilities"
ui_print "原生实测: $(ht_native_status_zh "$(ht_field "$NATIVE" native_status)")"
ui_print "测量结果: $(ht_native_reason_zh "$(ht_field "$NATIVE" native_reason)")"
ui_print "Camera API 最高档: $(ht_field "$NATIVE" native_api_max_strength) | 实测驱动值: $(ht_field "$NATIVE" native_observed_max)"
ui_print "响应通道数: $(ht_field "$NATIVE" native_channel_count) | 环境: $(ht_field "$NATIVE" native_environment)"
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
for FILE in post-fs-data.sh service.sh uninstall.sh action.sh probe.sh native-probe.sh bin/thermal_governor; do
  set_perm "$MODPATH/$FILE" 0 0 0755
done
set_perm "$MODPATH/.install-capabilities" 0 0 0600
[ ! -f "$MODPATH/.native-capabilities" ] || set_perm "$MODPATH/.native-capabilities" 0 0 0600
