"""竞拍时间窗口轮询。"""
from clients.auction_client import AuctionClient
from clients.base import ApiClient
from support.assertions import require_ok
from support.time_util import seconds_until
from support.wait_util import wait_until

# 轮询竞拍详情，直到剩余秒数 ≤ `target_remaining`
def wait_until_remaining(
    auction_id,
    target_remaining,
    client: ApiClient | None = None,
    timeout=120.0,
    interval=1.0,
):
    """等待竞拍进入指定剩余秒数；详情失败时立即保留接口诊断。"""
    api_client = client or ApiClient()

    def remaining():
        response = require_ok(
            AuctionClient(api_client).public_detail(auction_id),
            "等待竞拍时间窗口时查询详情",
        )
        planned_end = (response.data or {}).get("plannedEndTime")
        if not planned_end:
            raise AssertionError("竞拍详情缺少 plannedEndTime")
        return seconds_until(planned_end)

    return wait_until(
        remaining,
        predicate=lambda value: value <= target_remaining,
        timeout=timeout,
        interval=interval,
    )
