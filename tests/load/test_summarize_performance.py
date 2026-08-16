import json

from load.summarize import capacity_to_markdown, parse, to_markdown


def test_parse_uses_vus_max_metric_instead_of_active_vus(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps({
            "metrics": {
                "vus": {"max": 5},
                "vus_max": {"value": 6, "max": 6},
            }
        }),
        encoding="utf-8",
    )

    assert parse(summary_path)["vus_max"] == 6


def test_parse_and_render_endpoint_performance_metrics(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "detail_requests": {"count": 200, "rate": 100.0},
                    "detail_success_rate": {"value": 0.995},
                    "detail_technical_failure_rate": {"value": 0.005},
                    "detail_4xx": {"count": 1},
                    "detail_5xx": {"count": 1},
                    "detail_network_errors": {"count": 0},
                    "detail_success_duration": {
                        "p(95)": 120.5,
                        "p(99)": 180.25,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    summary = parse(summary_path)

    assert summary["performance_endpoints"]["detail"] == {
        "request_count": 200,
        "actual_rps": 100.0,
        "success_rate": 0.995,
        "technical_failure_rate": 0.005,
        "client_errors": 1,
        "server_errors": 1,
        "network_errors": 0,
        "success_duration_p95": 120.5,
        "success_duration_p99": 180.25,
    }

    markdown = to_markdown(summary)
    assert "| detail |" in markdown
    assert "99.50%" in markdown
    assert "0.50%" in markdown
    assert "120.50ms" in markdown
    assert "180.25ms" in markdown


def test_parse_bid_outcome_metrics(tmp_path):
    summary_path = tmp_path / "bid-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "bid_requests": {"count": 200, "rate": 100.0},
                    "bid_success_rate": {"value": 0.25},
                    "bid_technical_failure_rate": {"value": 0.005},
                    "bid_4xx": {"count": 149},
                    "bid_5xx": {"count": 1},
                    "bid_network_errors": {"count": 0},
                    "bid_success_duration": {
                        "p(95)": 130.0,
                        "p(99)": 190.0,
                    },
                    "bid_accepted": {"count": 50},
                    "bid_business_rejections": {"count": 149},
                    "bid_unexpected_rejections": {"count": 0},
                    "bid_handled_rate": {"value": 0.995},
                    "bid_handled_duration": {
                        "p(95)": 145.0,
                        "p(99)": 210.0,
                    },
                    "bid_accepted_amount": {"max": 982.0},
                }
            }
        ),
        encoding="utf-8",
    )

    summary = parse(summary_path)
    bid = summary["performance_endpoints"]["bid"]

    assert bid["accepted"] == 50
    assert bid["business_rejections"] == 149
    assert bid["unexpected_rejections"] == 0
    assert bid["handled_rate"] == 0.995
    assert bid["handled_duration_p95"] == 145.0
    assert bid["handled_duration_p99"] == 210.0
    assert bid["accepted_amount_max"] == 982.0


def test_render_bid_capacity_outcomes():
    markdown = capacity_to_markdown({
        "scenario": "bid_capacity",
        "run_id": "run-1",
        "base_url": "http://localhost:8080",
        "duration": "2m",
        "cooldown_seconds": 20,
        "stages": [{
            "target_rps": 100,
            "assessment": "PASS",
            "reasons": [],
            "metrics": {
                "actual_rps": 100.0,
                "success_rate": 0.25,
                "technical_failure_rate": 0.0,
                "success_duration_p95": 120.0,
                "success_duration_p99": 180.0,
                "client_errors": 9000,
                "server_errors": 0,
                "network_errors": 0,
                "dropped_iterations": 0,
                "vus_max": 40,
                "accepted": 3000,
                "business_rejections": 9000,
                "unexpected_rejections": 0,
                "handled_rate": 1.0,
                "handled_duration_p95": 140.0,
                "handled_duration_p99": 205.0,
                "accepted_amount_max": 12100,
            },
        }],
    })

    assert markdown.startswith("# 单竞拍热点出价容量测试")
    assert "| 目标 RPS | 实际 RPS | 接受率 |" in markdown
    assert "| 接受数 | 竞争拒绝 | 非预期拒绝 | 处理率 | 最高接受价 |" in markdown
    assert "| 3000 | 9000 | 0 | 100.00% | 12100.00 |" in markdown
    assert "| 140.00ms | 205.00ms |" in markdown
