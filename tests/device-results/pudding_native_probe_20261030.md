# pudding 安装时原生探测实机记录

日期：2026-10-30。设备为 Xiaomi pudding / SM8850，Android 17（SDK 37），Magisk Root。测试版本 v1.7.0-alpha.1，功能源码提交 f67dac364c699c8a38f3ea0c87e35c6b2dfdf7b3。

## 测量环境

测试前手机正在运行 v1.6.0-alpha.2，其 500 mA HAL 覆盖已加载。新探测程序和真实 Magisk 安装器均报告 hal_overlay_present。下面是当前增强环境下的原生 API / 驱动读数，不能用作未加载模块时的原厂亮度。

## 实测结果

| 检查 | 结果 |
| --- | --- |
| 原生 Camera API 最高档 | 100，回读确认通过 |
| 扫描 LED 节点 | 6 个，包含 RGB 和三个闪光灯通道 |
| 实际响应通道 | yellow:flash-0，自动关联为唯一通道 |
| 关灯基线 | brightness/strobe = 0/0，三次一致 |
| API 低档 1 | brightness/strobe = 6/1，三次一致 |
| API 最高档 100 | brightness/strobe = 255/1，三次一致 |
| 再次关灯 | brightness/strobe = 0/0，三次一致 |
| 其他五个节点 | 不随本次手电筒会话点亮 |
| Magisk 真实安装 | 成功，保存 mapped_maximum 和 native_api_correlation |
| 用户跳过开关 | 报告 user_disabled，灯光保持 0/0 |
| 手电筒已开启 | 报告 torch_already_on，原有低档 6/1 保持 |
| 测试客户端退出 | CameraService 回收会话后灯光恢复 0/0 |
| 原生映射缓存 | 当前构建和拓扑匹配时 native_cache_usable=1 |
| 构建失配模拟 | 在临时副本修改构建字段后缓存被拒绝，恢复后再次可用 |
| 启动检测 | 新暂存模块的 post-fs-data 完成检测，采用实测映射 |
| 温控接口只读预检 | 暂存版 thermal_governor --check 通过 |
| 清理 | 仅一个原有温控守护进程；无 TorchProbe / TorchBusyHold 残留；灯光最终 0/0 |

## 验证边界

本轮未重启手机。开发版已通过 Magisk 安装至暂存目录，下次正常重启才由开机流程正式加载；本轮的启动脚本检查与只读预检不等于重启后的冷启动验收。

没有对新机型套用电流参数，也没有制造实物高温或 Binder 挂起。超时、取消与其他通道组合由自动化测试覆盖。其他机型、旧 Android、隐藏驱动节点及长期点亮仍需要独立实机验证。
