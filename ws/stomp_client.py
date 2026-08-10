"""STOMP over WebSocket 客户端 (迁移自原 live_auction/websocket.py, 配置改读 config.yaml)。"""
from __future__ import annotations

import json
import time
import uuid
from urllib.parse import urlsplit

import allure

try:
    import stomp
except ImportError:  # stomp.py 未安装时仍可被收集, 仅在实际连接时报错
    stomp = None

from commons.logger_util import info_log
from commons.yaml_util import read_config_yaml


def _ws_endpoint():
    parsed = urlsplit(
        read_config_yaml("BASE", "ws_url") or "ws://localhost:8080/ws/websocket"
    )
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    return parsed.hostname or "localhost", port, parsed.path or "/ws/websocket"


def _stomp_timeout():
    return float(read_config_yaml("STOMP", "stomp_timeout") or 5)


def message_timeout():
    return float(read_config_yaml("STOMP", "message_timeout") or 3)


def _read_interval():
    return float(read_config_yaml("STOMP", "read_interval") or 0.1)


def _heart_beat():
    return read_config_yaml("STOMP", "heart_beat") or "10000,10000"


def _heartbeats():
    try:
        outgoing, incoming = str(_heart_beat()).split(",", 1)
        return int(outgoing), int(incoming)
    except (TypeError, ValueError):
        raise ValueError("STOMP.heart_beat 必须是 '发送毫秒,接收毫秒'") from None


def bid_destination():
    return read_config_yaml("STOMP", "bid_destination") or "/app/bid"


_ListenerBase = stomp.ConnectionListener if stomp is not None else object


class StompMessageListener(_ListenerBase):
    """收集 MESSAGE/ERROR 帧, 支持谓词等待。"""

    def __init__(self):
        self.messages: list[dict] = []
        self.errors: list[str] = []
        self.receipts: set[str] = set()

    def clear(self):
        self.messages.clear()
        self.errors.clear()
        self.receipts.clear()

    def on_message(self, *args):
        if len(args) == 1:
            frame = args[0]
            body = getattr(frame, "body", "")
        elif len(args) >= 2:
            body = args[1]
        else:
            body = ""
        self._record(body)

    def _record(self, body):
        try:
            self.messages.append(json.loads(body))
        except (TypeError, json.JSONDecodeError):
            pass

    def on_error(self, *args):
        """捕获 ERROR 帧, 供调用方检测连接拒绝/订阅失败等。"""
        if len(args) == 1:
            frame = args[0]
            body = getattr(frame, "body", str(frame))
        elif len(args) >= 2:
            body = args[1]
        else:
            body = ""
        self.errors.append(str(body))

    def on_receipt(self, *args):
        frame = args[-1] if args else None
        headers = getattr(frame, "headers", None)
        if headers is None and isinstance(frame, dict):
            headers = frame
        receipt_id = (headers or {}).get("receipt-id") or (headers or {}).get("receipt")
        if receipt_id:
            self.receipts.add(str(receipt_id))

    def wait_for_receipt(self, receipt_id: str, timeout=None):
        """尽量等待订阅确认；后端不支持 RECEIPT 时继续执行。"""
        timeout = timeout if timeout is not None else _stomp_timeout()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if receipt_id in self.receipts:
                return True
            if self.errors:
                raise AssertionError(f"STOMP receipt {receipt_id} 失败: {self.errors}")
            time.sleep(_read_interval())
        info_log(
            f"STOMP receipt {receipt_id} 在 {timeout}s 内未确认，"
            "按服务端不支持 RECEIPT 继续执行"
        )
        return False

    def wait_for(self, predicate, timeout=None, interval=None):
        timeout = timeout if timeout is not None else message_timeout()
        interval = interval if interval is not None else _read_interval()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for message in self.messages:
                if predicate(message):
                    return message
            time.sleep(interval)
        suffix = ""
        if self.messages:
            suffix += f", received {len(self.messages)} msgs: {self.messages}"
        if self.errors:
            suffix += f", errors: {self.errors}"
        raise AssertionError(
            f"timeout: no matching WebSocket message in {timeout}s{suffix}"
        )

class StompWebSocketClient:
    """STOMP-over-WebSocket 客户端, 用于直播间事件订阅。"""

    def __init__(self, token, listener=None):
        self.token = token
        self.listener = listener or StompMessageListener()
        self.conn = None

    def connect(self):
        if stomp is None:
            raise RuntimeError("stomp.py 未安装, 无法建立 STOMP 连接 (pip install stomp.py)")
        if not hasattr(stomp, "WSConnection"):
            raise RuntimeError("stomp.py 不支持 WSConnection, 请安装兼容版本")
        host, port, path = _ws_endpoint()
        self.conn = stomp.WSConnection(
            host_and_ports=[(host, port)],
            ws_path=path,
            timeout=_stomp_timeout(),
            heartbeats=_heartbeats(),
        )
        self.conn.set_listener("auction-listener", self.listener)
        self.conn.connect(
            wait=True,
            headers={
                "Authorization": f"Bearer {self.token}",
                "accept-version": "1.2",
                "heart-beat": _heart_beat(),
            },
        )
        info_log("STOMP WebSocket 已连接")
        return self

    def subscribe_auction_topic(self, room_id, subscription_id="sub-0"):
        receipt_id = f"receipt-{uuid.uuid4().hex}"
        self.conn.subscribe(
            destination=f"/topic/auction/{room_id}",
            id=subscription_id,
            headers={"ack": "auto", "receipt": receipt_id},
        )
        return receipt_id

    def subscribe_user_queue(self, queue="/user/queue/outbid", subscription_id="sub-user"):
        receipt_id = f"receipt-{uuid.uuid4().hex}"
        self.conn.subscribe(
            destination=queue,
            id=subscription_id,
            headers={"ack": "auto", "receipt": receipt_id},
        )
        return receipt_id

    def wait_for_message(self, predicate, timeout=None):
        msg = self.listener.wait_for(predicate, timeout=timeout)
        allure.attach(json.dumps(msg, ensure_ascii=False), "WS 收到消息", allure.attachment_type.JSON)
        return msg

    def send(self, destination, body, content_type="application/json"):
        if isinstance(body, dict):
            body = json.dumps(body)
        allure.attach(str(body), f"WS 发送 {destination}", allure.attachment_type.TEXT)
        self.conn.send(body=body, destination=destination, content_type=content_type)

    def disconnect(self):
        if self.conn is None:
            return
        try:
            self.conn.disconnect()
        finally:
            self.conn = None
