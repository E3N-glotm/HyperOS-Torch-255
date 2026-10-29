# HyperOS Torch 255 · 原生手电筒亮度增强

**语言：简体中文（当前） | [English](README_EN.md)**

**开发版：v1.6.0-alpha.1**。保留 HyperOS 原生手电筒，按实际接口进行检测；安装不再按机型代号拒绝。已校准硬件启用增强，其他硬件保留原厂亮度和温控，并提供兼容性报告。

## 本版改动

| 项目 | 新行为 |
| --- | --- |
| LED 查找 | 枚举 `/sys/class/leds`，识别 torch、flashlight 和带 strobe 的 flash 节点，去除符号链接重复项 |
| 亮度范围 | 读取各节点的 `max_brightness`，支持报告 31、100、255、1023 等不同量程，不统一按 255 处理 |
| Camera HAL | 查找 odm、vendor、product 及 system 的对应分区目录，支持 camera 下两级子目录，校验键的数量与格式 |
| 温度传感器 | 识别 flash/torch/LED 专用传感器名称；多个传感器不明确时停止自动选择，不使用 CPU 温度代替 |
| MTK / 其他接口 | 收集 flashlight、厂商 proc 和 V4L2 节点路径；未知 ioctl 与写入协议仅报告 |
| 启动和 OTA | 每次启动重新检测，原厂电流变化后停止套用旧校准 |
| 操作页面 | 展示状态、候选路径、亮度范围和未启用原因；检测不会点亮手电筒 |

**接口识别通过不等于电流和热设计已经校准。** `max_brightness` 是驱动亮度量程，不是安全持续电流参数；不能由它推导出所有手机都适合 500 mA。多候选、传感器缺失或电流映射未知时使用诊断模式，不运行增强守护进程。

## 已校准增强配置

当前仍只有 Xiaomi `pudding` 的历史实机校准：匹配原厂 150 mA / 255 量程 / `yellow:flash-0` / `flash_therm` 以及 PowerKeeper 接口后，保持 500 mA HAL 上限、80°C 降至 76、75°C 恢复的策略。其他机型可安装并生成报告，尚不能据此宣称亮度增强已验证。

增强档会增加 LED 发热，历史高温测试不能代替长期寿命测试；内核和 PMIC 的最终保护保持不变。模块不写 `flash_brightness`，不强制 `flash_strobe=1`，不会在驱动关灯后重新点亮。专用传感器失联时降低增强亮度、恢复原厂热策略并取消旧亮度恢复目标。

本版的自动检测与温控状态机经过模拟接口测试，尚未完成本版实机冷启动和多机型测试。旧版实机记录见 [英文文档](README_EN.md#historical-device-results)。

## 安装和查看报告

1. 在 Magisk 安装 ZIP 并重启，不需要 LSPosed 或 Zygisk。
2. 查看模块状态并点击“操作”，确认是增强配置还是仅诊断模式；诊断模式不改变原厂亮度。
3. 禁用或卸载后重启，恢复原厂 HAL 配置，不要叠加修改同一 Camera HAL 参数的模块。

也可以使用 Root shell 执行只读检测：

```sh
sh /data/adb/modules/hyperos_torch_255/probe.sh
```

报告只包含机型、SoC 和接口能力，不读取设备序列号、账户、照片或应用数据。新增机型应根据报告核实实际照明节点、持续电流映射和温度传感器，再添加校准配置；不能只增加代号白名单。

## 开发与验证

- `lib/discovery.sh`、`probe.sh`：共享接口探测与 TSV 报告。
- `customize.sh`：安装时检测，不再只允许单个机型安装。
- `post-fs-data.sh`：启动重检、原厂配置校验和 systemless 挂载。
- `service.sh`、`src/thermal_governor.c`：使用检测路径启动温控，参数独立校验，失联时回退。
- `action.sh`：Magisk 操作页只读报告。
- `tests/test_compatibility.py`：模拟不同硬件接口，并运行真实 C 温控状态机。

```sh
python3 -m unittest discover -s tests -v
```

原理参考：[Linux LED class](https://docs.kernel.org/leds/leds-class.html)、[Linux Flash LED class](https://docs.kernel.org/leds/leds-class-flash.html)。
