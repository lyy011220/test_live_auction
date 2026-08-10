"""时间解析工具: 统一处理后端返回的 ISO 时间字符串。"""
from __future__ import annotations

from datetime import datetime


def parse_iso_dt(value):
    """解析后端 plannedEndTime/actualEndTime/newEndTime 等 ISO 字符串。

    兼容 Z、显式 offset、无时区以及不同小数秒精度。
    """
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))


def seconds_between(later, earlier) -> float:
    """返回两个 ISO 时间字符串之间的秒数 (later - earlier)。"""
    later_dt = parse_iso_dt(later)
    earlier_dt = parse_iso_dt(earlier)
    if later_dt.tzinfo is not None and earlier_dt.tzinfo is None:
        earlier_dt = earlier_dt.replace(tzinfo=later_dt.tzinfo)
    elif later_dt.tzinfo is None and earlier_dt.tzinfo is not None:
        later_dt = later_dt.replace(tzinfo=earlier_dt.tzinfo)
    return (later_dt - earlier_dt).total_seconds()


def seconds_until(end_iso) -> float:
    """返回 end_iso 到当前时刻的剩余秒数 (end - now)。

    带时区时间使用相同时区的当前时间；无时区时间按本机本地时间处理。
    """
    end = parse_iso_dt(end_iso)
    now = datetime.now(end.tzinfo) if end.tzinfo is not None else datetime.now()
    return (end - now).total_seconds()
