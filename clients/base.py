"""HTTP 客户端基座 (参考 api_test_frame/commons/requests_util.py 的逐请求 allure.attach)。

ApiResponse 统一承载 http_status/code/message/data/raw, 供负向/边界用例精确断言。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import allure
import requests

from commons.logger_util import info_log
from commons.yaml_util import read_config_yaml


class ApiResponseError(RuntimeError):
    """传输层或 JSON 解析失败时抛出 (非业务码错误)。"""


@dataclass
class ApiResponse:
    http_status: int
    code: Any = None
    message: Any = None
    data: Any = None
    raw: requests.Response = None

    @property
    def is_ok(self) -> bool:
        """成功: HTTP 200 且响应信封明确给出业务成功码。"""
        return self.http_status == 200 and self.code in (200, "200")

    @property
    def biz_code(self):
        """业务码 (401/403/404/409/1001/2006...); 成功时为 None。"""
        return self.code if self.code not in (None, 200, "200") else None


def _config_base_url() -> str:
    return (read_config_yaml("BASE", "base_live_auction_url") or "http://localhost:8080").rstrip("/")


def _config_timeout() -> float:
    t = read_config_yaml("API_TIMEOUT", "timeout")
    return float(t) if t is not None else 5.0


class ApiClient:
    """HTTP 传输: 共享 base_url/timeout, Bearer token, 逐请求 allure.attach。"""

    def __init__(self, token: str | None = None, base_url: str | None = None, timeout: float | None = None):
        self.session = requests.Session()
        self.token = token
        self.base_url = (base_url or _config_base_url()).rstrip("/")
        self.timeout = float(timeout) if timeout is not None else _config_timeout()
        self.user_id = None
        self.username = None
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _attach(self, name, method, url, headers, kwargs, resp):
        if name:
            allure.attach(name, "接口名称")
        allure.attach(str(method).upper(), "请求方法")
        allure.attach(url, "接口地址")
        allure.attach(
            json.dumps(headers or {}, ensure_ascii=False, indent=2, default=str),
            "请求头信息", allure.attachment_type.TEXT,
        )
        for k in ("params", "json", "data"):
            if kwargs.get(k) is not None:
                try:
                    text = json.dumps(kwargs[k], ensure_ascii=False, default=str)
                except TypeError:
                    text = str(kwargs[k])
                allure.attach(text, f"请求参数({k})", allure.attachment_type.TEXT)
        allure.attach(resp.text, "响应信息", allure.attachment_type.TEXT)
        allure.attach(str(resp.status_code), "响应状态码", allure.attachment_type.TEXT)

    def _wrap(self, resp: requests.Response) -> ApiResponse:
        try:
            body = resp.json()
        except ValueError as exc:
            content_type = resp.headers.get("Content-Type", "")
            preview = (resp.text or "")[:200]
            raise ApiResponseError(
                "response is not valid JSON: "
                f"http={resp.status_code} content_type={content_type!r} body={preview!r}"
            ) from exc
        if not isinstance(body, dict):
            raise ApiResponseError(
                f"response JSON must be an object: http={resp.status_code} type={type(body).__name__}"
            )
        return ApiResponse(
            http_status=resp.status_code,
            code=body.get("code"),
            message=body.get("message"),
            data=body.get("data"),
            raw=resp,
        )

    def _request(self, method: str, path: str, name: str | None = None, **kwargs) -> ApiResponse:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        headers = dict(kwargs.pop("headers", None) or {})
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.token}"
        info_log(f"[{method.upper()}] {url}")
        resp = self.session.request(method=method.upper(), url=url, headers=headers, **kwargs)
        self._attach(name, method, url, headers, kwargs, resp)
        return self._wrap(resp)

    def get(self, path: str, name: str | None = None, **kwargs) -> ApiResponse:
        return self._request("GET", path, name=name, **kwargs)

    def post(self, path: str, name: str | None = None, **kwargs) -> ApiResponse:
        return self._request("POST", path, name=name, **kwargs)

    def put(self, path: str, name: str | None = None, **kwargs) -> ApiResponse:
        return self._request("PUT", path, name=name, **kwargs)
