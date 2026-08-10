"""配置、用户池与客户端工厂 fixture。"""
import threading

import pytest

from clients.auth_client import (
    default_password,
    register_bidder,
    register_merchant,
    unique_username,
)
from clients.base import ApiClient
from commons.yaml_util import read_config_yaml
from support.user_pool import ensure_pool, extend_pool, get_bidder


@pytest.fixture(scope="session")
def base_url():
    return read_config_yaml("BASE", "base_live_auction_url") or "http://localhost:8080"


@pytest.fixture(scope="session")
def password():
    return default_password()


@pytest.fixture(scope="session")
def bidder_pool(password):
    """session 级普通用户池，pytest 与 k6 共享。"""
    return ensure_pool(password=password)


@pytest.fixture(scope="session")
def bidder_allocator(bidder_pool, password):
    """一轮测试按序分配用户；池耗尽时扩容，不静默复用身份。"""
    state = {"index": 0}
    lock = threading.Lock()

    def _next() -> ApiClient:
        with lock:
            index = state["index"]
            state["index"] += 1
            if index >= len(bidder_pool["bidders"]):
                extend_pool(bidder_pool, password)
        return get_bidder(bidder_pool, index)

    return _next


@pytest.fixture
def unique_name():
    return lambda prefix="qa": unique_username(prefix)


@pytest.fixture
def anonymous_client():
    return ApiClient()


@pytest.fixture
def make_merchant(password):
    return lambda: register_merchant(password=password)


@pytest.fixture
def merchant_client(make_merchant):
    return make_merchant()


@pytest.fixture
def bidder_client(bidder_allocator):
    return bidder_allocator()


@pytest.fixture
def make_bidder(bidder_allocator):
    return bidder_allocator


@pytest.fixture
def make_fresh_bidder(password):
    """身份或历史敏感用例使用独立用户。"""
    return lambda: register_bidder(password=password)
