#!/usr/bin/env python
"""GCAN ControlCAN DLL 桥接 — 32-bit Python 用 ctypes 调 ControlCAN.dll。

被 can_tool.py 作为子进程调用，JSON 行协议通信，不依赖 python-can。
"""

from __future__ import annotations

import ctypes
import json
import sys
import os
import time
from ctypes import wintypes
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 设备类型 (Can_dll_list.ini)
DEVICE_TYPES = {
    "GCAN": 4,  # USBCAN_2
    "CX": 4,
    "ZLG": 4,
    "ZLG_EU": 21,  # USBCAN_2E
    "Tiny": 4,
}

# 通用波特率时序表（16MHz 晶振，SJA1000 兼容）
BITRATE_TIMING = {
    1000000: (0x00, 0x14),
    800000:  (0x00, 0x16),
    500000:  (0x00, 0x1C),
    250000:  (0x01, 0x1C),
    125000:  (0x03, 0x1C),
    100000:  (0x04, 0x1C),
    50000:   (0x09, 0x1C),
    20000:   (0x18, 0x1C),
    10000:   (0x31, 0x1C),
}

STATUS_OK = 1


# ---------------------------------------------------------------------------
# 结构体
# ---------------------------------------------------------------------------

class VCI_INIT_CONFIG(ctypes.Structure):
    _fields_ = [
        ("AccCode",  ctypes.c_uint32),
        ("AccMask",  ctypes.c_uint32),
        ("Reserved", ctypes.c_uint32),
        ("Filter",   ctypes.c_uint8),
        ("Timing0",  ctypes.c_uint8),
        ("Timing1",  ctypes.c_uint8),
        ("Mode",     ctypes.c_uint8),
    ]


class VCI_CAN_OBJ(ctypes.Structure):
    _fields_ = [
        ("ID",         ctypes.c_uint32),
        ("TimeStamp",  ctypes.c_uint32),
        ("TimeFlag",   ctypes.c_uint8),
        ("SendType",   ctypes.c_uint8),
        ("RemoteFlag", ctypes.c_uint8),
        ("ExternFlag", ctypes.c_uint8),
        ("DataLen",    ctypes.c_uint8),
        ("Data",       ctypes.c_uint8 * 8),
        ("Reserved",   ctypes.c_uint8 * 3),
    ]


class VCI_BOARD_INFO(ctypes.Structure):
    _fields_ = [
        ("hw_Version",      ctypes.c_uint16),
        ("fw_Version",      ctypes.c_uint16),
        ("dr_Version",      ctypes.c_uint16),
        ("in_Version",      ctypes.c_uint16),
        ("irq_Num",         ctypes.c_uint16),
        ("can_Num",         ctypes.c_uint8),
        ("str_Serial_Num",  ctypes.c_uint8 * 20),
        ("str_hw_Type",     ctypes.c_uint8 * 40),
        ("Reserved",        ctypes.c_uint16 * 4),
    ]


class VCI_CAN_STATUS(ctypes.Structure):
    _fields_ = [
        ("ErrInterrupt", ctypes.c_uint8),
        ("regMode",      ctypes.c_uint8),
        ("regStatus",    ctypes.c_uint8),
        ("regALCapture", ctypes.c_uint8),
        ("regECCapture", ctypes.c_uint8),
        ("regEWLimit",   ctypes.c_uint8),
        ("regRECounter", ctypes.c_uint8),
        ("regTECounter", ctypes.c_uint8),
        ("Reserved",     ctypes.c_uint32),
    ]


class VCI_ERR_INFO(ctypes.Structure):
    _fields_ = [
        ("ErrCode",           ctypes.c_uint32),
        ("Passive_ErrData",   ctypes.c_uint8 * 3),
        ("ArLost_ErrData",    ctypes.c_uint8),
    ]


class VCI_USB_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("DevType",    ctypes.c_uint32),
        ("DevIndex",   ctypes.c_uint32),
        ("CANIndex",   ctypes.c_uint32),
        ("Reserved",   ctypes.c_uint32),
    ]


# ---------------------------------------------------------------------------
# DLL 加载与函数绑定
# ---------------------------------------------------------------------------

class CanBridge:
    """GCAN ControlCAN 桥接封装。"""

    def __init__(self, dll_name: str = "ControlCAN_CX.dll"):
        # 确定 DLL 目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dll_dir = os.path.join(os.path.dirname(script_dir), "dll")
        dll_path = os.path.join(dll_dir, dll_name)

        if not os.path.isfile(dll_path):
            raise FileNotFoundError(f"DLL not found: {dll_path}")

        # 加载 DLL 前先切换到 DLL 目录（解决依赖 DLL 搜索问题）
        old_cwd = os.getcwd()
        os.chdir(dll_dir)
        try:
            self._dll = ctypes.WinDLL(dll_path)
        finally:
            os.chdir(old_cwd)

        self.dll_path = dll_path
        self.dev_type = 0
        self.dev_index = 0
        self._bind_functions()

    def _bind_functions(self):
        d = self._dll

        def _bind(name, argtypes=None, restype=ctypes.c_uint32):
            """安全绑定函数，不存在的函数返回 None。"""
            try:
                func = getattr(d, name)
                if argtypes:
                    func.argtypes = argtypes
                func.restype = restype
                return func
            except AttributeError:
                return None

        # VCI_OpenDevice
        self._OpenDevice = _bind("VCI_OpenDevice",
                                  [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
                                  ctypes.c_uint32)
        # VCI_CloseDevice
        self._CloseDevice = _bind("VCI_CloseDevice",
                                   [ctypes.c_uint32, ctypes.c_uint32],
                                   ctypes.c_uint32)
        # VCI_InitCAN
        self._InitCAN = _bind("VCI_InitCAN",
                               [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.POINTER(VCI_INIT_CONFIG)],
                               ctypes.c_uint32)
        # VCI_StartCAN
        self._StartCAN = _bind("VCI_StartCAN",
                                [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
                                ctypes.c_uint32)
        # VCI_ResetCAN
        self._ResetCAN = _bind("VCI_ResetCAN",
                                [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
                                ctypes.c_uint32)
        # VCI_Transmit
        self._Transmit = _bind("VCI_Transmit",
                                [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(VCI_CAN_OBJ), ctypes.c_uint32],
                                ctypes.c_uint32)
        # VCI_Receive
        self._Receive = _bind("VCI_Receive",
                               [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.POINTER(VCI_CAN_OBJ), ctypes.c_uint32,
                                ctypes.c_uint32],
                               ctypes.c_uint32)
        # VCI_GetReceiveNum
        self._GetReceiveNum = _bind("VCI_GetReceiveNum",
                                     [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
                                     ctypes.c_uint32)
        # VCI_ClearBuffer
        self._ClearBuffer = _bind("VCI_ClearBuffer",
                                   [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32],
                                   ctypes.c_uint32)
        # VCI_ReadBoardInfo
        self._ReadBoardInfo = _bind("VCI_ReadBoardInfo",
                                     [ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.POINTER(VCI_BOARD_INFO)],
                                     ctypes.c_uint32)
        # VCI_ReadCANStatus
        self._ReadCANStatus = _bind("VCI_ReadCANStatus",
                                     [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.POINTER(VCI_CAN_STATUS)],
                                     ctypes.c_uint32)
        # VCI_ReadErrInfo
        self._ReadErrInfo = _bind("VCI_ReadErrInfo",
                                   [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.POINTER(VCI_ERR_INFO)],
                                   ctypes.c_uint32)
        # VCI_FindUsbDevice (部分 DLL 不支持)
        self._FindUsbDevice = _bind("VCI_FindUsbDevice",
                                     [ctypes.POINTER(VCI_USB_DEVICE_INFO)],
                                     ctypes.c_uint32)
        # VCI_FindUsbDevice2 (新版 DLL)
        self._FindUsbDevice2 = _bind("VCI_FindUsbDevice2",
                                      [ctypes.POINTER(VCI_USB_DEVICE_INFO)],
                                      ctypes.c_uint32)
        # VCI_SetReference (部分 DLL 不支持)
        self._SetReference = _bind("VCI_SetReference",
                                    [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                     ctypes.c_uint32, ctypes.c_void_p],
                                    ctypes.c_uint32)

    # ---- 基础操作 ----------------------------------------------------------

    def open(self, dev_type: int, dev_index: int) -> bool:
        self.dev_type = dev_type
        self.dev_index = dev_index
        return self._OpenDevice(dev_type, dev_index, 0) == STATUS_OK

    def close(self) -> bool:
        return self._CloseDevice(self.dev_type, self.dev_index) == STATUS_OK

    def set_reference(self, can_index: int, ref_type: int = 0) -> bool:
        """设置 CAN 控制器参考时钟源（必须在 InitCAN 之前调用）。

        部分 GCAN 设备需要此调用，但某些 DLL 版本不支持或会崩溃。
        默认不调用，在 init_can 中由 ref_type 参数控制是否启用。

        :param can_index: CAN 通道索引 (0-based)
        :param ref_type: 0=内部时钟, 1=外部时钟
        :return: 是否成功
        """
        if self._SetReference is None:
            try:
                sys.stderr.write("[WARN] DLL 不支持 VCI_SetReference，跳过\n")
            except UnicodeEncodeError:
                pass
            sys.stderr.flush()
            return True  # DLL 不支持，不是错误
        try:
            # 分配一个零填充的缓冲区作为 pData（避免 NULL 指针崩溃）
            ref_data = (ctypes.c_uint8 * 16)()
            ret = self._SetReference(self.dev_type, self.dev_index, can_index,
                                     ref_type, ctypes.byref(ref_data))
            return ret == STATUS_OK
        except OSError as e:
            try:
                sys.stderr.write(f"[ERROR] VCI_SetReference 调用异常: {e}\n")
            except UnicodeEncodeError:
                pass
            sys.stderr.flush()
            return False  # 调用崩溃，向上报告失败

    def init_can(self, can_index: int, bitrate: int, mode: int = 0) -> bool:
        """初始化 CAN 控制器。

        注意：GCAN USBCAN-II 硬件对标准帧支持有问题。
        GC DLL 的 Transmit 间歇性返回 -1，建议使用 CX DLL (ControlCAN_CX.dll)。
        CX DLL 与 GCAN 硬件兼容，扩展帧收发正常（回环测试已确认）。
        """
        t0, t1 = BITRATE_TIMING.get(bitrate, (0x00, 0x1C))
        cfg = VCI_INIT_CONFIG()
        cfg.AccCode = 0x00000000  # 接收所有帧
        cfg.AccMask = 0xFFFFFFFF
        cfg.Filter = 1           # 双滤波模式
        cfg.Timing0 = t0
        cfg.Timing1 = t1
        cfg.Mode = mode          # 0=正常, 1=只听, 2=自测
        ret = self._InitCAN(self.dev_type, self.dev_index, can_index,
                            ctypes.byref(cfg))
        return ret == STATUS_OK

    def start_can(self, can_index: int) -> bool:
        """启动 CAN 控制器。

        GCAN USBCAN-II 的 CAN 控制器从复位模式退出后需要短暂稳定时间，
        否则 VCI_Transmit 会返回 -1。加入 200ms 延迟确保控制器就绪。
        """
        ok = self._StartCAN(self.dev_type, self.dev_index, can_index) == STATUS_OK
        if ok:
            time.sleep(0.2)  # CAN 控制器退出复位后稳定等待
        return ok

    def reset_can(self, can_index: int) -> bool:
        return self._ResetCAN(self.dev_type, self.dev_index, can_index) == STATUS_OK

    # ---- 收发 ---------------------------------------------------------------

    def send(self, can_index: int, arb_id: int, data: bytes,
             extended: bool = False, remote: bool = False,
             retries: int = 3) -> bool:
        """发送 CAN 帧，带自动重试。

        GCAN USBCAN-II 的 VCI_Transmit 在控制器刚启动时可能返回 -1，
        自动重试机制可应对此情况。
        """
        obj = VCI_CAN_OBJ()
        obj.ID = arb_id
        obj.ExternFlag = 1 if extended else 0
        obj.RemoteFlag = 1 if remote else 0
        dlen = min(len(data), 8)  # 经典 CAN DLC 最大 8，截断超长数据
        obj.DataLen = dlen
        for i, b in enumerate(data[:dlen]):
            obj.Data[i] = b
        obj.SendType = 0  # 正常发送
        for attempt in range(retries):
            ret = self._Transmit(self.dev_type, self.dev_index, can_index,
                                 ctypes.byref(obj), 1)
            if ret == STATUS_OK:
                return True
            if attempt + 1 < retries:
                # VCI_Transmit 返回非 1 即为失败，短暂等待后重试
                # 常见瞬时故障：0xFFFFFFFF（控制器未就绪）、0（缓冲区满）等
                time.sleep(0.05)
        return False

    def send_ex(self, can_index: int, arb_id: int, data: bytes,
                extended: bool = False, remote: bool = False) -> int:
        """发送 CAN 帧，返回原始 VCI_Transmit 返回值（用于诊断）。"""
        obj = VCI_CAN_OBJ()
        obj.ID = arb_id
        obj.ExternFlag = 1 if extended else 0
        obj.RemoteFlag = 1 if remote else 0
        dlen = min(len(data), 8)  # 经典 CAN DLC 最大 8
        obj.DataLen = dlen
        for i, b in enumerate(data[:dlen]):
            obj.Data[i] = b
        obj.SendType = 0  # 正常发送
        return self._Transmit(self.dev_type, self.dev_index, can_index,
                              ctypes.byref(obj), 1)

    def recv(self, can_index: int, timeout_ms: int = 1000,
             max_frames: int = 256) -> list[dict]:
        """接收 CAN 帧，返回帧列表。

        :param can_index: CAN 通道索引 (0-based)
        :param timeout_ms: 等待超时（毫秒），0=立即返回
        :param max_frames: 单次最多返回帧数
        :return: 帧字典列表，每个包含 timestamp(秒)/id/id_int/dlc/data/extended/remote
        """
        frames = []
        # 查询缓冲帧数，校验 DLL 返回值（0xFFFFFFFF 表示调用失败）
        count = self._GetReceiveNum(self.dev_type, self.dev_index, can_index)
        if count == 0xFFFFFFFF:
            return frames  # DLL 调用异常，返回空
        if count == 0 and timeout_ms > 0:
            # 缓冲区为空，轮询等待直到超时
            deadline = time.time() + timeout_ms / 1000.0
            while time.time() < deadline:
                count = self._GetReceiveNum(self.dev_type, self.dev_index, can_index)
                if count == 0xFFFFFFFF:
                    return frames  # DLL 异常
                if count > 0:
                    break
                time.sleep(0.01)
            else:
                return frames  # 超时，无帧

        # 从缓冲区取出帧（最多 max_frames 帧）
        for _ in range(min(count, max_frames)):
            obj = VCI_CAN_OBJ()
            ret = self._Receive(self.dev_type, self.dev_index, can_index,
                                ctypes.byref(obj), 1, 0)
            if ret != STATUS_OK:
                break
            # 防止畸形帧 DataLen > 8 导致越界访问 Data[8]
            safe_dlen = min(obj.DataLen, 8)
            frames.append({
                "timestamp": obj.TimeStamp * 0.0001,  # GCAN 时间戳单位 0.1ms → 秒
                "id": f"0x{obj.ID:08X}" if obj.ExternFlag else f"0x{obj.ID:03X}",
                "id_int": obj.ID,
                "dlc": safe_dlen,
                "data": " ".join(f"{obj.Data[i]:02X}" for i in range(safe_dlen)),
                "extended": bool(obj.ExternFlag),
                "remote": bool(obj.RemoteFlag),
            })
        return frames

    def get_receive_num(self, can_index: int) -> int:
        return self._GetReceiveNum(self.dev_type, self.dev_index, can_index)

    def clear_buffer(self, can_index: int) -> bool:
        return self._ClearBuffer(self.dev_type, self.dev_index, can_index) == STATUS_OK

    # ---- 信息查询 -----------------------------------------------------------

    def read_board_info(self) -> dict | None:
        info = VCI_BOARD_INFO()
        if self._ReadBoardInfo(self.dev_type, self.dev_index,
                               ctypes.byref(info)) != STATUS_OK:
            return None
        return {
            "hw_version": f"{info.hw_Version:04X}",
            "fw_version": f"{info.fw_Version:04X}",
            "dr_version": f"{info.dr_Version:04X}",
            "in_version": f"{info.in_Version:04X}",
            "irq_num": info.irq_Num,
            "can_num": info.can_Num,
            "serial": bytes(info.str_Serial_Num).rstrip(b"\x00").decode("ascii", errors="replace"),
            "hw_type": bytes(info.str_hw_Type).rstrip(b"\x00").decode("ascii", errors="replace"),
        }

    def read_can_status(self, can_index: int) -> dict | None:
        st = VCI_CAN_STATUS()
        if self._ReadCANStatus(self.dev_type, self.dev_index, can_index,
                               ctypes.byref(st)) != STATUS_OK:
            return None
        return {
            "err_interrupt": st.ErrInterrupt,
            "mode": st.regMode,
            "status": st.regStatus,
            "rx_err_count": st.regRECounter,
            "tx_err_count": st.regTECounter,
        }

    def read_err_info(self, can_index: int) -> dict | None:
        ei = VCI_ERR_INFO()
        if self._ReadErrInfo(self.dev_type, self.dev_index, can_index,
                             ctypes.byref(ei)) != STATUS_OK:
            return None
        return {
            "err_code": ei.ErrCode,
            "passive_err": " ".join(f"{ei.Passive_ErrData[i]:02X}" for i in range(3)),
            "ar_lost_err": ei.ArLost_ErrData,
        }

    def find_usb_devices(self) -> list[dict]:
        """扫描 USB 设备列表（VCI_FindUsbDevice）。"""
        if self._FindUsbDevice is None:
            return []  # DLL 不支持此函数
        devs = (VCI_USB_DEVICE_INFO * 20)()
        count = self._FindUsbDevice(devs)
        result = []
        for i in range(min(count, 20)):
            dev = devs[i]
            if dev.DevType > 0:
                result.append({
                    "dev_type": dev.DevType,
                    "dev_index": dev.DevIndex,
                    "can_index": dev.CANIndex,
                })
        return result


# ---------------------------------------------------------------------------
# JSON 命令行协议
# ---------------------------------------------------------------------------

def session_mode() -> int:
    """持久会话模式：循环读 stdin JSON 命令行，保持设备打开直到 quit。

    命令:
      {"cmd":"open",   "dll":"ControlCAN_CX.dll", "dev_type":4, "dev_index":0}
      {"cmd":"close"}
      {"cmd":"init",   "can_index":0, "bitrate":500000, "mode":0}
      {"cmd":"start",  "can_index":0}
      {"cmd":"reset",  "can_index":0}
      {"cmd":"send",   "can_index":0, "id":4660, "data":"01,02,03", "extended":true}
      {"cmd":"recv",   "can_index":0, "timeout":1000, "max_frames":256}
      {"cmd":"count",  "can_index":0}
      {"cmd":"clear",  "can_index":0}
      {"cmd":"info"}
      {"cmd":"status", "can_index":0}
      {"cmd":"err",    "can_index":0}
      {"cmd":"find"}
      {"cmd":"quit"}

    返回 (每行):
      {"ok":true, "data": ...}  或  {"ok":false, "error":"..."}
    """
    bridge = None
    dll_name = "ControlCAN_CX.dll"
    _session_opened = False  # 追踪设备是否已 open，防止未 open 就 send/recv

    while True:
        try:
            raw = sys.stdin.readline()
            if not raw:
                break  # stdin 关闭

            cmd = json.loads(raw.strip())
            action = cmd.get("cmd", "")

            if action == "quit":
                _ok({"msg": "session closed"})
                break

            # 延迟创建桥接（允许首次命令指定 dll）
            if bridge is None:
                dll_name = cmd.get("dll", dll_name)
                bridge = CanBridge(dll_name)

            # 强制 open-before-use：send/recv/init/start 必须在 open 之后
            ops_require_open = {"send", "recv", "init", "start", "reset",
                                "clear", "status", "err", "listen"}
            if action in ops_require_open and not _session_opened:
                raise RuntimeError(
                    f"命令 '{action}' 需要先执行 'open'。请先发送 open 命令。"
                )

            result = _dispatch_vci(bridge, cmd)
            _ok(result)

            # 追踪 open/close 状态
            if action == "open":
                _session_opened = True
            elif action == "close":
                _session_opened = False

        except json.JSONDecodeError as e:
            _err(f"JSON 解析错误: {e}")
        except Exception as e:
            _err(str(e))
            # 致命错误时退出 session
            if bridge is None:
                break

    # 清理
    if bridge:
        try:
            bridge.close()
        except Exception:
            pass
    return 0


def _dispatch_vci(bridge: CanBridge, cmd: dict) -> Any:
    """VCI 命令分发器，仅用于 session/JSON 模式。"""
    action = cmd["cmd"]

    if action == "open":
        dt = cmd.get("dev_type", 4)
        di = cmd.get("dev_index", 0)
        if not bridge.open(dt, di):
            raise RuntimeError(f"VCI_OpenDevice(dev_type={dt}, dev_index={di}) 失败")
        return {"msg": f"设备已打开 dev_type={dt} dev_index={di}"}

    elif action == "close":
        if not bridge.close():
            raise RuntimeError("VCI_CloseDevice 失败")
        return {"msg": "设备已关闭"}

    elif action == "init":
        ci = cmd.get("can_index", 0)
        br = cmd.get("bitrate", 500000)
        mode = cmd.get("mode", 0)
        if not bridge.init_can(ci, br, mode):
            raise RuntimeError(f"VCI_InitCAN(can_index={ci}, bitrate={br}) 失败")
        return {"msg": f"CAN{ci} 已初始化 波特率={br}"}

    elif action == "start":
        ci = cmd.get("can_index", 0)
        if not bridge.start_can(ci):
            raise RuntimeError(f"VCI_StartCAN(can_index={ci}) 失败")
        return {"msg": f"CAN{ci} 已启动"}

    elif action == "reset":
        ci = cmd.get("can_index", 0)
        if not bridge.reset_can(ci):
            raise RuntimeError(f"VCI_ResetCAN(can_index={ci}) 失败")
        return {"msg": f"CAN{ci} 已复位"}

    elif action == "send":
        ci = cmd.get("can_index", 0)
        arb_id = cmd["id"]
        data_str = cmd.get("data", "")
        data = bytes(int(b, 16) for b in data_str.split(",")) if data_str else b""
        extended = cmd.get("extended", False)
        remote = cmd.get("remote", False)
        if not bridge.send(ci, arb_id, data, extended, remote):
            raise RuntimeError(
                f"VCI_Transmit(id=0x{arb_id:X}, can_index={ci}) 失败（已重试）"
            )
        return {"msg": f"已发送 ID=0x{arb_id:X} data={data_str}"}

    elif action == "recv":
        ci = cmd.get("can_index", 0)
        timeout = cmd.get("timeout", 1000)
        max_frames = cmd.get("max_frames", 256)
        frames = bridge.recv(ci, timeout, max_frames)
        return {"frames": frames}

    elif action == "count":
        ci = cmd.get("can_index", 0)
        return {"count": bridge.get_receive_num(ci)}

    elif action == "clear":
        ci = cmd.get("can_index", 0)
        if not bridge.clear_buffer(ci):
            raise RuntimeError(f"VCI_ClearBuffer(can_index={ci}) 失败")
        return {"msg": f"CAN{ci} 缓冲区已清除"}

    elif action == "info":
        info = bridge.read_board_info()
        if info is None:
            raise RuntimeError("VCI_ReadBoardInfo 失败")
        return info

    elif action == "status":
        ci = cmd.get("can_index", 0)
        st = bridge.read_can_status(ci)
        if st is None:
            raise RuntimeError(f"VCI_ReadCANStatus(can_index={ci}) 失败")
        return st

    elif action == "err":
        ci = cmd.get("can_index", 0)
        ei = bridge.read_err_info(ci)
        if ei is None:
            raise RuntimeError(f"VCI_ReadErrInfo(can_index={ci}) 失败")
        return ei

    elif action == "find":
        devs = bridge.find_usb_devices()
        return {"devices": devs}

    elif action == "listen":
        # session 模式下的 listen：持续接收并即时输出帧文本
        ci = cmd.get("can_index", 0)
        duration = cmd.get("duration", 0)
        filter_range = cmd.get("filter", None)

        lo_id, hi_id = None, None
        if filter_range:
            parts = filter_range.split("-")
            lo_id = int(parts[0], 16) if "0x" in parts[0].lower() else int(parts[0])
            hi_id = int(parts[1], 16) if len(parts) > 1 and "0x" in parts[1].lower() else (int(parts[1]) if len(parts) > 1 else lo_id)

        frames = []
        deadline = time.time() + duration if duration > 0 else float("inf")
        while time.time() < deadline:
            # 在 session 模式下也检查是否有新命令（非阻塞读 stdin）
            if duration > 0:
                # 有限时长直接用阻塞模式
                batch = bridge.recv(ci, timeout=min(500, int((deadline - time.time()) * 1000)), max_frames=50)
            else:
                batch = bridge.recv(ci, timeout=500, max_frames=50)

            for f in batch:
                if lo_id is not None and not (lo_id <= f["id_int"] <= hi_id):
                    continue
                frames.append(f)
                ts = time.strftime("%H:%M:%S", time.localtime())
                rtr = " RTR" if f["remote"] else ""
                print(f"  [{ts}] {f['id']}  [{f['dlc']}]  {f['data']}{rtr}", flush=True)

        return {"frames": frames}

    else:
        raise ValueError(f"未知命令: {action}")


def json_cmd() -> int:
    """单次 JSON 命令模式（兼容旧用法）。读一行，执行，输出结果。"""
    return session_mode()  # session 模式同样支持单次调用



def _ok(data: Any) -> None:
    """向 stdout 写入成功响应 JSON 行。"""
    sys.stdout.write(json.dumps({"ok": True, "data": data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(msg: str) -> None:
    """向 stderr 写入错误消息，向 stdout 写入错误响应 JSON 行。

    stderr 写入容忍编码错误（部分终端配置为 GBK，不支持特殊字符）。
    """
    try:
        sys.stderr.write(msg + "\n")
    except UnicodeEncodeError:
        # 终端编码不支持某些字符，回退到 ASCII 安全版本
        sys.stderr.write(msg.encode("ascii", errors="replace").decode("ascii") + "\n")
    sys.stderr.flush()
    sys.stdout.write(json.dumps({"ok": False, "error": msg}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 直接命令行模式（不用 stdin JSON）
# ---------------------------------------------------------------------------

def direct_main():
    """直接命令行参数模式，方便手动测试。

    python can_bridge.py find [dll]
    python can_bridge.py info [dev_type] [dev_index] [dll]
    python can_bridge.py listen [dev_type] [dev_index] [can_index] [bitrate] [duration] [dll]
    python can_bridge.py send <id> <data> [dev_type] [dev_index] [can_index] [bitrate] [extended] [dll]
    """
    import argparse
    p = argparse.ArgumentParser(description="GCAN CAN Bridge (ControlCAN ctypes)")
    sub = p.add_subparsers(dest="sub")

    # find
    sp_find = sub.add_parser("find", help="扫描 USB CAN 设备")
    sp_find.add_argument("--dll", default="ControlCAN_CX.dll")

    # info
    sp_info = sub.add_parser("info", help="读取板卡信息")
    sp_info.add_argument("--dev-type", type=int, default=4)
    sp_info.add_argument("--dev-index", type=int, default=0)
    sp_info.add_argument("--dll", default="ControlCAN_CX.dll")

    # listen
    sp_listen = sub.add_parser("listen", help="监听 CAN 总线")
    sp_listen.add_argument("--dev-type", type=int, default=4)
    sp_listen.add_argument("--dev-index", type=int, default=0)
    sp_listen.add_argument("--can-index", type=int, default=0)
    sp_listen.add_argument("--bitrate", type=int, default=500000)
    sp_listen.add_argument("--duration", type=float, default=10, help="0=无限")
    sp_listen.add_argument("--filter", default=None)
    sp_listen.add_argument("--dll", default="ControlCAN_CX.dll")

    # send
    sp_send = sub.add_parser("send", help="发送 CAN 帧")
    sp_send.add_argument("id", help="CAN ID (hex, 如 0x123)")
    sp_send.add_argument("data", nargs="?", default="", help="数据字节 (逗号分隔十六进制)")
    sp_send.add_argument("--dev-type", type=int, default=4)
    sp_send.add_argument("--dev-index", type=int, default=0)
    sp_send.add_argument("--can-index", type=int, default=0)
    sp_send.add_argument("--bitrate", type=int, default=500000)
    sp_send.add_argument("--extended", action="store_true")
    sp_send.add_argument("--dll", default="ControlCAN_CX.dll")

    args = p.parse_args()

    if args.sub is None:
        p.print_help()
        return

    try:
        bridge = CanBridge(args.dll)
    except Exception as e:
        print(f"ERROR: 加载 DLL 失败: {e}")
        sys.exit(1)

    try:
        if args.sub == "find":
            devs = bridge.find_usb_devices()
            if devs:
                print(f"找到 {len(devs)} 个设备:")
                for d in devs:
                    print(f"  DevType={d['dev_type']} DevIndex={d['dev_index']} CANIndex={d['can_index']}")
            else:
                print("未找到 USB CAN 设备")

        elif args.sub == "info":
            dt, di = args.dev_type, args.dev_index
            if not bridge.open(dt, di):
                print(f"ERROR: 打开设备失败 dev_type={dt} dev_index={di}")
                sys.exit(1)
            info = bridge.read_board_info()
            if info:
                print(f"硬件版本: {info['hw_version']}")
                print(f"固件版本: {info['fw_version']}")
                print(f"驱动版本: {info['dr_version']}")
                print(f"接口版本: {info['in_version']}")
                print(f"序列号:   {info['serial']}")
                print(f"硬件类型: {info['hw_type']}")
                print(f"CAN 通道数: {info['can_num']}")
            else:
                print("ERROR: 读取板卡信息失败")
            bridge.close()

        elif args.sub == "listen":
            dt, di, ci = args.dev_type, args.dev_index, args.can_index
            br = args.bitrate
            if not bridge.open(dt, di):
                print(f"ERROR: 打开设备失败")
                sys.exit(1)
            if not bridge.init_can(ci, br):
                print(f"ERROR: 初始化 CAN{ci} 失败")
                bridge.close()
                sys.exit(1)
            if not bridge.start_can(ci):
                print(f"ERROR: 启动 CAN{ci} 失败")
                bridge.close()
                sys.exit(1)

            print(f"CAN{ci} 已启动 波特率={br}")
            print(f"监听中 ({args.duration}s)...  " if args.duration > 0 else "监听中 (Ctrl+C 停止)...")

            # 解析过滤
            lo, hi = None, None
            if args.filter:
                parts = args.filter.split("-")
                lo = int(parts[0], 16) if "0x" in parts[0] else int(parts[0])
                hi = int(parts[1], 16) if len(parts) > 1 and "0x" in parts[1] else (int(parts[1]) if len(parts) > 1 else lo)

            count = 0
            deadline = time.time() + args.duration if args.duration > 0 else float("inf")
            try:
                while time.time() < deadline:
                    frames = bridge.recv(ci, timeout=500, max_frames=50)
                    for f in frames:
                        if lo is not None and not (lo <= f["id_int"] <= hi):
                            continue
                        count += 1
                        ts = time.strftime("%H:%M:%S", time.localtime())
                        rtr = " RTR" if f["remote"] else ""
                        print(f"  [{ts}] {f['id']}  [{f['dlc']}]  {f['data']}{rtr}")
            except KeyboardInterrupt:
                pass

            print(f"\n共收到 {count} 帧")
            bridge.close()

        elif args.sub == "send":
            dt, di, ci = args.dev_type, args.dev_index, args.can_index
            br = args.bitrate
            arb_id = int(args.id, 16) if args.id.startswith("0x") or args.id.startswith("0X") else int(args.id)
            data = bytes(int(b, 16) for b in args.data.split(",")) if args.data else b""

            if not bridge.open(dt, di):
                print(f"ERROR: 打开设备失败")
                sys.exit(1)
            if not bridge.init_can(ci, br):
                print(f"ERROR: 初始化 CAN{ci} 失败")
                bridge.close()
                sys.exit(1)
            if not bridge.start_can(ci):
                print(f"ERROR: 启动 CAN{ci} 失败")
                bridge.close()
                sys.exit(1)

            ok = bridge.send(ci, arb_id, data, args.extended)
            if ok:
                ext_flag = " EXT" if args.extended else ""
                print(f"已发送: 0x{arb_id:03X} [{len(data)}]{ext_flag}  {' '.join(f'{b:02X}' for b in data)}")
            else:
                print("ERROR: 发送失败")
            bridge.close()

    finally:
        try:
            bridge.close()
        except Exception:
            pass


if __name__ == "__main__":
    # --session: 持久会话模式（供 vci_adapter 调用）
    if "--session" in sys.argv:
        sys.argv.remove("--session")
        sys.exit(session_mode())
    # stdin 不是终端：单次 JSON 命令模式（兼容旧用法）
    elif not sys.stdin.isatty():
        sys.exit(json_cmd())
    # 终端交互：CLI 子命令模式
    else:
        direct_main()
