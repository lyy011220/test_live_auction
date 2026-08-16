import json
from pathlib import Path

import allure
import pytest

from support.traceability import case


ROOT = Path(__file__).resolve().parents[2]
CAPACITY_REPORTS_ROOT = ROOT / "reports" / "k6" / "detail_capacity"

EPIC = allure.epic("直播竞拍平台")
FEATURE = allure.feature("性能域")


def _latest_capacity_run() -> tuple[Path, dict]:
    if not CAPACITY_REPORTS_ROOT.exists():
        pytest.skip(
            "未运行详情容量测试，请先执行: "
            "python -m load.performance.runner --scenario detail_capacity"
        )

    run_dirs = sorted(
        path
        for path in CAPACITY_REPORTS_ROOT.iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    )
    if not run_dirs:
        pytest.skip(
            "未运行详情容量测试，请先执行: "
            "python -m load.performance.runner --scenario detail_capacity"
        )

    run_dir = run_dirs[-1]
    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    return run_dir, manifest


@EPIC
@FEATURE
@allure.story("PERF-CAPACITY-001")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("PERF-CAPACITY-001 竞拍详情固定 RPS 分档容量")
@pytest.mark.perf
@pytest.mark.load
@case("PERF-CAPACITY-001")
def test_perf_capacity_001_detail_fixed_rates():
    run_dir, manifest = _latest_capacity_run()
    summary_path = run_dir / "summary.md"

    allure.attach(
        summary_path.read_text(encoding="utf-8"),
        "竞拍详情容量对比",
        allure.attachment_type.TEXT,
    )
    allure.attach(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        "竞拍详情容量清单",
        allure.attachment_type.JSON,
    )

    assert manifest["scenario"] == "detail_capacity"
    assert manifest.get("completed_at"), "容量运行必须完整结束"
    assert manifest["stages"], "容量运行至少应完成一个档位"
    assert not any(
        stage["assessment"] == "STOP"
        for stage in manifest["stages"]
    ), f"容量运行触发安全停止: {manifest['stages']}"

    for stage in manifest["stages"]:
        metrics = stage.get("metrics") or {}
        assert metrics.get("actual_rps") is not None
        assert metrics.get("technical_failure_rate") is not None
        assert metrics.get("success_duration_p95") is not None
        assert metrics.get("success_duration_p99") is not None
