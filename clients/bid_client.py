"""出价客户端: /api/auction/{id}/bid (amount 走 query param), /api/user/bids。"""
from __future__ import annotations

from typing import Any

from clients.base import ApiClient, ApiResponse


class BidClient:
    def __init__(self, client: ApiClient | None = None):
        self.c = client or ApiClient()

    def bid(self, auction_id: Any, amount: Any, name: str = "出价") -> ApiResponse:
        # master 约定: amount 用 query param, 非 JSON body
        return self.c.post(f"/api/auction/{auction_id}/bid", name=name, params={"amount": amount})

    def my_bids(self, name: str = "我的出价记录") -> ApiResponse:
        return self.c.get("/api/user/bids", name=name)
