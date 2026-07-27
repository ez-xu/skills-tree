#!/usr/bin/env python
"""VCI CAN 总线适配器 — python-can BusABC 实现，通过子进程桥接 32-bit ControlCAN DLL。

用法（通过 can_tool.py）:
    python can_tool.py --interface vci --channel 0 --listen --duration 10

直接使用:
    import can
    from vci_adapter import register
    register()
    bus = can.Bus(interface="vci", channel=0, bitrate=500000)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional

import can
from can.bus import BusABC, CanProtocol
from can.message import Message

# ---------------------------------------------------------------------------
# 桥接子进程管理
# ---------------------------------------------------------------------------


def _find_bridge_script() -> str:
    """查找 can_bridge.py 的绝对路径。"""
    # 与 vci_adapter.py 同目录
    my_dir = os.path.dirname(os.path.abspath(__file__))
    bridge = os.path.join(my_dir, "can_bridge.py")
    if not os.path.isfile(bridge):
        raise FileNotFoundError(f"找不到 can_bridge.py: {bridge}")
    return bridge


def _find_32bit_python() -> list[str]:
    """查找 32-bit Python 解释器，返回命令行列表（含参数）。"""
    # 优先 py 启动器的 32-bit 标签
    candidate_groups = [["py", "-3.11-32"], ["py"], ["python"]]
    for cmd_parts in candidate_groups:
        try:
            result = subprocess.run(
                cmd_parts + ["-c", "import struct; print(struct.calcsize('P')*8)"],
                capture_output=True, text=True, timeout=5, shell=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "32":
                return cmd_parts  # 返回完整命令行
        except Exception:
            continue
    raise RuntimeError(
        "未找到 32-bit Python。请安装 32-bit Python 3.11 并确保 py 启动器可用。\n"
        "下载: https://www.python.org/downloads/ (选择 32-bit installer)"
    )


class VciBus(BusABC):
    """VCI CAN 总线适配器。

    通过子进程启动 32-bit can_bridge.py，利用 ctypes 调用 ControlCAN DLL，
    与 GCAN/ZLG/CX USBCAN 适配器通信。

    :param channel:
        CAN 通道编号，从 1 开始（1=CAN1→can_index=0, 2=CAN2→can_index=1）。
    :param can_filters:
        python-can 消息过滤器列表。
    :param kwargs:
        后端专用参数:
        - dll: DLL 文件名 (默认 "ControlCAN_CX.dll")
        - dev_type: 设备类型 (默认 4=USBCAN_2)
        - dev_index: 设备索引 (默认 0)
        - bitrate: 波特率 (默认 500000)
        - python: 32-bit Python 解释器路径 (默认自动检测)
    """

    def __init__(
        self,
        channel: Any = 1,
        can_filters: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        # 解析参数：用户侧 1-based，转换为 DLL 的 0-based can_index
        user_channel = int(channel) if channel is not None else 1
        if user_channel < 1:
            raise ValueError(f"VCI 通道编号从 1 开始，收到: {user_channel}")
        self._can_index = user_channel - 1
        self._dll = kwargs.pop("dll", None)
        if self._dll is None:
            raise can.CanInterfaceNotImplementedError(
                "VCI 接口必须指定 dll 参数（DLL 必须匹配硬件品牌）。\n"
                "GCAN 硬件: dll='ControlCAN_GC.dll'\n"
                "创芯 硬件: dll='ControlCAN_CX.dll'\n"
                "ZLG  硬件: dll='ControlCAN_ZLG.dll'"
            )
        self._dev_type = int(kwargs.pop("dev_type", 4))
        self._dev_index = int(kwargs.pop("dev_index", 0))
        self._bitrate = int(kwargs.pop("bitrate", 500000))
        python_exe = kwargs.pop("python", None)

        self._proc: Optional[subprocess.Popen] = None
        self._open = False

        # 找 32-bit Python
        bridge_script = _find_bridge_script()
        if python_exe:
            py_cmd = [python_exe]
        else:
            try:
                py_cmd = _find_32bit_python()
            except RuntimeError:
                raise can.CanInterfaceNotImplementedError(
                    "VCI 接口需要 32-bit Python (ControlCAN DLL 是 32-bit)。\n"
                    "请安装后重试，或使用其他 CAN 接口。"
                )

        # 启动桥接子进程（强制 UTF-8 避免 GBK 编码兼容问题）
        cmd = py_cmd + [bridge_script, "--session"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"  # 子进程 stdout/stderr 使用 UTF-8
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # 捕获 stderr 用于诊断，用 daemon 线程防死锁
                encoding="utf-8",  # 父进程以 UTF-8 解码子进程输出
                errors="replace",  # 对无法解码的字节用替换字符
                bufsize=1,  # 行缓冲
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            # 后台线程持续读取 bridge 的 stderr，防止 pipe 缓冲满导致死锁，
            # 同时将 bridge 的诊断输出转发到父进程 stderr 方便调试
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, daemon=True
            )
            self._stderr_thread.start()
        except FileNotFoundError:
            raise can.CanInterfaceNotImplementedError(
                f"无法启动桥接子进程: {' '.join(cmd)}\n"
                "请确保 32-bit Python 已安装且 py 启动器可用。"
            )

        # 初始化设备序列: open → init → start
        try:
            self._cmd("open", dll=self._dll, dev_type=self._dev_type, dev_index=self._dev_index)
            self._cmd("init", can_index=self._can_index, bitrate=self._bitrate, mode=0)
            self._cmd("start", can_index=self._can_index)
            self._open = True
        except Exception:
            self._cleanup_proc()
            raise

        # 读取板卡信息用于 channel_info
        try:
            info = self._cmd("info")
            self.channel_info = (
                f"VCI {self._dll} CAN{self._can_index} "
                f"[{info.get('hw_type', '?')} SN:{info.get('serial', '?')}]"
            )
        except Exception:
            self.channel_info = f"VCI {self._dll} CAN{self._can_index}"

        self._can_protocol = CanProtocol.CAN_20

        # 最后调用父类构造函数（放 try/finally 中防止子进程泄漏）
        try:
            super().__init__(channel=channel, can_filters=can_filters, **kwargs)
        except Exception:
            self._cleanup_proc()
            raise

    # ---- 子进程通信 ----------------------------------------------------

    def _cmd(self, cmd: str, **params: Any) -> Any:
        """发送 JSON 命令到桥接子进程，读取并返回 JSON 响应。"""
        if self._proc is None or self._proc.stdin is None:
            raise can.CanOperationError("桥接子进程未启动")

        payload = json.dumps({"cmd": cmd, **params}, ensure_ascii=False)
        try:
            self._proc.stdin.write(payload + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise can.CanOperationError(f"写入桥接子进程失败: {e}")

        # 读取响应
        try:
            line = self._proc.stdout.readline()
        except Exception as e:
            raise can.CanOperationError(f"读取桥接子进程失败: {e}")

        if not line:
            # 子进程已退出
            self._check_proc_dead()
            raise can.CanOperationError("桥接子进程意外退出")

        try:
            response = json.loads(line.strip())
        except json.JSONDecodeError:
            raise can.CanOperationError(f"桥接子进程返回无效 JSON: {line[:200]}")

        if not response.get("ok"):
            err = response.get("error", "未知错误")
            raise can.CanOperationError(f"VCI {cmd} 失败: {err}")

        return response["data"]

    def _check_proc_dead(self) -> None:
        """检查子进程是否意外退出。

        尝试收集 stderr 中残留的诊断信息辅助错误消息。
        """
        if self._proc and self._proc.poll() is not None:
            stderr_tail = ""
            if self._proc.stderr:
                try:
                    # 尝试非阻塞读取残留 stderr（buffer 中可能还有数据）
                    import select
                    while select.select([self._proc.stderr], [], [], 0)[0]:
                        line = self._proc.stderr.readline()
                        if line:
                            stderr_tail += line
                except Exception:
                    pass
            msg = f"桥接子进程已退出 (code={self._proc.returncode})"
            if stderr_tail:
                msg += f"\nstderr 残留: {stderr_tail[:500]}"
            raise can.CanOperationError(msg)

    def _drain_stderr(self) -> None:
        """后台线程：持续读取 bridge 子进程的 stderr 并转发到父进程 stderr。

        防止 pipe 缓冲满导致死锁，同时保留 bridge 的诊断输出供调试。
        """
        try:
            while self._proc and self._proc.stderr:
                line = self._proc.stderr.readline()
                if not line:
                    break  # stderr 已关闭（子进程退出）
                # 转发到父进程 stderr（容忍编码错误）
                try:
                    sys.stderr.write(f"[bridge] {line}")
                except UnicodeEncodeError:
                    sys.stderr.write(f"[bridge] {line.encode('ascii', errors='replace').decode('ascii')}")
                sys.stderr.flush()
        except Exception:
            pass  # 子进程关闭时 stderr 读取可能抛异常

    def _cleanup_proc(self) -> None:
        """关闭子进程。"""
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.write('{"cmd":"quit"}\n')
                    self._proc.stdin.flush()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            except Exception:
                pass
            self._proc = None

    # ---- BusABC 接口 ---------------------------------------------------

    def _recv_internal(
        self, timeout: Optional[float]
    ) -> tuple[Optional[Message], bool]:
        """从 CAN 总线接收一帧。

        :param timeout: 等待超时（秒），None=阻塞等待, 0=立即返回, >0=超时秒数
        :return: (Message, False) 或 (None, False)
        :raises can.CanOperationError: 底层读取出错时抛出（不吞错误）
        """
        if not self._open:
            raise can.CanOperationError("Cannot operate on a closed bus")

        # None=阻塞等待, 0=非阻塞, >0=超时秒数
        if timeout is None:
            timeout_ms = 10000  # 大超时值（协议限制，非真正无限）
        else:
            timeout_ms = int(timeout * 1000)
        timeout_ms = max(timeout_ms, 0)  # 允许 0 表示非阻塞

        data = self._cmd("recv", can_index=self._can_index, timeout=timeout_ms, max_frames=1)

        frames = data.get("frames", [])
        if not frames:
            return None, False

        f = frames[0]
        msg = Message(
            arbitration_id=f["id_int"],
            is_extended_id=f.get("extended", False),
            is_remote_frame=f.get("remote", False),
            dlc=f.get("dlc", 0),
            data=self._hex_to_bytes(f.get("data", "")),
            timestamp=f.get("timestamp", time.time()),
            channel=self._can_index,
        )
        return msg, False

    def send(self, msg: Message, timeout: Optional[float] = None) -> None:
        """发送一帧到 CAN 总线。"""
        if not self._open:
            raise can.CanOperationError("Cannot operate on a closed bus")

        data_hex = ",".join(f"{b:02X}" for b in msg.data)
        self._cmd(
            "send",
            can_index=self._can_index,
            id=msg.arbitration_id,
            data=data_hex,
            extended=msg.is_extended_id,
            remote=msg.is_remote_frame,
        )

    def shutdown(self) -> None:
        """关闭总线，释放资源。"""
        try:
            super().shutdown()
        finally:
            if self._open:
                self._open = False
                try:
                    self._cmd("close")
                except Exception:
                    pass
            self._cleanup_proc()

    def flush_tx_buffer(self) -> None:
        """清空接收缓冲区。

        注意：VCI API 的 VCI_ClearBuffer 清除的是接收缓冲区（RX），
        而非发送缓冲区（TX）。VCI API 没有独立的 TX 缓冲区清除函数。
        调用此方法会丢弃所有已接收但未读取的 CAN 帧。
        """
        if self._open:
            try:
                self._cmd("clear", can_index=self._can_index)
            except Exception:
                pass

    # ---- 辅助方法 ------------------------------------------------------

    @staticmethod
    def _hex_to_bytes(data_str: str) -> bytes:
        """将 "01 02 FF" 格式的十六进制字符串转为 bytes。"""
        if not data_str:
            return b""
        return bytes(int(b, 16) for b in data_str.split())

    def __del__(self) -> None:
        """析构时确保子进程被清理。"""
        try:
            self._cleanup_proc()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 注册到 python-can BACKENDS
# ---------------------------------------------------------------------------


def register() -> None:
    """将 VCI 后端注册到 python-can 的 BACKENDS 字典。

    调用后即可使用:
        can.Bus(interface="vci", channel=0, bitrate=500000)
    """
    import can.interfaces
    import can.util

    if "vci" not in can.interfaces.BACKENDS:
        can.interfaces.BACKENDS["vci"] = (__name__, "VciBus")
        # 重建 VALID_INTERFACES（原为 frozenset，config 加载时用于校验）
        # 必须同时更新 can.interfaces 和 can.util 中的引用
        new_valid = frozenset(sorted(can.interfaces.BACKENDS.keys()))
        can.interfaces.VALID_INTERFACES = new_valid
        can.util.VALID_INTERFACES = new_valid


# 模块导入时自动注册
register()
