# HyperOS Torch 255 · 原生手电筒亮度增强

**语言：简体中文（当前） | [English](README_EN.md)**

**开发版：v1.7.0-alpha.1**。新增安装时的原生手电筒实测：通过 Android Camera API 短时点亮，比较关灯、低档、最高档和再次关灯的驱动读数，自动识别实际响应的照明接口。

[当前正式版 v1.6.0](https://github.com/E3N-glotm/HyperOS-Torch-255/releases/latest) 仍保持不变。

## 安装时实测

安装器先扫描 LED、Camera HAL 和温度接口，再调用随模块提供的临时 DEX 程序；不安装独立 App，不依赖 LSPosed 或 Zygisk。

| 项目 | 检测行为 |
| --- | --- |
| API 最高档 | Android 13 及以上读取系统声明的最高强度，调用原生接口并回读强度 |
| 驱动读数 | 对每个候选连续采样，记录关灯、低档、最高档、再次关灯时的亮度与 strobe |
| 通道识别 | 同时观察所有有效的 LED class 节点，包括没有 torch/flash 名称的节点 |
| 多通道 | 同时响应的多个 LED 作为一组报告，不任意挑选一个 |
| 老版本系统 | 提供开关灯实测和默认档映射，最高档无法确定时明确留空 |
| 接口隐藏 | Camera API 通过但驱动节点不可读时，报告 API 可用、观测接口未明确 |
| 环境标记 | 记录 HAL 是否存在覆盖；升级时的读数属于当前运行环境，不作为原厂亮度 |
| 超时和退出 | 正常路径关灯后退出，异常路径清理；程序和外层分别设有 10/12 秒截止时间 |

安装前请关闭手电筒并退出正在使用摄像头的应用。相机占用、手电筒已开启、温度过高、系统未启动完成或恢复环境安装时会跳过实测，并保留原因，不影响模块安装。

实测仅使用原生 Camera API 控制灯光，不通过写入未知 sysfs 或厂商 ioctl 试错。最高档阶段约持续半秒，整段测量通常约 2–3 秒。被终止的探测进程由 CameraService 回收其手电筒客户端令牌。

## 三个数值的区别

- Camera API 最高强度：系统当前允许原生接口请求的档位。
- 实测驱动值：在该档位下观察到的稳定 LED 读数。
- max_brightness：驱动声明的量程，不能直接作为持续电流或安全增强目标。

低档可能因驱动量化显示为零，或只点亮其中一个色温通道。探测会结合整个开关灯序列判断；最高档不稳定、读数越界、多个通道同时响应或关灯未确认时，不生成单通道映射。

实测映射绑定机型、SoC、系统构建指纹和接口拓扑。每次开机重新校验，OTA 或接口变化后旧结果不再用于选择通道。开机和 Magisk 操作页仅做只读检查，不会自动点灯；操作页会展示安装历史实测及当前结果能否复用。

## 兼容范围

原生 API 测量与观测接口识别不限制机型，也不要求使用 CamX；具体能回读哪些节点取决于 ROM 和驱动。

**通道读数跟随原生手电筒变化，说明它是经过实测的观测接口，不代表已经验证直接写入该节点的增强方式。** 已知增强校准仍只有 pudding / SM8850：500 mA HAL 上限、80°C 降至约 76、75°C 恢复。其他设备即使测得最高档和照明通道，仍保留原厂电流及温控，等待对应硬件的电流与温控校准。

模块保留内核与 PMIC 最终保护，不写 flash_brightness，不强制重新点亮被驱动关闭的灯；增强档增加发热，短时实测不能替代长期寿命验证。

## 安装与重新检测

1. 在 Magisk 安装开发版 ZIP，留意安装器的短时点灯提示和测量结果，然后正常重启。
2. 进入模块“操作”查看状态、Camera API 最高档、实测驱动值、通道与测量环境。
3. 需要回退时禁用或卸载后重启，恢复原厂 HAL 配置。

可以建立 /data/adb/hyperos_torch_255/skip_native_probe 文件跳过安装点灯。安装脚本也识别 HYPERTORCH_SKIP_NATIVE_PROBE=1。

需要主动重测时，在 Root shell 执行：

```sh
sh /data/adb/modules/hyperos_torch_255/native-probe.sh --output /data/adb/modules/hyperos_torch_255/.native-capabilities
```

只读检查仍使用：

```sh
sh /data/adb/modules/hyperos_torch_255/probe.sh
```

报告包含机型、SoC、系统构建和接口读数，不读取序列号、账号、照片或应用数据。

## 验证

开发版已完成 Python 安装/缓存/超时/退出流程测试、真实 C 温控状态机测试和纯 Java 通道关联测试，Android Java 与 DEX 已构建。当前手机插件连接异常、ADB 无在线设备，本版安装探测尚未实机验收；v1.6.0 的历史实测不能替代新版主动探测的实机测试。

CI 从源码重新构建 ARM64 温控程序与原生探测 DEX，打包包含所有运行脚本。

参考：[Android CameraManager](https://developer.android.com/reference/android/hardware/camera2/CameraManager)、[Linux LED class](https://docs.kernel.org/leds/leds-class.html)。

