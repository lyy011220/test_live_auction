"""直播间客户端: /api/rooms, /api/rooms/{id}/online, /api/admin/room/*。"""
from __future__ import annotations

from typing import Any

from clients.base import ApiClient, ApiResponse


class RoomClient:
    def __init__(self, client: ApiClient | None = None):
        self.c = client or ApiClient()

    # ---- 主播后台 ----
    def create(self, title: str, cover_image: str | None = None, video_url: str | None = None,
               notice: str | None = None, name: str = "创建直播间") -> ApiResponse:
        params: dict[str, Any] = {"title": title}
        if cover_image is not None:
            params["coverImage"] = cover_image
        if video_url is not None:
            params["videoUrl"] = video_url
        if notice is not None:
            params["notice"] = notice
        return self.c.post("/api/admin/room", name=name, params=params)

    def start(self, room_id: Any, name: str = "开播") -> ApiResponse:
        return self.c.post(f"/api/admin/room/{room_id}/start", name=name)

    def stop(self, room_id: Any, name: str = "下播") -> ApiResponse:
        return self.c.post(f"/api/admin/room/{room_id}/stop", name=name)

    def update(self, room_id: Any, title: str | None = None, cover_image: str | None = None,
               video_url: str | None = None, notice: str | None = None,
               name: str = "修改房间信息") -> ApiResponse:
        """修改直播间信息 (PUT /api/admin/room/{id}), 仅传需要更新的字段。"""
        params: dict[str, Any] = {}
        if title is not None:
            params["title"] = title
        if cover_image is not None:
            params["coverImage"] = cover_image
        if video_url is not None:
            params["videoUrl"] = video_url
        if notice is not None:
            params["notice"] = notice
        return self.c.put(f"/api/admin/room/{room_id}", name=name, params=params)

    def get_my_room(self, name: str = "查询我的直播间") -> ApiResponse:
        return self.c.get("/api/admin/room", name=name)

    def get_live_rooms(self, name: str = "查询所有直播中直播间") -> ApiResponse:
        return self.c.get("/api/admin/room/live", name=name)

    # ---- 用户公开 ----
    def public_list(self, name: str = "查询直播中房间列表") -> ApiResponse:
        return self.c.get("/api/rooms", name=name)

    def online_count(self, room_id: Any, name: str = "查询在线人数") -> ApiResponse:
        return self.c.get(f"/api/rooms/{room_id}/online", name=name)
