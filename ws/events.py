"""WebSocket 事件谓词工厂: 兼容 type/event 两种消息形状。"""
from __future__ import annotations

from typing import Any, Callable

from models.enums import EventType


def _matches_event(msg: dict, event: str) -> bool:
    return msg.get("event") == event or msg.get("type") == event


def _item_matches(msg: dict, item_id: Any) -> bool:
    return item_id is None or str(msg.get("itemId")) == str(item_id)


def bid_event(item_id: Any = None, price: Any = None) -> Callable[[dict], bool]:
    """BID 事件: type/event == BID, 可校验 itemId 与 price。"""

    def predicate(msg: dict) -> bool:
        if not _matches_event(msg, EventType.BID):
            return False
        if not _item_matches(msg, item_id):
            return False
        if price is not None:
            try:
                actual = float(msg.get("price", msg.get("amount", 0)))
                if actual != float(price):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    return predicate


def sold_event(item_id: Any = None) -> Callable[[dict], bool]:
    def predicate(msg: dict) -> bool:
        return _matches_event(msg, EventType.SOLD) and _item_matches(msg, item_id)
    return predicate


def started_event(item_id: Any = None) -> Callable[[dict], bool]:
    def predicate(msg: dict) -> bool:
        return _matches_event(msg, EventType.STARTED) and _item_matches(msg, item_id)
    return predicate


def cancelled_event(item_id: Any = None) -> Callable[[dict], bool]:
    def predicate(msg: dict) -> bool:
        return _matches_event(msg, EventType.CANCELLED) and _item_matches(msg, item_id)
    return predicate


def delayed_event(item_id: Any = None) -> Callable[[dict], bool]:
    """DELAYED 事件: 校验 newEndTime 非空。"""

    def predicate(msg: dict) -> bool:
        if not (_matches_event(msg, EventType.DELAYED) and _item_matches(msg, item_id)):
            return False
        return msg.get("newEndTime") is not None

    return predicate


def ended_event(item_id: Any = None) -> Callable[[dict], bool]:
    def predicate(msg: dict) -> bool:
        return _matches_event(msg, EventType.ENDED) and _item_matches(msg, item_id)
    return predicate


def outbid_event(item_id: Any = None) -> Callable[[dict], bool]:
    """OUTBID 事件 (点对点 /user/queue/outbid): 原最高出价人被超越。"""
    def predicate(msg: dict) -> bool:
        if not _matches_event(msg, EventType.OUTBID):
            return False
        return _item_matches(msg, item_id)
    return predicate


def online_event(room_id: Any = None) -> Callable[[dict], bool]:
    def predicate(msg: dict) -> bool:
        if not _matches_event(msg, EventType.ONLINE):
            return False
        return room_id is None or str(msg.get("roomId")) == str(room_id)
    return predicate
