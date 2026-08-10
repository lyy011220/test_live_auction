"""直播间与竞拍生命周期 fixture。"""
import pytest

from scenarios.auction_lifecycle import AuctionLifecycle


@pytest.fixture
def live_room(password, unique_name):
    return AuctionLifecycle(password=password).create_live_room(title=unique_name("room"))


@pytest.fixture
def started_auction(password):
    return AuctionLifecycle(password=password).create_started_auction()


@pytest.fixture
def pending_auction(password):
    return AuctionLifecycle(password=password).create_pending_auction()


@pytest.fixture
def started_auction_with_bidder(password, make_bidder):
    context = AuctionLifecycle(password=password).create_started_auction()
    bidder = make_bidder()
    context["bidderClient"] = bidder
    context["bidderToken"] = bidder.token
    context["bidderId"] = bidder.user_id
    return context
