# HyperOS Torch 255

**简体中文** | [English](README_EN.md)

面向 Xiaomi 17（`pudding`，Android 16 / HyperOS）的 Magisk 手电筒增强模块。在不替换 SystemUI、不使用 LSPosed/Zygisk/Xposed 的前提下，保留 HyperOS 原生控制中心手电筒与亮度滑条，并把最高持续亮度扩展到驱动正常 `brightness` 范围的 `255`。

> [!WARNING]
> 本模块会显著提高 LED 持续输出和发热。`100% / brightness=255` 应视为极限档，不是普通长期照明档。模块保留内核、Camera HAL 和 PMIC 的最终保护，但这不代表高温运行没有硬件风险。

## 兼容性

- 已验证设备：**Xiaomi 17**
- 设备代号：**`pudding`**
- 已验证系统：Android 16 / HyperOS
- Root：Magisk
- 模块架构：AArch64

模块包含 Xiaomi 17 专用 Camera HAL 配置键、LED sysfs 路径以及 PowerKeeper 热状态处理逻辑。**未验证其他机型，不建议直接刷入其他设备。**

## 功能

- 保留 HyperOS 原生控制中心手电筒入口和亮度滑条。
- 将 Camera HAL 的 `overrideFlashTorchCurrent` 从原厂 `150` systemless 覆盖为 `500`。
- 在实测 Xiaomi 17 上，原生 `strength=100` 从约 `brightness=76` 提升到 `brightness=255`。
- 只在手电筒会话活动期间，对 PowerKeeper 自己看到的 `temp_state` 最后一位手电筒热状态进行隔离过滤；系统其余进程仍看到真实 thermal sysfs。
- 模块自带窄范围热保护：
  - `flash_therm >= 80°C`：增强档降到原厂级 `brightness=76`；
  - `flash_therm <= 75°C`：若手电筒仍在工作，恢复用户此前目标亮度；
  - 采用 80/75°C 回滞，避免临界温度反复抖动。
- 不修改 kernel thermal trip。
- 不写 `flash_brightness`，不会把拍照爆闪电流当持续照明电流。
- 不主动重新置 `flash_strobe=1`；如果驱动、内核或 PMIC 将 LED 关闭，模块不会强行重新点亮。
- Magisk systemless 安装；卸载并重启后恢复原厂 Camera HAL 配置和 PowerKeeper 视图。

## 实测结果

原厂 Camera HAL 电流映射：

| Torch current | `yellow:flash-0/brightness` |
| ---: | ---: |
| 150 mA | 76 |
| 250 mA | 127 |
| 350 mA | 178 |
| 450 mA | 229 |
| 500 mA | 255 |

v1.5.0 实机验证包括：

- HyperOS 原生亮度滑条最高档：`yellow:flash-0 = 255`、`flash_strobe = 1`。
- 实际 `flash_therm` 约 77.6°C 时仍保持增强亮度。
- `flash_therm = 80.006°C` 时从 `255` 降为 `76`。
- 降温至约 74.9°C 后恢复此前增强目标。
- 完成过“卸载 → 重启 → 验证 stock → 重新安装 → 重启 → 再验证增强”的完整回滚闭环。

## 安装

1. 从 [Releases](../../releases) 下载 `HyperOS-Torch-255-v1.5.0.zip`。
2. 在 Magisk 中选择“从本地安装”，刷入 ZIP。
3. 重启手机。
4. 之后直接使用 HyperOS 原生控制中心手电筒和亮度滑条即可。

Release 同时提供可选的 `RootTorch-v1.0.2.apk`。它是独立 Root 手电筒控制工具，不是 Magisk 模块运行所必需：

- 第一次安装后手动点击一次“获取 Root”并在 Root 管理器中授权；
- 授权成功后 App 会记住“已完成首次授权”；
- 之后每次启动会自动使用 Root 管理器已经保存的授权重新建立 `su` 会话，不需要每次再按“获取 Root”；
- 如果 Magisk 授权被撤销、Root 环境被重置或自动连接失败，App 会重新显示“重新获取 Root”。

## 卸载

在 Magisk 中移除模块并重启。

v1.5.0 的回滚测试确认：

- `/data/adb/modules/hyperos_torch_255` 被移除；
- 模块 thermal governor 不再运行；
- PowerKeeper namespace 不再存在模块的 `temp_state` 代理挂载；
- `/odm/etc/camera/camxoverridesettings.txt` 对系统恢复原厂 `overrideFlashTorchCurrent=150`；
- 原厂 `strength=100` 恢复为约 `brightness=76`。

ROM 分区本身不会被永久写入。

## 工作原理

HyperOS 正常手电筒链路保持不变：

```text
MiFlashlightActivity
  -> Camera2 torch strength 1..100
  -> Xiaomi/QCOM Camera HAL
  -> PMIC
  -> /sys/class/leds/yellow:flash-0
```

### 1. Camera HAL 上限

原厂 `/odm/etc/camera/camxoverridesettings.txt` 包含：

```text
overrideFlashTorchCurrent=150
```

模块在每次启动时复制 ROM 原始配置，检查目标配置键，只把这一项改为 `500`，保持原厂 vendor SELinux label，再通过 Magisk/systemless bind mount 在 Camera Provider 启动前提供给 Camera HAL。

模块不会修改 `overrideFlashVideoLightCurrent`、`overrideFlashPreviewLightCurrent`、`overrideTorchScanCurrent`、`overrideFlashSnapshotLightCurrent` 或 `FlashTorchTemperatureLevels`。

### 2. HyperOS 约 57°C 的提前关灯策略

实机定位到 `com.miui.powerkeeper` 会读取：

```text
/sys/class/thermal/thermal_message/temp_state
```

并发送 `action_temp_state_change`。SystemUI/插件使用该复合整数最后一位作为手电筒热状态，特定状态会提前降亮度或关闭手电筒。

v1.5.0 不全局伪造 thermal 状态，而是在物理手电筒活动期间，仅进入 **PowerKeeper 的 mount namespace**，将该路径替换为模块维护的只读代理。代理保留复合热状态的高位，只把最后一位手电筒状态过滤为 `0`；其他进程和内核仍读取真实 sysfs。手电筒关闭后代理挂载立即移除。

### 3. 模块自己的 80/75°C governor

同一个 AArch64 原生进程每 100 ms 读取 `flash_therm`、`yellow:flash-0/brightness` 与 `flash_strobe`。低于 80°C 时不重映射原生滑条；到达 80°C 时仅把高于原厂档的持续亮度压回 `76`，降到 75°C 后再恢复此前目标。

这一策略是额外保护层，不替代内核或 PMIC 的最终保护。

原生 governor 源码位于 [`src/thermal_governor.c`](src/thermal_governor.c)，Release/Magisk 包中的 `bin/thermal_governor` 是对应的 AArch64 Android 可执行文件。

## RootTorch v1.0.2

APK 的包名仍为 `io.e3n.roottorch`。v1.0.2 只改变 Root 授权体验：首次明确授权一次，后续启动自动复用 Root 管理器持久化的授权并重新创建 App 进程自己的长驻 `su` shell。

App 不保存 Root 密钥、Magisk Token 或密码；本地偏好只记录“用户曾经成功完成授权”这一布尔状态，真正的 Root 权限仍由 Magisk/Root 管理器决定。

> 本次 v1.0.2 按要求只进行了本地源码检查、构建和 APK 静态验证，没有连接手机进行新一轮实机测试。模块 v1.5.0 的上述硬件与热策略数据来自此前的 Xiaomi 17 实机验证。

## 安全边界

- 不修改 kernel thermal trip。
- 不绕过 PMIC/驱动最终关断。
- 不写 `flash_brightness`。
- 不强制保持 `flash_strobe=1`。
- 100% 增强档发热明显，应避免不必要的长时间高温运行。

## 版本

- Magisk module: **v1.5.0 / versionCode 150**
- Companion APK: **RootTorch v1.0.2 / versionCode 12**

