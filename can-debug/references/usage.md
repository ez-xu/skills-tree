# CAN 总线调试 Skill 用法

## 基础用法

```bash
# 探测环境
python scripts/can_tool.py --detect

# 监听总线（10 秒）
python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --listen --duration 10

# 监听并过滤 ID 范围
python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --listen --filter 0x100-0x1FF

# 发送单帧
python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --send --id 0x123 --data 01,02,03,04

# 发送并等待响应
python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --send --id 0x123 --data 01,02 --wait-id 0x124

# 扫描节点
python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --scan --scan-range 0x001-0x0FF

# 使用 virtual 接口测试（无需硬件）
python scripts/can_tool.py --interface virtual --channel test --send --id 0x123 --data AA,BB,CC

# JSON 格式监听
python scripts/can_tool.py --interface pcan --channel PCAN_USBBUS1 --listen --format json
```

## 参数说明

### 模式参数

| 参数 | 说明 |
| --- | --- |
| `--detect` | 探测 python-can 环境 |
| `--listen` | 监听 CAN 总线 |
| `--send` | 发送 CAN 帧 |
| `--scan` | 扫描 CAN 节点 |

### 连接参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--interface` | virtual | CAN 接口类型 |
| `--channel` | test | 通道名 |
| `--bitrate` | 500000 | 波特率 |
| `--timeout` | 1.0 | 接收超时秒数 |

### 发送参数

| 参数 | 说明 |
| --- | --- |
| `--id` | CAN ID（如 0x123） |
| `--data` | 数据字节，逗号分隔十六进制（如 01,02,FF） |
| `--wait-id` | 发送后等待响应的 CAN ID |
| `--extended` | 使用扩展帧（29 位 ID） |

### 监听和扫描

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--filter` | — | 监听过滤 ID 范围（如 0x100-0x1FF） |
| `--scan-range` | 0x001-0x7FF | 扫描 ID 范围 |
| `--duration` | 10 | 监听持续秒数（0=无限） |
| `--format` | table | 输出格式：table、raw、json |

## 常见接口类型

| 接口 | 通道示例 | 说明 |
| --- | --- | --- |
| pcan | PCAN_USBBUS1 | PEAK USB-CAN 适配器 |
| kvaser | 0 | Kvaser USB-CAN |
| slcan | COM3 / /dev/ttyACM0 | CANable 等串口 CAN |
| socketcan | can0 | Linux SocketCAN |
| virtual | test | 虚拟总线（测试用） |
| vci | 0 | GCAN/ZLG/CX USBCAN 适配器（需 32-bit Python） |

### VCI 接口专用参数

VCI 接口使用 GCAN 等国产 USBCAN 适配器的私有 ControlCAN API。
需要 **32-bit Python** (`py -3.11-32`) 来加载 32-bit DLL。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--dll` | ControlCAN_CX.dll | DLL 文件名 (ControlCAN_CX/GC/ZLG) |
| `--dev-type` | 4 | 设备类型 (3=USBCAN_1, 4=USBCAN_2, 20/21=USBCAN_E) |
| `--dev-index` | 0 | 设备索引 (多设备时递增) |
| `--channel` | 1 | CAN 通道编号 (1=CAN1, 2=CAN2)，VCI 从 1 开始计数 |

**DLL 与品牌对照:**

| 品牌 | --dll | --dev-type | 说明 |
| --- | --- | --- | --- |
| 广成 (GCAN) | ControlCAN_GC.dll | 4 | **GCAN 硬件专用**。间歇性 Transmit=-1 需重插设备（已内置 200ms 延迟+重试） |
| 创芯 (CX) | ControlCAN_CX.dll | 4 | 创芯硬件专用。**不能用于 GCAN 硬件**——时序寄存器不匹配，TX 错误会爆满 |
| 周立功 (ZLG) | ControlCAN_ZLG.dll | 4 | ZLG 硬件专用，需配套驱动 |

> **关键原则**：DLL 必须与硬件品牌匹配。CX DLL 的 CAN 控制器时钟配置与 GCAN 硬件不同，
> 即使能 open/init/start 成功，实际波特率会偏差，BMU 无法正确解码帧。
>
> **GC DLL 已知问题**：`ControlCAN_GC.dll` 在 close→reopen 后 `VCI_Transmit` 间歇性返回 -1。
> 设备需物理重插 USB 才能恢复。代码已内置 StartCAN 后 200ms 稳定延迟 + Transmit 3 次自动重试，
> 大多数情况下无需手动干预。
>
> **标准帧限制**：GC DLL 和 CX DLL 对标准帧 (11-bit ID) 的 TX 均有问题。BMU 协议全用扩展帧，不受影响。

**VCI 使用示例:**
```bash
# 探测环境（含 GCAN 设备扫描）
python scripts/can_tool.py --detect

# 监听 CAN1（GCAN 硬件用 GC DLL）
python scripts/can_tool.py --interface vci --channel 1 --dll ControlCAN_GC.dll --listen --duration 10

# 创芯硬件用 CX DLL（切勿用于 GCAN 硬件）
python scripts/can_tool.py --interface vci --channel 1 --dll ControlCAN_CX.dll --listen --duration 10

# 发送扩展帧到 CAN1
python scripts/can_tool.py --interface vci --channel 1 --dll ControlCAN_GC.dll --send --id 0xC8 --data 01,02,03 --extended
```

## 返回码

- `0`：操作成功
- `1`：连接失败、无响应或参数错误
