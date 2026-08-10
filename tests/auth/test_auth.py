"""AUTH 域 | 注册、登录与鉴权。

覆盖 8 个 Case ID，参数化后共 12 个执行项。
"""
import allure
import pytest

from clients.auth_client import AuthClient, decode_jwt_payload
from clients.room_client import RoomClient
from models.enums import Role
from support.assertions import assert_failed, assert_ok
from support.traceability import case

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("认证域")


@EPIC
@FEATURE
@allure.story("AUTH-NOR-001")
@allure.severity(allure.severity_level.BLOCKER)
@allure.title("AUTH-NOR-001 普通用户注册成功并返回 token/userId/role")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-NOR-001")
def test_auth_nor_001_register_user(anonymous_client, password, unique_name):
    """核心预期: role=2 注册返回成功, data 含 token/userId/role=2。"""
    username = unique_name("u")
    resp = AuthClient(anonymous_client).register(
        username=username, password=password, role=Role.USER
    )
    assert_ok(resp, "注册普通用户")
    data = resp.data or {}
    assert data.get("token"), "注册应返回 token"
    assert data.get("userId"), "注册应返回 userId"
    assert data.get("role") == Role.USER, f"期望 role={Role.USER}, 实际 {data.get('role')}"


@EPIC
@FEATURE
@allure.story("AUTH-NOR-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUTH-NOR-002 主播注册成功并返回主播身份凭证")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-NOR-002")
def test_auth_nor_002_register_merchant(anonymous_client, password, unique_name):
    """核心预期: role=1 注册返回主播身份与可用会话凭证。"""
    username = unique_name("a")
    resp = AuthClient(anonymous_client).register(
        username=username, password=password, role=Role.MERCHANT
    )
    assert_ok(resp, "注册主播用户")
    data = resp.data or {}
    assert data.get("token"), "注册应返回 token"
    assert data.get("userId"), "注册应返回 userId"
    assert data.get("role") == Role.MERCHANT, f"期望 role={Role.MERCHANT}, 实际 {data.get('role')}"


@EPIC
@FEATURE
@allure.story("AUTH-NOR-003")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUTH-NOR-003 普通用户正确登录签发匹配 Token")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-NOR-003")
def test_auth_nor_003_user_login(anonymous_client, password, unique_name):
    """核心预期: 普通用户正确登录签发匹配普通用户的有效 Token (JWT sub=userId, role=2)。

    每次创建独立普通用户, 避免账号历史状态影响登录契约。
    """
    username = unique_name("login")
    auth = AuthClient(anonymous_client)
    assert_ok(
        auth.register(username=username, password=password, role=Role.USER),
        "准备独立普通用户",
    )
    resp_login = auth.login(username=username, password=password)
    assert_ok(resp_login, "登录普通用户")
    data = resp_login.data or {}
    token = data.get("token")
    user_id = data.get("userId")
    assert token, "登录应返回 token"
    assert user_id, "登录应返回 userId"
    # JWT 载荷: sub 为字符串形式的 userId, role 为整型 2
    payload = decode_jwt_payload(token)
    assert payload.get("sub") == str(user_id), (
        f"JWT sub 期望 {user_id}, 实际 {payload.get('sub')}"
    )
    assert payload.get("role") == Role.USER, (
        f"JWT role 期望 {Role.USER}, 实际 {payload.get('role')}"
    )


@EPIC
@FEATURE
@allure.story("AUTH-NOR-004")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUTH-NOR-004 主播正确登录签发匹配 Token")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-NOR-004")
def test_auth_nor_004_merchant_login(anonymous_client, password, unique_name):
    """核心预期: 主播正确登录签发匹配主播的有效 Token。"""
    username = unique_name("a")
    auth = AuthClient(anonymous_client)
    resp_register = auth.register(username=username, password=password, role=Role.MERCHANT)
    assert_ok(resp_register, "注册主播用户")
    resp_login = auth.login(username=username, password=password)
    assert_ok(resp_login, "登录主播用户")
    data = resp_login.data or {}
    token = data.get("token")
    user_id = data.get("userId")
    assert token, "登录应返回 token"
    assert user_id, "登录应返回 userId"
    # JWT 载荷: sub 为字符串形式的 userId, role 为整型 1
    payload = decode_jwt_payload(token)
    assert payload.get("sub") == str(user_id), (
        f"JWT sub 期望 {user_id}, 实际 {payload.get('sub')}"
    )
    assert payload.get("role") == Role.MERCHANT, (
        f"JWT role 期望 {Role.MERCHANT}, 实际 {payload.get('role')}"
    )


@EPIC
@FEATURE
@allure.story("AUTH-NEG-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUTH-NEG-001 账号不存在或密码错误被拒绝且不签发 Token")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-NEG-001")
@pytest.mark.parametrize(
    "exists",
    [False, True],
    ids=["账号不存在", "账号存在密码错误"],
)
def test_auth_neg_001_wrong_password(anonymous_client, password, unique_name, exists):
    """核心预期: 不存在账号或错误密码登录被拒绝, 响应不签发 token。

    - 账号不存在: 用户名未注册, 登录必须失败且不得签发 token
    - 账号存在密码错误: 独立注册账号后用错误密码登录, 必须失败且不得签发 token
    """
    auth = AuthClient(anonymous_client)
    if exists:
        username = unique_name("wrongpwd")
        assert_ok(
            auth.register(username=username, password=password, role=Role.USER),
            "准备独立普通用户",
        )
    else:
        # 账号不存在: 用未注册的用户名
        username = unique_name("nobody")
    resp = auth.login(username=username, password="definitely_wrong")
    assert_failed(resp, "错误凭证登录")
    assert not (resp.data or {}).get("token"), "失败响应不得签发 token"


@EPIC
@FEATURE
@allure.story("AUTH-VAL-001")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUTH-VAL-001 注册或登录必填字段缺失或空值")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-VAL-001")
@pytest.mark.parametrize(
    "endpoint, missing_field",
    [
        ("register", "username"),
        ("register", "password"),
        ("login", "username"),
        ("login", "password"),
    ],
    ids=["注册缺username", "注册缺password", "登录缺username", "登录缺password"],
)
def test_auth_val_001_missing_fields(anonymous_client, password, unique_name, endpoint, missing_field):
    """核心预期: 必填字段缺失应被拒绝且不签发 token。

    - 注册缺 username/password: 不创建账号
    - 登录缺 username/password: 不签发 token
    """
    auth = AuthClient(anonymous_client)
    username = unique_name("u")

    if endpoint == "register":
        payload = {"username": username, "password": password, "role": Role.USER}
        payload.pop(missing_field, None)
        resp = auth.c.post("/api/auth/register", json=payload)
        assert_failed(resp, f"注册缺 {missing_field}")
        # 同一用户名随后应能正常注册，证明失败请求没有抢占账号。
        valid_register = auth.register(username=username, password=password, role=Role.USER)
        assert_ok(valid_register, f"缺 {missing_field} 注册失败后重新注册")
    else:  # login
        assert_ok(
            auth.register(username=username, password=password, role=Role.USER),
            "准备登录字段校验账号",
        )
        payload = {"username": username, "password": password}
        payload.pop(missing_field, None)
        resp = auth.c.post("/api/auth/login", json=payload)
        assert_failed(resp, f"登录缺 {missing_field}")
        assert not (resp.data or {}).get("token"), "失败响应不得签发 token"


@EPIC
@FEATURE
@allure.story("AUTH-AUT-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("AUTH-AUT-001 主播管理缺失 Token 创建直播间")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-AUT-001")
def test_auth_aut_001_admin_without_token(anonymous_client, unique_name):
    """核心预期: 使用合法请求形状但不携带凭证时，创建直播间被拒绝。"""
    resp = RoomClient(anonymous_client).create(title=unique_name("room"))
    assert_failed(resp, "无 token 访问主播管理接口")


@EPIC
@FEATURE
@allure.story("AUTH-VAL-002")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("AUTH-VAL-002 重复用户名注册被拒绝且不覆盖原账号")
@pytest.mark.auth
@pytest.mark.api
@case("AUTH-VAL-002")
def test_auth_val_002_duplicate_username(anonymous_client, password, unique_name):
    """核心预期: 重复用户名注册按唯一性给出提示, 不得覆盖原账号。

    每次创建独立账号, 再验证重复注册被拒绝且原账号不被覆盖。
    """
    auth = AuthClient(anonymous_client)
    username = unique_name("duplicate")
    assert_ok(
        auth.register(username=username, password=password, role=Role.USER),
        "准备独立普通用户",
    )

    # 1. 重复注册应被拒绝
    resp = auth.register(username=username, password="different_pwd", role=Role.USER)
    assert_failed(resp, "重复用户名注册")
    assert "用户名" in (resp.message or ""), f"期望提示用户名冲突, 实际 {resp.message}"

    # 2. 原账号未被覆盖: 用原密码可正常登录
    login_resp = auth.login(username=username, password=password)
    assert_ok(login_resp, "原账号登录")
