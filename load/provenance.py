"""k6 结果来源校验：运行元数据、后端身份和有效期。"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import requests

from commons.logger_util import info_log
from commons.yaml_util import read_config_yaml

REPORTS_K6 = Path(__file__).resolve().parents[1] / "reports" / "k6"


class SummaryValidationError(RuntimeError):
    """k6 摘要不属于当前环境或已经过期。"""


def metadata_path_for(scenario_name: str) -> Path:
    return REPORTS_K6 / f"{scenario_name}.meta.json"

# LRU 缓存 （Least Recently Used）——同一进程内，
# 同样的 base_url 第二次调用 直接返回缓存 ，不重复发 HTTP 请求。
@lru_cache(maxsize=8)
def backend_identity(base_url: str) -> dict:
    """用后端 OpenAPI 内容和声明版本构造可重复比较的环境指纹。"""
    url = f"{base_url.rstrip('/')}/v3/api-docs"
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    document = response.json()
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "openapi_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "api_version": (document.get("info") or {}).get("version"),
        "configured_version": os.getenv("BACKEND_VERSION") or None,
    }


def write_run_metadata(scenario_name: str, metadata: dict) -> Path:
    REPORTS_K6.mkdir(parents=True, exist_ok=True)
    path = metadata_path_for(scenario_name)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    info_log(f"k6 运行元数据已写入: {path}")
    return path


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def validate_run_metadata(scenario_name: str, metadata: dict) -> None:
    """拒绝旧环境、旧接口契约或超出允许时间窗口的历史结果。"""
    if metadata.get("schema_version") != 1:
        raise SummaryValidationError(f"{scenario_name} k6 元数据版本无效，请重新运行该场景")
    if metadata.get("scenario") != scenario_name:
        raise SummaryValidationError(f"{scenario_name} k6 元数据场景不匹配")
    if metadata.get("k6_exit_code") != 0:
        raise SummaryValidationError(
            f"{scenario_name} 上次 k6 退出码为 {metadata.get('k6_exit_code')}，结果不可作为通过依据"
        )

    completed_text = metadata.get("completed_at")
    if not completed_text:
        raise SummaryValidationError(f"{scenario_name} k6 元数据缺少 completed_at")
    try:
        completed = _parse_utc(completed_text)
    except (TypeError, ValueError) as exc:
        raise SummaryValidationError(f"{scenario_name} k6 completed_at 格式无效") from exc
    max_age_hours = float(os.getenv("K6_SUMMARY_MAX_AGE_HOURS", "24"))
    now = datetime.now(timezone.utc)
    if completed > now + timedelta(minutes=5):
        raise SummaryValidationError(f"{scenario_name} k6 完成时间位于未来，请检查系统时间")
    if now - completed > timedelta(hours=max_age_hours):
        raise SummaryValidationError(
            f"{scenario_name} k6 结果已超过 {max_age_hours:g} 小时，请针对当前后端重新运行"
        )

    current_base = (
        read_config_yaml("BASE", "base_live_auction_url") or "http://localhost:8080"
    ).rstrip("/")
    if metadata.get("base_url") != current_base:
        raise SummaryValidationError(
            f"{scenario_name} k6 目标为 {metadata.get('base_url')}，当前目标为 {current_base}"
        )

    recorded_identity = metadata.get("backend") or {}
    try:
        current_identity = backend_identity(current_base)
    except Exception as exc:  # noqa: BLE001
        raise SummaryValidationError(f"无法核对当前后端 OpenAPI 指纹: {exc}") from exc
    if recorded_identity.get("openapi_sha256") != current_identity.get("openapi_sha256"):
        raise SummaryValidationError(f"{scenario_name} k6 结果对应的后端 OpenAPI 已变化，请重新运行")
    if recorded_identity.get("configured_version") != current_identity.get("configured_version"):
        raise SummaryValidationError(f"{scenario_name} k6 结果对应的 BACKEND_VERSION 已变化，请重新运行")
