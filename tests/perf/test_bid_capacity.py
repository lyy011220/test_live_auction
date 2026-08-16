import json
from pathlib import Path

import allure
import pytest

from support.traceability import case


ROOT = Path(__file__).resolve().parents[2]
REPORTS_ROOT = ROOT / "reports" / "k6" / "bid_capacity"


def _latest_run() -> tuple[Path, dict]:
    if not REPORTS_ROOT.exists():
        pytest.skip(
            "未运行热点出价容量测试，请先执行: "
            "python -m load.performance.runner --scenario bid_capacity"
        )
    run_dirs = sorted(
        path
        for path in REPORTS_ROOT.iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    )
    if not run_dirs:
        pytest.skip(
            "未运行热点出价容量测试，请先执行: "
            "python -m load.performance.runner --scenario bid_capacity"
        )
    run_dir = run_dirs[-1]
    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    return run_dir, manifest


@allure.epic("直播竞拍平台")
@allure.feature("性能域")
@allure.story("PERF-CAPACITY-002")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("PERF-CAPACITY-002 单竞拍热点出价固定 RPS 分档容量")
@pytest.mark.perf
@pytest.mark.load
@case("PERF-CAPACITY-002")
def test_perf_capacity_002_bid_hotspot_fixed_rates():
    run_dir, manifest = _latest_run()
    allure.attach(
        (run_dir / "summary.md").read_text(encoding="utf-8"),
        "热点出价容量对比",
        allure.attachment_type.TEXT,
    )
    allure.attach(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        "热点出价容量清单",
        allure.attachment_type.JSON,
    )

    assert manifest["scenario"] == "bid_capacity"
    assert manifest.get("completed_at"), "容量运行必须完整结束"
    assert manifest["stages"], "容量运行至少应完成一个档位"
    assert not any(
        stage["assessment"] == "STOP"
        for stage in manifest["stages"]
    ), f"容量运行触发安全停止: {manifest['stages']}"

    auction_ids = [stage["auction_id"] for stage in manifest["stages"]]
    assert len(auction_ids) == len(set(auction_ids)), "每档必须使用独立竞拍"
    for stage in manifest["stages"]:
        metrics = stage.get("metrics") or {}
        assert metrics.get("actual_rps") is not None
        assert metrics.get("handled_rate") is not None
        assert metrics.get("technical_failure_rate") is not None
        assert metrics.get("accepted", 0) > 0
        assert metrics.get("unexpected_rejections") == 0
        assert metrics.get("handled_duration_p95") is not None
        assert metrics.get("handled_duration_p99") is not None
