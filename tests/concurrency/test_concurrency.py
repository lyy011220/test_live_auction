"""CON 域 | 并发竞价、重复请求和陈旧价格竞争。"""
from decimal import Decimal

import allure
import pytest

from clients.auction_client import AuctionClient
from clients.base import ApiClient
from clients.bid_client import BidClient
from support.assertions import assert_fields, assert_ok
from support.concurrency import (
    ConcurrentRunner,
    ThreadResult,
    assert_exactly_one_succeeded,
    failed,
)
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("并发域")

SAME_AMOUNT = 110
STALE_AMOUNTS = [109, 118, 127, 136]


def _bid_worker(client, auction_id, amount):
    def run():
        resp = BidClient(client).bid(auction_id, amount=amount)
        return ThreadResult(
            success=resp.is_ok,
            http_status=resp.http_status,
            biz_code=resp.biz_code,
            data=resp.data or {},
        )
    return run


def _same_identity_client(client: ApiClient) -> ApiClient:
    """为同一用户创建独立 HTTP session, 避免跨线程共享 requests.Session。"""
    clone = ApiClient(token=client.token)
    clone.user_id = client.user_id
    clone.username = client.username
    return clone


def _auction_history(client: ApiClient, auction_id: int) -> list[dict]:
    """读取独立用户的出价历史, 只保留当前竞拍记录。"""
    resp = BidClient(client).my_bids()
    assert_ok(resp, "查询用户出价历史")
    data = resp.data
    if isinstance(data, dict):
        rows = data.get("records") or data.get("content") or data.get("items") or []
    else:
        rows = data if isinstance(data, list) else []
    return [row for row in rows if str(row.get("itemId")) == str(auction_id)]


@EPIC
@FEATURE
@allure.story("CON-CCY-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("CON-CCY-001 两用户真实同价竞争恰一请求生效")
@pytest.mark.concurrency
@pytest.mark.api
@case("CON-CCY-001")
def test_con_ccy_001_two_users_same_price(started_auction, make_fresh_bidder):
    """核心预期: 两个独立用户同价竞争, 恰一请求生效且只写一条记录。"""
    merchant = started_auction["merchantClient"]
    aid = started_auction["auctionId"]
    b1 = make_fresh_bidder()
    b2 = make_fresh_bidder()

    results = ConcurrentRunner([
        _bid_worker(b1, aid, SAME_AMOUNT),
        _bid_worker(b2, aid, SAME_AMOUNT),
    ]).spawn()

    winner = assert_exactly_one_succeeded(results)
    assert winner.http_status == 200, "胜者应为 HTTP 200"
    losers = failed(results)
    assert len(losers) == 1, "应有且仅有一个失败者"
    assert losers[0].exception is None, f"并发请求不应因线程异常失败: {losers[0].exception}"

    detail = AuctionClient(merchant).public_detail(aid)
    assert_ok(detail, "竞拍详情")
    assert_fields(detail, {"currentPrice": SAME_AMOUNT, "bidCount": 1}, "同价竞争终态")

    rank = AuctionClient(merchant).ranking(aid)
    assert_ok(rank, "竞拍排行榜")
    ranking = rank.data if isinstance(rank.data, list) else []
    assert ranking, "同价竞争成功后排行榜不应为空"
    top_amount = ranking[0].get("amount", ranking[0].get("price"))
    assert Decimal(str(top_amount)) == Decimal(str(SAME_AMOUNT)), (
        f"排名首位金额期望 {SAME_AMOUNT}, 实际 {top_amount}"
    )

    found1 = any(Decimal(str(row.get("bidAmount", 0))) == Decimal(str(SAME_AMOUNT)) for row in _auction_history(b1, aid))
    found2 = any(Decimal(str(row.get("bidAmount", 0))) == Decimal(str(SAME_AMOUNT)) for row in _auction_history(b2, aid))
    assert found1 != found2, "仅胜者应有本次出价记录, 败者不应入账"


@EPIC
@FEATURE
@allure.story("CON-RPT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("CON-RPT-001 同一用户重复同价首次生效后不增加次数或记录")
@pytest.mark.concurrency
@pytest.mark.api
@case("CON-RPT-001")
def test_con_rpt_001_same_user_repeat(started_auction, make_fresh_bidder):
    """核心预期: 同一身份并发重复同价, 仅一次生效且只写一条历史。"""
    aid = started_auction["auctionId"]
    merchant = started_auction["merchantClient"]
    bidder = make_fresh_bidder()
    clone = _same_identity_client(bidder)

    results = ConcurrentRunner([
        _bid_worker(bidder, aid, SAME_AMOUNT),
        _bid_worker(clone, aid, SAME_AMOUNT),
    ]).spawn()

    assert_exactly_one_succeeded(results)
    assert all(result.exception is None for result in results), f"并发线程不应异常: {results}"

    detail = AuctionClient(merchant).public_detail(aid)
    assert_ok(detail, "竞拍详情")
    assert_fields(detail, {"currentPrice": SAME_AMOUNT, "bidCount": 1}, "重复请求终态")
    assert len(_auction_history(bidder, aid)) == 1, "同一用户重复请求只应写入一条出价记录"


@EPIC
@FEATURE
@allure.story("CON-CCY-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("CON-CCY-002 同一旧价下的竞争写入不回退")
@pytest.mark.concurrency
@pytest.mark.api
@case("CON-CCY-002")
def test_con_ccy_002_stale_price_race(started_auction, make_fresh_bidder):
    """核心预期: 多用户同时基于旧价出价, 终价为最高提交价且投影一致。"""
    aid = started_auction["auctionId"]
    merchant = started_auction["merchantClient"]
    bidders = [make_fresh_bidder() for _ in STALE_AMOUNTS]

    results = ConcurrentRunner([
        _bid_worker(client, aid, amount)
        for client, amount in zip(bidders, STALE_AMOUNTS)
    ]).spawn()

    assert any(result.success for result in results), f"至少一个并发出价应成功: {results}"
    assert all(result.exception is None for result in results), f"并发线程不应异常: {results}"

    expected_price = max(STALE_AMOUNTS)
    detail = AuctionClient(merchant).public_detail(aid)
    assert_ok(detail, "竞拍详情")
    assert_fields(detail, {"currentPrice": expected_price}, "陈旧价格竞争终态")
    bid_count = int((detail.data or {}).get("bidCount", 0))
    assert 1 <= bid_count <= len(STALE_AMOUNTS), f"出价次数异常: {bid_count}"

    rank = AuctionClient(merchant).ranking(aid)
    assert_ok(rank, "竞拍排行榜")
    ranking = rank.data if isinstance(rank.data, list) else []
    assert ranking, "并发成功后排行榜不应为空"
    top_amount = ranking[0].get("amount", ranking[0].get("price"))
    assert Decimal(str(top_amount)) == Decimal(str(expected_price)), (
        f"排行榜最高价期望 {expected_price}, 实际 {top_amount}"
    )

    history_count = sum(len(_auction_history(client, aid)) for client in bidders)
    assert history_count == bid_count, (
        f"详情 bidCount={bid_count}, 用户历史合计={history_count}, 投影不一致"
    )
