"""BID 域 | 正常出价、金额规则与参数校验。"""
from decimal import Decimal

import allure
import pytest

from clients.auction_client import AuctionClient
from clients.bid_client import BidClient
from models.enums import AuctionStatus
from models.payloads import DEFAULT_AUCTION_PAYLOAD as P
from support.assertions import assert_failed, assert_fields, assert_ok, require_ok
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("出价域")

START = P["startPrice"]          # 100
INC = P["incrementAmount"]       # 9
MAXP = P["maxPrice"]             # 1000
MIN_VALID = START + INC          # 109
MISSING_AUCTION_ID = 99999999

@EPIC
@FEATURE
@allure.story("BID-NOR-001")
@allure.severity(allure.severity_level.BLOCKER)
@allure.title("BID-NOR-001 正常有效出价原子更新价格/出价人/次数与记录")
@pytest.mark.bid
@pytest.mark.api
@case("BID-NOR-001")
def test_bid_nor_001_valid_bid(started_auction_with_bidder):
    """核心预期: 有效出价后 currentPrice/出价人/bidCount/记录 原子更新一次。"""
    ctx = started_auction_with_bidder
    bidder = ctx["bidderClient"]
    merchant = ctx["merchantClient"]
    aid = ctx["auctionId"]

    resp = BidClient(bidder).bid(aid, amount=MIN_VALID)
    assert_ok(resp, "有效出价")
    assert_fields(resp, {"currentPrice": MIN_VALID, "bidCount": 1}, "出价响应")
    assert str((resp.data or {}).get("currentBidderId")) == str(ctx["bidderId"]), (
        f"期望出价人 {ctx['bidderId']}, 实际 {(resp.data or {}).get('currentBidderId')}"
    )

    # public_detail 一致性
    detail = AuctionClient(merchant).public_detail(aid)
    assert_ok(detail, "竞拍详情")
    assert_fields(detail, {"currentPrice": MIN_VALID, "bidCount": 1}, "竞拍详情")

@EPIC
@FEATURE
@allure.story("BID-NEG-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("BID-NEG-001 非法出价金额被拒绝且竞拍状态不变")
@pytest.mark.bid
@pytest.mark.api
@case("BID-NEG-001")
@pytest.mark.parametrize(
    "amount",
    [0, -1, START, MIN_VALID, MIN_VALID + 1, MAXP + 1],
    ids=["零", "负数", "低于当前价", "等于当前价", "不足最小加价", "超过封顶价"],
)
def test_bid_neg_001_invalid_amount(started_auction_with_bidder, make_bidder, amount):
    """核心预期: 非法金额出价被拒且价格/出价人/次数不变。

    覆盖: 零/负数/低于当前价/等于当前价/不足最小加价/超过封顶价
    (原 BND-006, VAL-001 已并入)。
    """
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    assert_ok(BidClient(ctx["bidderClient"]).bid(aid, amount=MIN_VALID), "建立当前价")

    resp = BidClient(make_bidder()).bid(aid, amount=amount)
    assert_failed(resp, f"非法金额出价 {amount}")

    # 验证价格/次数不变
    detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
    assert_fields(detail, {"currentPrice": MIN_VALID, "bidCount": 1}, "非法出价后终态")

@EPIC
@FEATURE
@allure.story("BID-BND-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-BND-002 满足加价规则的有效出价成功")
@pytest.mark.bid
@pytest.mark.api
@case("BID-BND-002")
@pytest.mark.parametrize(
    "request_amount, expected_amount",
    [
        (str(MIN_VALID + INC), Decimal(str(MIN_VALID + INC))),
        (f"{MIN_VALID + INC}.01", Decimal(f"{MIN_VALID + INC}.01")),
        (f"{MAXP - 1}.99", Decimal(f"{MAXP - 1}.99")),
    ],
    ids=["等于最小有效价", "高于最小有效价0.01", "低于封顶价0.01"],
)
def test_bid_bnd_002_valid_bid(started_auction_with_bidder, make_bidder, request_amount, expected_amount):
    """核心预期: 满足加价规则的有效出价成功且竞拍继续 (status=LIVE)。

    覆盖: 等于最小有效价 / 高于最小有效价 / 低于封顶价 (原 BND-003/004 已并入)。
    """
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    assert_ok(BidClient(ctx["bidderClient"]).bid(aid, amount=MIN_VALID), "首次出价")

    resp = BidClient(make_bidder()).bid(aid, amount=request_amount)
    assert_ok(resp, f"出价 {request_amount}")
    assert Decimal(str((resp.data or {}).get("currentPrice"))) == expected_amount, (
        f"currentPrice 期望 {expected_amount}, 实际 {(resp.data or {}).get('currentPrice')}"
    )
    assert (resp.data or {}).get("bidCount") == 2, "第二次有效出价后 bidCount 应为 2"

    # 未到封顶价, 竞拍继续
    detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
    assert_fields(detail, {"status": AuctionStatus.LIVE}, "未到封顶价终态")

@EPIC
@FEATURE
@allure.story("BID-BND-005")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("BID-BND-005 等于封顶价只成交一次并一致更新赢家/记录")
@pytest.mark.bid
@pytest.mark.api
@case("BID-BND-005")
def test_bid_bnd_005_equals_max_price(started_auction_with_bidder):
    """核心预期: 出价==maxPrice 触发成交, 状态 SOLD, currentPrice==maxPrice, 仅成交一次。"""
    ctx = started_auction_with_bidder
    bidder = ctx["bidderClient"]
    merchant = ctx["merchantClient"]
    aid = ctx["auctionId"]

    resp = BidClient(bidder).bid(aid, amount=MAXP)
    assert_ok(resp, "封顶出价")

    detail = AuctionClient(merchant).public_detail(aid)
    assert_ok(detail, "竞拍详情")
    assert_fields(detail, {"status": AuctionStatus.SOLD, "currentPrice": MAXP}, "封顶成交")

    # 再次出价应被拒绝 (只成交一次)
    again = BidClient(bidder).bid(aid, amount=MAXP + INC)
    assert_failed(again, "成交后再次出价")

@EPIC
@FEATURE
@allure.story("BID-VAL-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-VAL-002 金额精度超过两位参数校验失败")
@pytest.mark.bid
@pytest.mark.api
@case("BID-VAL-002")
def test_bid_val_002_precision_exceed(started_auction_with_bidder, make_bidder):
    """核心预期: 金额精度超过两位小数被拒绝且无写入副作用。"""
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    assert_ok(BidClient(ctx["bidderClient"]).bid(aid, amount=MIN_VALID), "首次出价")

    resp = BidClient(make_bidder()).bid(aid, amount=f"{MIN_VALID + INC}.001")
    assert_failed(resp, "精度超过两位的出价")

    # 验证终态不变
    detail = AuctionClient(ctx["merchantClient"]).public_detail(aid)
    assert_fields(detail, {"currentPrice": MIN_VALID, "bidCount": 1}, "精度超限后终态")

@EPIC
@FEATURE
@allure.story("BID-VAL-003")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("BID-VAL-003 非法请求参数或路径被拒绝")
@pytest.mark.bid
@pytest.mark.api
@case("BID-VAL-003")
@pytest.mark.parametrize(
    "desc",
    ["amount缺失", "amount非数字", "auctionId非数字", "auctionId溢出"],
)
def test_bid_val_003_invalid_request(started_auction_with_bidder, desc):
    """核心预期: 非法请求参数/路径被拒且不产生写入。

    覆盖: amount缺失/非数字, auctionId非数字/溢出 (原 VAL-004/005 已并入)。
    """
    ctx = started_auction_with_bidder
    aid = ctx["auctionId"]
    before = require_ok(AuctionClient(ctx["merchantClient"]).public_detail(aid), "非法请求前详情")
    before_data = before.data or {}
    if desc == "amount缺失":
        resp = ctx["bidderClient"].post(f"/api/auction/{aid}/bid")
    elif desc == "amount非数字":
        resp = ctx["bidderClient"].post(f"/api/auction/{aid}/bid", params={"amount": "abc"})
    elif desc == "auctionId非数字":
        resp = ctx["bidderClient"].post("/api/auction/abc/bid", params={"amount": MIN_VALID})
    else:  # auctionId溢出
        resp = ctx["bidderClient"].post(
            "/api/auction/99999999999999999/bid", params={"amount": MIN_VALID}
        )
    assert_failed(resp, f"非法请求 ({desc})")
    after = require_ok(AuctionClient(ctx["merchantClient"]).public_detail(aid), "非法请求后详情")
    assert_fields(
        after,
        {
            "currentPrice": before_data.get("currentPrice"),
            "bidCount": before_data.get("bidCount"),
        },
        f"非法请求 ({desc}) 后终态",
    )
