"""WS 域 | 在线人数同步。"""
import allure
import pytest
import stomp
from support.traceability import case
from ws.events import online_event
from ws.stomp_client import StompWebSocketClient

pytestmark = pytest.mark.skipif(stomp is None, reason="stomp.py 未安装")

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("WebSocket域")

@EPIC
@FEATURE
@allure.story("WS-CNS-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("WS-CNS-001 连接生命周期同步在线人数")
@pytest.mark.ws
@pytest.mark.api
@case("WS-CNS-001")
def test_ws_cns_001_online_sync(live_room, make_bidder):
    """核心预期: WS 连接/断开后在线人数精确随之变化 (通过 ONLINE 广播事件验证)。

    REST online_count 接口不反映 WS 连接, 改用 ONLINE 事件验证:
    观察者订阅 topic, joiner 连接/断开各触发一次 ONLINE 事件, count 精确 ±1。
    """
    room_id = live_room["roomId"]
    observer = make_bidder()
    joiner = make_bidder()

    def online_with_count(expected):
        return lambda m: online_event(room_id=room_id)(m) and m.get("count") == expected

    ws_obs = StompWebSocketClient(token=observer.token)
    try:
        ws_obs.connect()
        ws_obs.subscribe_auction_topic(room_id)
        # 等待观察者自身的 ONLINE 事件, 记录基准在线人数
        msg = ws_obs.wait_for_message(online_event(room_id=room_id), timeout=5)
        count_before = msg.get("count", 0)

        # joiner 连接并订阅, 观察者应收到 ONLINE 事件 (count + 1)
        ws_join = StompWebSocketClient(token=joiner.token)
        try:
            ws_join.connect()
            ws_join.subscribe_auction_topic(room_id)
            msg = ws_obs.wait_for_message(online_with_count(count_before + 1), timeout=5)
            count_after = msg.get("count", 0)
            assert count_after == count_before + 1, (
                f"连接后在线人数应增加 1: {count_before} -> {count_after}"
            )
        finally:
            ws_join.disconnect()

        # joiner 断开后, 观察者应收到 ONLINE 事件 (count 回落)
        msg = ws_obs.wait_for_message(online_with_count(count_before), timeout=5)
        count_final = msg.get("count", 0)
        assert count_final == count_before, (
            f"断开后在线人数应回落: {count_before} -> {count_final}"
        )
    finally:
        ws_obs.disconnect()
