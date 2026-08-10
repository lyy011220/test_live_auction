"""HEALTH 域 | 健康检查。

覆盖: HEALTH-NOR-001。
"""
import allure
import pytest

from clients.health_client import HealthClient
from support.assertions import assert_ok
from support.traceability import case


@allure.epic("直播竞拍平台")
@allure.feature("健康检查域")
@allure.story("HEALTH-NOR-001")
@allure.severity(allure.severity_level.BLOCKER)
@allure.title("HEALTH-NOR-001 后端健康检查返回可用状态")
@pytest.mark.health
@pytest.mark.api
@case("HEALTH-NOR-001")
def test_health_nor_001_backend_health(anonymous_client):
    """核心预期: GET /api/health 返回 HTTP 200, 服务可用。"""
    resp = HealthClient(anonymous_client).health()
    assert_ok(resp, "健康检查")
    assert resp.http_status == 200, f"期望 200, 实际 {resp.http_status}"
