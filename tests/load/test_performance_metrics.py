import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests" / "load" / "fixtures" / "performance_metrics_probe.js"
K6 = shutil.which("k6")


def _serve(status: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(
                {
                    "code": 200 if status == 200 else 500,
                    "data": {},
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
    return server, thread


def _run_probe(tmp_path: Path, status: int) -> tuple[subprocess.CompletedProcess, dict]:
    server, thread = _serve(status)
    summary_path = tmp_path / "summary.json"
    url = f"http://127.0.0.1:{server.server_port}/probe"
    try:
        result = subprocess.run(
            [
                K6,
                "run",
                "-e",
                f"URL={url}",
                "--summary-export",
                str(summary_path),
                str(PROBE),
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

    assert result.returncode == 0, result.stderr
    return result, json.loads(summary_path.read_text(encoding="utf-8"))


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_performance_metrics_record_success(tmp_path):
    _, summary = _run_probe(tmp_path, status=200)
    metrics = summary["metrics"]

    assert metrics["probe_requests"]["count"] == 1
    assert metrics["probe_success_rate"]["value"] == 1
    assert metrics["probe_technical_failure_rate"]["value"] == 0
    assert metrics["probe_success_duration"]["p(95)"] >= 0


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_performance_metrics_classify_server_error(tmp_path):
    _, summary = _run_probe(tmp_path, status=500)
    metrics = summary["metrics"]

    assert metrics["probe_requests"]["count"] == 1
    assert metrics["probe_success_rate"]["value"] == 0
    assert metrics["probe_technical_failure_rate"]["value"] == 1
    assert metrics["probe_5xx"]["count"] == 1
