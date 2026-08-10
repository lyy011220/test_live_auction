"""项目配置读取：环境变量 > 项目根目录 .env > config/config.yaml。"""
from functools import lru_cache
import os
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

_ENV_OVERRIDES = {
    ("BASE", "base_live_auction_url"): "AUCTION_HTTP_BASE_URL",
    ("BASE", "ws_url"): "AUCTION_WS_URL",
    ("API_TIMEOUT", "timeout"): "AUCTION_API_TIMEOUT",
    ("ACCOUNT", "default_password"): "AUCTION_DEFAULT_PASSWORD",
    ("K6", "bin"): "K6_BIN",
}
_TOP_LEVEL_ENV = {"REPORT_TYPE": "AUCTION_REPORT_TYPE"}


def _load_project_env() -> None:
    """加载简单 KEY=VALUE 形式的 .env，不覆盖进程已有环境变量。"""
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


_load_project_env()


def get_object_path():
    """返回项目根目录 (commons 的上一级)。"""
    return str(PROJECT_ROOT)


def _read_yaml(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.load(stream=f, Loader=yaml.FullLoader)


@lru_cache(maxsize=1)
def _config() -> dict:
    return _read_yaml(CONFIG_PATH) or {}


def read_config(node):
    """读取 config/config.yaml 的顶层节点。"""
    env_name = _TOP_LEVEL_ENV.get(node)
    if env_name and os.getenv(env_name) is not None:
        return os.environ[env_name]
    return _config().get(node)


def read_config_yaml(one_node, two_node):
    """读取 config/config.yaml 的二级节点: config[one_node][two_node]。"""
    env_name = _ENV_OVERRIDES.get((one_node, two_node))
    if env_name and os.getenv(env_name) is not None:
        return os.environ[env_name]
    return (_config().get(one_node) or {}).get(two_node)
