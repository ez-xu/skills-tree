#!/usr/bin/env python
"""CAN 总线调试工具。

为 `can-debug` skill 提供可重复调用的执行入口，支持：

- 探测 python-can 环境
- 监听 CAN 总线帧
- 发送 CAN 帧（可等待响应）
- 扫描 CAN 节点
- 过滤指定 ID 范围
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import can
    HAS_CAN = True
    CAN_VERSION = can.__version__
except ImportError:
    HAS_CAN = False
    CAN_VERSION = None

KNOWN_INTERFACES = ["pcan", "kvaser", "slcan", "socketcan", "virtual",
                     "ixxat", "vector", "canalystii", "systec", "usb2can"]

# 注册 VCI 后端（GCAN/ZLG/CX USBCAN 适配器）
try:
    import can.interfaces
    from vci_adapter import VciBus
    can.interfaces.BACKENDS["vci"] = ("vci_adapter", "VciBus")
    KNOWN_INTERFACES.append("vci")
    HAS_VCI = True
except ImportError:
    HAS_VCI = False


@dataclass
class CANResult:
    status: str  # success, failure, timeout
    summary: str
    mode: str | None = None
    connection: str | None = None
    messages: list[dict] = field(default_factory=list)
    failure_category: str | None = None
    evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------

def create_bus(interface: str, channel: str, bitrate: int, **kwargs: Any) -> Any:
    """创建 CAN 总线连接。VCI 接口额外支持 dll/dev_type/dev_index 参数。"""
    try:
        bus = can.Bus(interface=interface, channel=channel, bitrate=bitrate, **kwargs)
        return bus, None
    except Exception as e:
        return None, str(e)


def format_msg(msg: can.Message) -> dict:
    return {
        "timestamp": round(msg.timestamp, 6),
        "id": f"0x{msg.arbitration_id:03X}",
        "id_int": msg.arbitration_id,
        "dlc": msg.dlc,
        "data": " ".join(f"{b:02X}" for b in msg.data),
        "extended": msg.is_extended_id,
        "remote": msg.is_remote_frame,
    }


def parse_id(s: str) -> int:
    s = s.strip()
    return int(s, 16) if s.startswith("0x") or s.startswith("0X") else int(s)


def parse_filter(filter_str: str) -> tuple[int, int] | None:
    if not filter_str:
        return None
    parts = filter_str.split("-")
    lo = parse_id(parts[0])
    hi = parse_id(parts[1]) if len(parts) > 1 else lo
    return lo, hi


# ---------------------------------------------------------------------------
# 监听
# ---------------------------------------------------------------------------

def listen_bus(bus, duration: float, filter_range: tuple[int, int] | None, fmt: str) -> CANResult:
    print(f"📡 监听 CAN 总线（{duration}s）..." if duration > 0 else "📡 监听 CAN 总线（Ctrl+C 停止）...")
    messages: list[dict] = []
    deadline = time.time() + duration if duration > 0 else float("inf")

    try:
        while time.time() < deadline:
            msg = bus.recv(timeout=0.5)
            if msg is None:
                continue
            if filter_range:
                lo, hi = filter_range
                if not (lo <= msg.arbitration_id <= hi):
                    continue
            m = format_msg(msg)
            messages.append(m)
            if fmt == "json":
                print(json.dumps(m))
            else:
                ts = time.strftime("%H:%M:%S", time.localtime(msg.timestamp))
                rtr = " RTR" if msg.is_remote_frame else ""
                print(f"  [{ts}] {m['id']}  [{msg.dlc}]  {m['data']}{rtr}")
    except KeyboardInterrupt:
        pass

    return CANResult(status="success", summary=f"监听完成，收到 {len(messages)} 帧", mode="listen", messages=messages)


# ---------------------------------------------------------------------------
# 发送
# ---------------------------------------------------------------------------

def send_frame(bus, arb_id: int, data: list[int], extended: bool) -> CANResult:
    msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=extended)
    try:
        bus.send(msg)
        m = format_msg(msg)
        print(f"✅ 已发送: {m['id']}  [{msg.dlc}]  {m['data']}")
        return CANResult(status="success", summary=f"发送成功 ID={m['id']}", mode="send", messages=[m])
    except Exception as e:
        return CANResult(status="failure", summary=str(e), mode="send", failure_category="bus-error", evidence=[str(e)])


def send_and_wait(bus, arb_id: int, data: list[int], wait_id: int, timeout: float, extended: bool) -> CANResult:
    msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=extended)
    try:
        bus.send(msg)
    except Exception as e:
        return CANResult(status="failure", summary=str(e), mode="send", failure_category="bus-error", evidence=[str(e)])

    m_sent = format_msg(msg)
    print(f"📤 已发送: {m_sent['id']}  [{msg.dlc}]  {m_sent['data']}")
    print(f"⏳ 等待响应 ID=0x{wait_id:03X}（{timeout}s）...")

    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = bus.recv(timeout=0.5)
        if resp and resp.arbitration_id == wait_id:
            m_resp = format_msg(resp)
            print(f"📥 响应: {m_resp['id']}  [{resp.dlc}]  {m_resp['data']}")
            return CANResult(status="success", summary=f"收到响应 ID=0x{wait_id:03X}",
                             mode="send", messages=[m_sent, m_resp])

    return CANResult(status="timeout", summary=f"等待 ID=0x{wait_id:03X} 超时", mode="send",
                     messages=[m_sent], failure_category="timeout")


# ---------------------------------------------------------------------------
# 扫描节点
# ---------------------------------------------------------------------------

def scan_nodes(bus, scan_range: str, timeout: float) -> CANResult:
    parts = scan_range.split("-")
    start = parse_id(parts[0])
    end = parse_id(parts[1]) if len(parts) > 1 else start

    print(f"🔍 扫描 CAN 节点 0x{start:03X}-0x{end:03X}...")
    found: list[dict] = []

    for arb_id in range(start, end + 1):
        msg = can.Message(arbitration_id=arb_id, is_remote_frame=True, dlc=0)
        try:
            bus.send(msg)
        except Exception:
            continue

        resp = bus.recv(timeout=timeout)
        if resp and resp.arbitration_id == arb_id:
            m = format_msg(resp)
            found.append(m)
            print(f"  ✅ 0x{arb_id:03X} 响应: [{resp.dlc}] {m['data']}")

    if found:
        return CANResult(status="success", summary=f"找到 {len(found)} 个节点", mode="scan", messages=found)
    return CANResult(status="failure", summary="未找到响应节点", mode="scan", failure_category="timeout")


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def print_report(result: CANResult) -> None:
    icon = {"success": "✅", "failure": "❌", "timeout": "⏱️"}.get(result.status, "❓")
    print(f"\n📊 结果: {icon} {result.summary}")

    if result.connection:
        print(f"  连接: {result.connection}")
    if result.mode == "scan" and result.messages:
        print(f"  响应节点: {', '.join(m['id'] for m in result.messages)}")
    if result.failure_category:
        print(f"\n  失败分类: {result.failure_category}")
    if result.evidence:
        print("\n📝 证据:")
        for line in result.evidence[:10]:
            print(f"  {line}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CAN 总线调试工具", formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--detect", action="store_true", help="探测 python-can 环境")
    p.add_argument("--listen", action="store_true", help="监听 CAN 总线")
    p.add_argument("--send", action="store_true", help="发送 CAN 帧")
    p.add_argument("--scan", action="store_true", help="扫描 CAN 节点")
    p.add_argument("--interface", default="virtual", help="CAN 接口类型（默认 virtual）")
    p.add_argument("--channel", default="test", help="CAN 通道名")
    p.add_argument("--bitrate", type=int, default=500000, help="波特率（默认 500000）")
    p.add_argument("--timeout", type=float, default=1.0, help="接收超时秒数（默认 1）")
    p.add_argument("--id", help="发送帧的 CAN ID（如 0x123）")
    p.add_argument("--data", help="发送数据，逗号分隔十六进制（如 01,02,FF）")
    p.add_argument("--wait-id", help="发送后等待响应的 CAN ID")
    p.add_argument("--extended", action="store_true", help="使用扩展帧（29 位 ID）")
    p.add_argument("--filter", help="监听过滤 ID 范围（如 0x100-0x1FF）")
    p.add_argument("--scan-range", default="0x001-0x7FF", help="扫描 ID 范围（默认 0x001-0x7FF）")
    p.add_argument("--duration", type=float, default=10, help="监听持续秒数（默认 10，0=无限）")
    p.add_argument("--format", choices=["table", "raw", "json"], default="table", help="输出格式")
    # VCI 专用参数 (GCAN/ZLG/CX) — DLL 必须匹配硬件品牌，不设默认值
    p.add_argument("--dll", default=None, help="VCI: DLL 文件名 (必填: ControlCAN_GC/CX/ZLG.dll)")
    p.add_argument("--dev-type", type=int, default=4, help="VCI: 设备类型 (默认 4=USBCAN_2)")
    p.add_argument("--dev-index", type=int, default=0, help="VCI: 设备索引 (默认 0)")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.detect:
        print("\n📊 CAN 调试环境探测：")
        if HAS_CAN:
            print(f"  ✅ python-can {CAN_VERSION}")
        else:
            print("  ❌ python-can 未安装（pip install python-can）")

        print(f"\n  已知接口类型:")
        for iface in KNOWN_INTERFACES:
            marker = " (VCI/GCAN)" if iface == "vci" else ""
            print(f"    - {iface}{marker}")

        # 探测 VCI/GCAN 设备
        if HAS_VCI:
            print("\n  VCI 设备探测:")
            print(f"    32-bit Python: ", end="")
            try:
                from vci_adapter import _find_32bit_python
                py_cmd = _find_32bit_python()
                print(f"✅ {' '.join(py_cmd)}")
            except RuntimeError as e:
                print(f"❌ {e}")
                py_cmd = None

            # 扫描设备：用所有可用的 DLL 各尝试一次
            if py_cmd:
                import subprocess as sp, os
                bridge = os.path.join(os.path.dirname(os.path.abspath(__file__)), "can_bridge.py")
                # 若用户未指定 DLL，尝试所有已知 DLL
                dlls_to_try = [args.dll] if args.dll else [
                    "ControlCAN_GC.dll", "ControlCAN_CX.dll", "ControlCAN_ZLG.dll"
                ]
                for dll_name in dlls_to_try:
                    if dll_name is None:
                        continue
                    try:
                        result = sp.run(
                            py_cmd + [bridge, "find", "--dll", dll_name],
                            capture_output=True, text=True, timeout=10,
                        )
                        if result.returncode == 0:
                            print(f"    [{dll_name}] {result.stdout.strip()}")
                        else:
                            print(f"    [{dll_name}] (无设备或 DLL 不支持扫描)")
                    except Exception as ex:
                        print(f"    [{dll_name}] 扫描异常: {ex}")

        return 0

    if not HAS_CAN:
        print("❌ python-can 未安装，请运行: pip install python-can")
        return 1

    if not (args.listen or args.send or args.scan):
        parser.print_help()
        return 1

    # 构建连接参数
    conn_str = f"{args.interface} {args.channel} {args.bitrate}"
    bus_kwargs = {}
    if args.interface == "vci":
        if not args.dll:
            print("❌ VCI 接口必须指定 --dll 参数（DLL 必须匹配硬件品牌）")
            print("   GCAN 硬件: --dll ControlCAN_GC.dll")
            print("   创芯 硬件: --dll ControlCAN_CX.dll")
            print("   ZLG  硬件: --dll ControlCAN_ZLG.dll")
            return 1
        bus_kwargs = {
            "dll": args.dll,
            "dev_type": args.dev_type,
            "dev_index": args.dev_index,
        }
    bus, err = create_bus(args.interface, args.channel, args.bitrate, **bus_kwargs)
    if bus is None:
        print(f"❌ 连接失败: {conn_str}")
        if err:
            print(f"  {err}")
        return 1
    print(f"🔗 已连接: {conn_str}")

    try:
        if args.listen:
            filt = parse_filter(args.filter) if args.filter else None
            result = listen_bus(bus, args.duration, filt, args.format)
            result.connection = conn_str
            print_report(result)
            return 0

        if args.send:
            if not args.id:
                print("❌ 发送需要 --id 参数（如 --id 0x123）")
                return 1
            arb_id = parse_id(args.id)
            data = [int(b, 16) for b in args.data.split(",")] if args.data else []

            if args.wait_id:
                wait_id = parse_id(args.wait_id)
                result = send_and_wait(bus, arb_id, data, wait_id, args.timeout, args.extended)
            else:
                result = send_frame(bus, arb_id, data, args.extended)
            result.connection = conn_str
            print_report(result)
            return 0 if result.status == "success" else 1

        if args.scan:
            result = scan_nodes(bus, args.scan_range, args.timeout)
            result.connection = conn_str
            print_report(result)
            return 0 if result.status == "success" else 1

    finally:
        bus.shutdown()
        print("🔌 CAN 总线已关闭")


if __name__ == "__main__":
    sys.exit(main())
