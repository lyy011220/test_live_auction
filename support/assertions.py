"""统一断言: 针对 ApiResponse 的 ok/biz/http 断言, 失败信息含上下文。"""
from __future__ import annotations

from clients.base import ApiResponse, ApiResponseError


def require_ok(resp: ApiResponse, action: str = "operation") -> ApiResponse:
    """成功则返回 resp, 否则抛 ApiResponseError (用于 fixture 造数)。"""
    if not resp.is_ok:
        raise ApiResponseError(
            f"{action} failed: http={resp.http_status} code={resp.code} message={resp.message}"
        )
    return resp


def assert_ok(resp: ApiResponse, action: str = "operation") -> None:
    assert resp.is_ok, (
        f"{action} 期望成功, 实际 http={resp.http_status} code={resp.code} message={resp.message}"
    )


def assert_failed(resp: ApiResponse, action: str = "operation") -> None:
    """断言请求未成功, 不绑定不稳定的 HTTP/业务错误码。

    业务副作用必须由调用用例继续断言；状态码只保留在失败诊断中。
    """
    assert not resp.is_ok, (
        f"{action} 期望被拒绝, 实际成功 "
        f"(http={resp.http_status}, code={resp.code}, message={resp.message})"
    )


def assert_fields(resp: ApiResponse, expected: dict, msg: str = "") -> None:
    """验证响应 data 中指定字段等于期望值。

    用法: assert_fields(detail, {"status": 5, "bidCount": 0}, "取消后终态")
    """
    d = resp.data or {}
    for k, v in expected.items():
        actual = d.get(k)
        assert actual == v, (
            f"{msg} {k} 期望 {v}, 实际 {actual}" if msg else f"{k} 期望 {v}, 实际 {actual}"
        )
