"""竞拍客户端: /api/admin/auction/*, /api/auction/{id}, /api/room/{id}/auctions, ranking。"""
from __future__ import annotations

from typing import Any, Mapping

from clients.base import ApiClient, ApiResponse


class AuctionClient:
    def __init__(self, client: ApiClient | None = None):
        self.c = client or ApiClient()

    # ---- 主播后台 ----
    def admin_create(self, payload: Mapping[str, Any], name: str = "发布竞拍") -> ApiResponse:
        return self.c.post("/api/admin/auction", name=name, json=dict(payload))

    def admin_update(self, auction_id: Any, payload: Mapping[str, Any],
                     name: str = "修改竞拍规则") -> ApiResponse:
        return self.c.put(f"/api/admin/auction/{auction_id}", name=name, json=dict(payload))

    def admin_start(self, auction_id: Any, name: str = "开始竞拍") -> ApiResponse:
        return self.c.post(f"/api/admin/auction/{auction_id}/start", name=name)

    def admin_cancel(self, auction_id: Any, reason: str, name: str = "取消竞拍") -> ApiResponse:
        return self.c.post(
            f"/api/admin/auction/{auction_id}/cancel", name=name, params={"reason": reason}
        )

    def admin_detail(self, auction_id: Any, name: str = "后台竞拍详情") -> ApiResponse:
        return self.c.get(f"/api/admin/auction/{auction_id}", name=name)

    def admin_list(self, page: int = 1, size: int = 10, name: str = "我发布的竞拍列表") -> ApiResponse:
        return self.c.get("/api/admin/auctions", name=name, params={"page": page, "size": size})

    # ---- 用户公开 ----
    def public_detail(self, auction_id: Any, name: str = "竞拍详情") -> ApiResponse:
        return self.c.get(f"/api/auction/{auction_id}", name=name)

    def room_auctions(self, room_id: Any, name: str = "直播间竞拍列表") -> ApiResponse:
        return self.c.get(f"/api/room/{room_id}/auctions", name=name)

    def ranking(self, auction_id: Any, name: str = "竞拍排行榜") -> ApiResponse:
        return self.c.get(f"/api/auction/{auction_id}/ranking", name=name)
