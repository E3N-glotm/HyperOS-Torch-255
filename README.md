# HyperOS Torch 255 · 原生手电筒亮度增强

**语言：简体中文（当前） | [English](README_EN.md)**

适用于已验证的 Xiaomi `pudding` 硬件的 Magisk 模块。保留 HyperOS 原生控制中心手电筒与亮度滑条，扩展常亮亮度上限，并在高温时自动降档。

**当前版本：v1.5.1** · [下载 Release](https://github.com/E3N-glotm/HyperOS-Torch-255/releases)

> [!WARNING]
> 增强档会显著增加 LED 发热。亮度 `255` 不是建议长期使用的安全常亮档。高温、长时间持续点亮仍可能损伤硬件。内核与 PMIC 保护保留，但不代表没有风险。

## 工作方式

- 使用 Magisk systemless 方式覆盖专用 Camera HAL 配置，将原厂 `overrideFlashTorchCurrent` 上限由 150 调整为 500（相应单位取决于 OEM 定义）。
- 已验证设备上，原生最高强度可从约 `brightness=76` 提升到 `255`。
- 仅在手电筒会话期间，对 PowerKeeper 所见的手电筒专用热状态进行有限处理，不覆盖其他进程读取的系统温度。
- `flash_therm >= 80°C` 时降至约原厂亮度 `76`；降到 `<= 75°C` 后，在手电筒仍开启时尝试恢复目标亮度，带回滞防止抖动。
- 不修改内核热阈值，不强制在内核关灯后重新点亮，不把闪光摄影电流用于常亮。

## 兼容性

- **已验证硬件：** Xiaomi `pudding`，ARM64；其他手机即使具有相似 sysfs，也不代表经过电流与热设计验证。
- v1.5.1 已取消按 Android SDK 版本号放行，改为探测 Camera HAL 配置、LED sysfs、`flash_therm`、`temp_state` 与 PowerKeeper 等实际接口。
- 检测通过仅说明接口结构符合要求，不能替代未来系统版本的高温、寿命与长亮测试。

## 安装与恢复

在 Magisk 中安装对应 ZIP 并重启，在原生控制中心调节亮度。需要回退时禁用或卸载模块后重启，恢复原厂 Camera HAL 配置。**不要与其他修改同一 Camera HAL 闪光灯参数的模块叠加。**

## 相关文件

- `customize.sh`：安装兼容性与接口校验
- `post-fs-data.sh`、`service.sh`：挂载与启动管理
- `src/thermal_governor.c`：温度回滞控制源码
- `README_EN.md`：英文详细文档与历史测试记录

模块不使用 LSPosed/Zygisk Hook。
