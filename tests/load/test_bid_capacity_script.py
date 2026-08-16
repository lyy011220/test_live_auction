import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "load" / "k6" / "performance" / "bid_capacity.js"
K6 = shutil.which("k6")


def _run_bid_script(
    tmp_path: Path,
    status: int,
    message: str = "",
    code: int | None = None,
) -> tuple[subprocess.CompletedProcess, dict, list[dict]]:
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            amount = float(
                parse_qs(urlparse(self.path).query)["amount"][0]
            )
            received.append({
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            })
            body = json.dumps(
                {
                    "code": code if code is not None else (
                        200 if status == 200 else status
                    ),
                    "message": message,
                    "data": (
                        {"currentPrice": amount, "bidCount": len(received)}
                        if status == 200
                        else None
                    ),
                }
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "tokens.json"
    token_file.write_text(
        json.dumps([{"userid": 7, "token": "probe-token"}]),
        encoding="utf-8",
    )
    summary_path = tmp_path / f"summary-{status}.json"

    try:
        result = subprocess.run(
            [
                K6,
                "run",
                "-e",
                "ITEM_ID=77",
                "-e",
                f"BASE_URL=http://127.0.0.1:{server.server_port}",
                "-e",
                "TARGET_RPS=1",
                "-e",
                "DURATION=1s",
                "-e",
                "PRE_ALLOCATED_VUS=1",
                "-e",
                "MAX_VUS=1",
                "-e",
                f"TOKENS_FILE={token_file}",
                "-e",
                "START_PRICE=100",
                "-e",
                "INCREMENT_AMOUNT=1",
                "-e",
                "MAX_PRICE=1000000",
                "--summary-export",
                str(summary_path),
                str(SCRIPT),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    return (
        result,
        json.loads(summary_path.read_text(encoding="utf-8")),
        received,
    )


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_bid_capacity_script_records_accepted_bid(tmp_path):
    result, summary, received = _run_bid_script(tmp_path, status=200)
    metrics = summary["metrics"]
    request_count = len(received)

    assert request_count >= 1
    assert result.returncode == 0, result.stderr
    assert metrics["bid_requests"]["count"] == request_count
    assert metrics["bid_accepted"]["count"] == request_count
    assert metrics["bid_business_rejections"]["count"] == 0
    assert metrics["bid_unexpected_rejections"]["count"] == 0
    assert metrics["bid_handled_rate"]["value"] == 1
    assert metrics["bid_handled_duration"]["p(95)"] >= 0
    assert metrics["bid_accepted_amount"]["max"] == 100 + request_count
    assert received[0]["path"] == "/api/auction/77/bid?amount=101"
    assert all(
        request["authorization"] == "Bearer probe-token"
        for request in received
    )


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_bid_capacity_script_treats_conflict_as_business_rejection(tmp_path):
    result, summary, received = _run_bid_script(
        tmp_path,
        status=409,
        message="出价金额低于当前价格",
    )
    metrics = summary["metrics"]

    assert result.returncode == 0, result.stderr
    assert metrics["bid_accepted"]["count"] == 0
    assert metrics["bid_business_rejections"]["count"] == len(received)
    assert metrics["bid_unexpected_rejections"]["count"] == 0
    assert metrics["bid_technical_failure_rate"]["value"] == 0
    assert metrics["bid_handled_rate"]["value"] == 1
    assert metrics["bid_handled_duration"]["p(95)"] >= 0


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_bid_capacity_classifies_confirmed_backend_conflict(tmp_path):
    result, summary, received = _run_bid_script(
        tmp_path,
        status=400,
        code=2006,
        message="加价幅度不符合规则（当前价: 107.00, 最低出价: 108.00）",
    )
    metrics = summary["metrics"]

    assert received
    assert result.returncode == 0, result.stderr
    assert metrics["bid_business_rejections"]["count"] == len(received)
    assert metrics["bid_unexpected_rejections"]["count"] == 0


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
@pytest.mark.parametrize(
    "message",
    ["竞拍已结束", "出价金额超过封顶价"],
)
def test_bid_capacity_script_rejects_non_conflict_409(tmp_path, message):
    result, summary, received = _run_bid_script(
        tmp_path,
        status=409,
        message=message,
    )
    metrics = summary["metrics"]

    assert received
    assert result.returncode != 0
    assert metrics["bid_business_rejections"]["count"] == 0
    assert metrics["bid_unexpected_rejections"]["count"] == len(received)
    assert metrics["bid_handled_rate"]["value"] == 0
