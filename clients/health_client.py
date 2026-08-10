"""健康检查客户端: GET /api/health。"""
from __future__ import annotations

from clients.base import ApiClient, ApiResponse


class HealthClient:
    def __init__(self, client: ApiClient | None = None):
        self.c = client or ApiClient()

    def health(self) -> ApiResponse:
        return self.c.get("/api/health", name="健康检查")
