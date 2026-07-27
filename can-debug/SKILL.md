---
name: can-debug
description: 当需要调试 CAN 总线通信时使用，支持通过 USB-CAN 适配器监听、发送 CAN 帧和扫描节点。支持 PCAN/Kvaser/slcan/socketcan/VCI(GCAN) 等多种接口。
---

# CAN 总线调试

## 适用场景

- 嵌入式设备实现了 CAN 通信，需要验证收发是否正常。
- 需要监听 CAN 总线上的所有帧或过滤特定 ID。
- 需要向 CAN 总线发送测试帧并等待响应。
- 需要扫描总线上的活跃节点。

## 必要输入

以下信息缺一不可，**必须向用户确认**（不可硬编码默认值）：

| 参数 | 说明 | 常用值 |
|------|------|--------|
| **CAN 接口类型** | 适配器接口 | pcan / kvaser / slcan / socketcan / vci |
| **CAN 卡品牌** (VCI 专属) | 国产 USB-CAN 品牌 | GCAN / CX / ZLG |
| **波特率** | CAN 总线速率 | 500000, 250000, 125000 |
| **通道** | CAN 通道标识 | PCAN_USBBUS1 / COM3 / can0 / 0 |

如果用户未提供以上任何一项，**必须先询问**再执行。

## 依赖

- `python-can`（pip install python-can）
- **VCI 接口额外需要**：32-bit Python 3.11（用于加载 32-bit ControlCAN DLL）
- 对应适配器的驱动（如 PCAN 需要 PCAN-Basic API，GCAN 需要 ControlCAN）

## 执行步骤

1. 先阅读 [references/usage.md](references/usage.md)，确认操作参数。
2. **向用户确认缺失参数**（接口类型、品牌、波特率、通道）。
3. 探测环境：
   ```bash
   python scripts/can_tool.py --detect
   ```
4. 根据需求执行操作：

   **VCI/GCAN 示例**（国产 USB-CAN，通道从 1 开始）：
   ```bash
   # 监听 CAN1（GCAN 硬件必须用 GC DLL — CX DLL 时序不匹配会导致 TX 错误爆满）
   python scripts/can_tool.py --interface vci --channel 1 --dll ControlCAN_GC.dll --listen --duration 10

   # GC DLL 间歇性 VCI_Transmit 返回 -1 时的处理：拔插 USB 设备后重试
   # 已内置 200ms StartCAN 延迟 + 3 次自动重试，通常无需手动干预

   # 发送扩展帧到 CAN1
   python scripts/can_tool.py --interface vci --channel 1 --send --id 0xC8 --data 01,02,03 --extended
   ```

   **标准接口示例**（PCAN 等）：
   ```bash
   # 监听总线
   python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --listen --duration 10

   # 发送帧
   python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --send --id 0x123 --data 01,02,03

   # 扫描节点
   python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --scan --scan-range 0x001-0x0FF
   ```

## 失败分流

- `connection-failure`：适配器未连接或驱动未安装。
- `bus-error`：CAN 总线错误（如未接终端电阻、波特率不匹配）。
- `timeout`：发送后无响应。
- `32-bit-python-missing`：VCI 接口需要 32-bit Python，安装 32-bit Python 3.11 后重试。

## 输出约定

示例输出格式：

```
结果: ✅ 监听完成，收到 15 帧
  连接: vci CAN0 [USBCAN-II SN:512000000B3]

  [14:30:01] 0x123  [8]  01 02 03 04 05 06 07 08
  [14:30:01] 0x456  [4]  AA BB CC DD
```

## 交接关系

- 从 `build-keil` / `build-platformio` 烧录固件后，用此 skill 验证 CAN 通信。
- 与 `serial-monitor` 互补：serial-monitor 查看串口调试输出，can-debug 进行 CAN 协议级调试。
