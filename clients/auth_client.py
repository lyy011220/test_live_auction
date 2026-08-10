"""认证客户端 + 账号辅助: /api/auth/register, /api/auth/login。"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from clients.base import ApiClient, ApiResponse
from commons.yaml_util import read_config_yaml


def unique_username(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def default_password() -> str:
    return read_config_yaml("ACCOUNT", "default_password") or "123456"


class AuthClient:
    def __init__(self, client: ApiClient | None = None):
        self.c = client or ApiClient()

    def register(self, username: str, password: str, role: int, nickname: str | None = None,
                 name: str = "注册") -> ApiResponse:
        return self.c.post(
            "/api/auth/register",
            name=name,
            json={
                "username": username,
                "password": password,
                "nickname": nickname or username,
                "role": role,
            },
        )

    def login(self, username: str, password: str, name: str = "登录") -> ApiResponse:
        return self.c.post(
            "/api/auth/login", name=name, json={"username": username, "password": password}
        )


def get_token(client: ApiClient) -> str:
    return client.token or ""


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """解码 JWT payload (不验签), 返回 claims dict; 供用例断言 sub/role/exp 等。"""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("token is not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))


def register_account(role: int = 2, username: str | None = None,
                     password: str | None = None) -> dict[str, Any]:
    """注册并登录, 返回 {username, userId, token, role}。"""
    username = username or unique_username("m" if role == 1 else "u")
    password = password or default_password()
    auth = AuthClient(ApiClient())
    reg = auth.register(username, password, role)
    if not reg.is_ok:
        raise RuntimeError(f"register failed: {reg.message} ({reg.code})")
    login = auth.login(username, password)
    if not login.is_ok:
        raise RuntimeError(f"login failed: {login.message} ({login.code})")
    token = (login.data or {}).get("token")
    if not token:
        raise RuntimeError(f"login response has no token: {login.data}")
    user_id = (login.data or {}).get("userId") or (reg.data or {}).get("userId")
    return {"username": username, "userId": user_id, "token": token, "role": role}


def register_client(role: int = 2, username: str | None = None,
                    password: str | None = None) -> ApiClient:
    """注册并登录, 返回带 token/user_id 的 ApiClient。"""
    account = register_account(role=role, username=username, password=password)
    client = ApiClient(token=account["token"])
    client.user_id = account["userId"]
    client.username = account["username"]
    return client


def register_merchant(username: str | None = None, password: str | None = None) -> ApiClient:
    return register_client(role=1, username=username, password=password)


def register_bidder(username: str | None = None, password: str | None = None) -> ApiClient:
    return register_client(role=2, username=username, password=password)
