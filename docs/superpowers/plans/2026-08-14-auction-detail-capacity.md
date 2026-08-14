# Auction Detail Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible hotspot capacity test for `GET /api/auction/{id}` that runs 50/100/200/400 RPS as separate fixed-rate stages and reports the capacity knee.

**Architecture:** A focused k6 script executes exactly one `constant-arrival-rate` stage per process. A Python capacity runner prepares one long-lived auction, invokes that script once per target rate, parses each independent k6 summary, applies safety/acceptance rules, writes a run-scoped comparison report, and always cleans up the auction and room.

**Tech Stack:** Python 3, pytest, k6 JavaScript, `subprocess`, existing API clients and `AuctionLifecycle`.

## Global Constraints

- Test only `GET /api/auction/{ITEM_ID}`; do not add ranking, bid, room-list, login, or WebSocket traffic.
- Use one shared hot `ITEM_ID` for every stage in one run.
- Default stages are exactly 50, 100, 200, and 400 RPS, each for 2 minutes, with 15 seconds cooldown.
- Create a 20-minute auction once per capacity run; do not create bidder users or token files.
- Store every run under `reports/k6/detail_capacity/{run_id}/`; never overwrite a previous run.
- A successful detail request requires HTTP 200, body `code == 200`, parseable JSON, and `data.id == ITEM_ID`.
- Keep successful response latency separate from failed-response latency.
- Stop escalation when technical failure rate reaches 10%, health fails, or a valid summary cannot be produced.
- Do not modify or delete the user's unrelated dirty-worktree changes.

---

## File Structure

- Modify: `load/k6/detail_capacity.js` — one fixed-rate hotspot detail load process.
- Create: `tests/load/__init__.py` — load-test unit/integration test package marker.
- Create: `tests/load/test_detail_capacity_script.py` — local stub-server integration tests for the k6 script.
- Create: `load/capacity_model.py` — parse stage metrics and decide acceptance/safety stop.
- Create: `tests/load/test_capacity_model.py` — pure unit tests for metric parsing and decisions.
- Create: `load/capacity_report.py` — run directory, manifest, and Markdown comparison report.
- Create: `tests/load/test_capacity_report.py` — report output tests.
- Create: `load/capacity_runner.py` — resource lifecycle, four k6 subprocesses, cooldown, and cleanup.
- Create: `tests/load/test_capacity_runner.py` — command construction and orchestration tests with no real backend traffic.
- Modify: `README.md` — capacity smoke and full-run commands plus interpretation guidance.

---

### Task 1: One-Stage k6 Detail Capacity Script

**Files:**
- Modify: `load/k6/detail_capacity.js`
- Create: `tests/load/__init__.py`
- Create: `tests/load/test_detail_capacity_script.py`

**Interfaces:**
- Consumes env: `BASE_URL`, `ITEM_ID`, `TARGET_RPS`, `DURATION`, `PRE_ALLOCATED_VUS`, `MAX_VUS`.
- Produces metrics: `detail_requests`, `detail_success_rate`, `detail_technical_failure_rate`, `detail_4xx`, `detail_5xx`, `detail_network_errors`, `detail_success_duration`.

- [ ] **Step 1: Create the package marker and write the failing success-path integration test**

Create an empty `tests/load/__init__.py`. Add this structure to `tests/load/test_detail_capacity_script.py`:

```python
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "load" / "k6" / "detail_capacity.js"
K6 = shutil.which("k6")


def _serve_detail(item_id: int, returned_id: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != f"/api/auction/{item_id}":
                self.send_error(404)
                return
            body = json.dumps({
                "code": 200,
                "message": "success",
                "data": {"id": returned_id},
            }).encode()
            self.send_response(200)
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


def _run_k6(tmp_path: Path, returned_id: int):
    item_id = 123
    server, thread = _serve_detail(item_id, returned_id)
    summary = tmp_path / "summary.json"
    env = os.environ.copy()
    env.update({
        "BASE_URL": f"http://127.0.0.1:{server.server_port}",
        "ITEM_ID": str(item_id),
        "TARGET_RPS": "1",
        "DURATION": "2s",
        "PRE_ALLOCATED_VUS": "1",
        "MAX_VUS": "2",
    })
    try:
        result = subprocess.run(
            [K6, "run", "--summary-export", str(summary), str(SCRIPT)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    data = json.loads(summary.read_text(encoding="utf-8"))
    return result, data


@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_detail_capacity_records_success_metrics(tmp_path):
    result, data = _run_k6(tmp_path, returned_id=123)
    assert result.returncode == 0, result.stderr
    assert data["metrics"]["detail_success_rate"]["value"] == 1
    assert data["metrics"]["detail_technical_failure_rate"]["value"] == 0
    assert data["metrics"]["detail_success_duration"]["count"] >= 1
    assert data["metrics"].get("dropped_iterations", {}).get("count", 0) == 0
```

- [ ] **Step 2: Run the test and verify it fails because the empty script exports no runnable scenario**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load/test_detail_capacity_script.py::test_detail_capacity_records_success_metrics -q
```

Expected: FAIL because `detail_capacity.js` is empty and k6 cannot run the required scenario/metrics.

- [ ] **Step 3: Implement the minimal fixed-rate k6 script**

Implement `load/k6/detail_capacity.js` with:

```javascript
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

function requireEnv(name) {
  const value = __ENV[name];
  if (!value) throw new Error(`missing env ${name}`);
  return value;
}

function positiveInt(name) {
  const value = Number(requireEnv(name));
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

const BASE = requireEnv('BASE_URL').replace(/\/$/, '');
const ITEM_ID = requireEnv('ITEM_ID');
const TARGET_RPS = positiveInt('TARGET_RPS');
const DURATION = requireEnv('DURATION');
const PRE_ALLOCATED_VUS = positiveInt('PRE_ALLOCATED_VUS');
const MAX_VUS = positiveInt('MAX_VUS');

if (MAX_VUS < PRE_ALLOCATED_VUS) {
  throw new Error('MAX_VUS must be >= PRE_ALLOCATED_VUS');
}

const detailRequests = new Counter('detail_requests');
const detailSuccessRate = new Rate('detail_success_rate');
const detailTechnicalFailureRate = new Rate('detail_technical_failure_rate');
const detail4xx = new Counter('detail_4xx');
const detail5xx = new Counter('detail_5xx');
const detailNetworkErrors = new Counter('detail_network_errors');
const detailSuccessDuration = new Trend('detail_success_duration', true);

export const options = {
  scenarios: {
    detail_capacity: {
      executor: 'constant-arrival-rate',
      rate: TARGET_RPS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: PRE_ALLOCATED_VUS,
      maxVUs: MAX_VUS,
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    detail_success_rate: ['rate>0.99'],
    detail_technical_failure_rate: [
      { threshold: 'rate<0.10', abortOnFail: true, delayAbortEval: '30s' },
    ],
    dropped_iterations: ['count==0'],
  },
};

export default function () {
  const response = http.get(`${BASE}/api/auction/${ITEM_ID}`, {
    tags: { name: 'GET /api/auction/:id', endpoint: 'auction_detail' },
  });
  detailRequests.add(1);

  let body = null;
  let parseFailed = false;
  try {
    body = response.json();
  } catch (_) {
    parseFailed = true;
  }

  const networkError = response.status === 0;
  const is4xx = response.status >= 400 && response.status < 500;
  const is5xx = response.status >= 500;
  const success = response.status === 200
    && !parseFailed
    && Number(body.code) === 200
    && String(body.data && body.data.id) === String(ITEM_ID);
  const technicalFailure = networkError || is5xx || parseFailed;

  detailSuccessRate.add(success);
  detailTechnicalFailureRate.add(technicalFailure);
  if (is4xx) detail4xx.add(1);
  if (is5xx) detail5xx.add(1);
  if (networkError) detailNetworkErrors.add(1);
  if (success) detailSuccessDuration.add(response.timings.duration);

  check(response, {
    '详情 HTTP 200': () => response.status === 200,
    '详情业务码 200': () => !parseFailed && Number(body.code) === 200,
    '详情 itemId 匹配': () => !parseFailed
      && String(body.data && body.data.id) === String(ITEM_ID),
  });
}
```

- [ ] **Step 4: Run the success test and verify it passes**

Run the Step 2 command. Expected: PASS with one test passed.

- [ ] **Step 5: Add the failing-business-response test**

Append:

```python
@pytest.mark.skipif(K6 is None, reason="k6 未安装")
def test_detail_capacity_rejects_wrong_item_id(tmp_path):
    result, data = _run_k6(tmp_path, returned_id=999)
    assert result.returncode == 99
    assert data["metrics"]["detail_success_rate"]["value"] == 0
    assert data["metrics"]["checks"]["fails"] >= 1
```

- [ ] **Step 6: Run both script tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load/test_detail_capacity_script.py -q
```

Expected: 2 passed, or 2 skipped only when k6 is not installed.

- [ ] **Step 7: Commit Task 1**

```powershell
git add load/k6/detail_capacity.js tests/load/__init__.py tests/load/test_detail_capacity_script.py
git commit -m "feat: add fixed-rate auction detail capacity script"
```

---

### Task 2: Stage Metric Model and Capacity Decisions

**Files:**
- Create: `load/capacity_model.py`
- Create: `tests/load/test_capacity_model.py`

**Interfaces:**
- Produces: `CapacityStageResult`, `StageAssessment`, `stage_result_from_summary()`, `assess_stage()`.
- Consumed later by: `load/capacity_runner.py` and `load/capacity_report.py`.

- [ ] **Step 1: Write failing unit tests for summary parsing**

Create `tests/load/test_capacity_model.py` with a `_summary()` factory containing `http_reqs.rate`, custom Rate values, success Trend p95/p99, `dropped_iterations.count`, and `vus.max`. Assert:

```python
from load.capacity_model import assess_stage, stage_result_from_summary


def _summary(*, actual_rps=100.0, success=1.0, technical=0.0,
             p95=20.0, p99=40.0, dropped=0, vus=12):
    return {
        "metrics": {
            "http_reqs": {"rate": actual_rps, "count": 12000},
            "detail_success_rate": {"value": success},
            "detail_technical_failure_rate": {"value": technical},
            "detail_success_duration": {"p(95)": p95, "p(99)": p99},
            "dropped_iterations": {"count": dropped},
            "vus": {"max": vus},
        }
    }


def test_stage_result_parses_capacity_metrics():
    result = stage_result_from_summary(_summary(), target_rps=100, k6_exit_code=0)
    assert result.target_rps == 100
    assert result.actual_rps == 100.0
    assert result.success_rate == 1.0
    assert result.technical_failure_rate == 0.0
    assert result.success_p95_ms == 20.0
    assert result.success_p99_ms == 40.0
    assert result.dropped_iterations == 0
    assert result.vus_max == 12


def test_stage_is_acceptable_at_target_and_clean():
    result = stage_result_from_summary(_summary(), target_rps=100, k6_exit_code=0)
    assessment = assess_stage(result, baseline_p95_ms=20.0)
    assert assessment.acceptable is True
    assert assessment.stop_escalation is False
    assert assessment.reasons == ()


def test_stage_rejects_capacity_knee_signals():
    result = stage_result_from_summary(
        _summary(actual_rps=95, technical=0.02, p95=45, dropped=3),
        target_rps=100,
        k6_exit_code=99,
    )
    assessment = assess_stage(result, baseline_p95_ms=20.0)
    assert assessment.acceptable is False
    assert "actual_rps_below_99_percent" in assessment.reasons
    assert "technical_failure_rate_at_least_1_percent" in assessment.reasons
    assert "dropped_iterations" in assessment.reasons
    assert "p95_over_2x_baseline" in assessment.reasons


def test_stage_stops_escalation_at_ten_percent_technical_failures():
    result = stage_result_from_summary(
        _summary(technical=0.10), target_rps=100, k6_exit_code=99
    )
    assert assess_stage(result, baseline_p95_ms=20.0).stop_escalation is True
```

- [ ] **Step 2: Run the tests and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load/test_capacity_model.py -q
```

Expected: collection error because `load.capacity_model` does not exist.

- [ ] **Step 3: Implement the immutable result and assessment model**

Create `load/capacity_model.py` with frozen dataclasses using these exact public fields:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CapacityStageResult:
    target_rps: int
    actual_rps: float
    success_rate: float
    technical_failure_rate: float
    success_p95_ms: float | None
    success_p99_ms: float | None
    dropped_iterations: int
    vus_max: int
    http_requests: int
    k6_exit_code: int


@dataclass(frozen=True)
class StageAssessment:
    acceptable: bool
    stop_escalation: bool
    reasons: tuple[str, ...]
```

Implement `stage_result_from_summary(summary, target_rps, k6_exit_code)` by reading the exact metric keys used in Task 1. Missing required metrics must raise `ValueError` naming the missing metric; only `dropped_iterations` may default to zero.

Implement `assess_stage(result, baseline_p95_ms)` with these reasons and rules:

```text
actual_rps_below_99_percent             actual_rps < target_rps * 0.99
technical_failure_rate_at_least_1_percent technical_failure_rate >= 0.01
dropped_iterations                      dropped_iterations > 0
p95_over_2x_baseline                    p95 exists and p95 > baseline * 2
```

Set `acceptable = not reasons`. Set `stop_escalation` when technical failure rate is at least `0.10`.

- [ ] **Step 4: Run the model tests and verify all pass**

Run the Step 2 command. Expected: 4 passed.

- [ ] **Step 5: Commit Task 2**

```powershell
git add load/capacity_model.py tests/load/test_capacity_model.py
git commit -m "feat: model detail capacity stage results"
```

---

### Task 3: Run-Scoped Manifest and Comparison Report

**Files:**
- Create: `load/capacity_report.py`
- Create: `tests/load/test_capacity_report.py`

**Interfaces:**
- Consumes: `CapacityStageResult` and `StageAssessment` from Task 2.
- Produces: `create_run_directory()`, `write_manifest()`, `write_summary_markdown()`.

- [ ] **Step 1: Write failing tests for unique run directories and stage comparison output**

Test that `create_run_directory(root, run_id)` creates `root / run_id` and refuses to reuse an existing directory. Test that `write_summary_markdown()` writes one row per completed stage with target RPS, actual RPS, p95, p99, technical failure percentage, dropped iterations, VUs, and assessment.

Use two explicit `CapacityStageResult` instances: one acceptable 50 RPS baseline and one rejected 100 RPS stage. Assert the Markdown contains `50`, `100`, `PASS`, `KNEE`, and the exact reason `technical_failure_rate_at_least_1_percent`.

- [ ] **Step 2: Run the report tests and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load/test_capacity_report.py -q
```

Expected: collection error because `load.capacity_report` does not exist.

- [ ] **Step 3: Implement report functions**

Implement:

```python
def create_run_directory(root: Path, run_id: str) -> Path
def write_manifest(run_dir: Path, manifest: Mapping[str, Any]) -> Path
def write_summary_markdown(
    run_dir: Path,
    rows: Sequence[tuple[CapacityStageResult, StageAssessment]],
) -> Path
```

Requirements:

- `create_run_directory` uses `mkdir(parents=True, exist_ok=False)`.
- `write_manifest` writes UTF-8 indented JSON to `manifest.json`.
- `write_summary_markdown` writes `summary.md` with a Markdown table sorted by target RPS.
- Assessment label is `PASS` when acceptable, `KNEE` when unacceptable but escalation may continue, and `STOP` when `stop_escalation` is true.
- Missing p95/p99 prints `N/A`, never `0`.

- [ ] **Step 4: Run report tests and verify they pass**

Run the Step 2 command. Expected: all report tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add load/capacity_report.py tests/load/test_capacity_report.py
git commit -m "feat: report detail capacity stages"
```

---

### Task 4: Capacity Runner and Safety Stop

**Files:**
- Create: `load/capacity_runner.py`
- Create: `tests/load/test_capacity_runner.py`

**Interfaces:**
- Consumes: Task 1 script, Task 2 model functions, Task 3 report functions, `AuctionLifecycle`, `AuctionClient`, `RoomClient`, `HealthClient`, and `backend_identity`.
- Produces CLI: `python -m load.capacity_runner`.

- [ ] **Step 1: Write failing tests for command construction**

Define the intended pure interface in the test:

```python
from pathlib import Path

from load.capacity_runner import CapacityConfig, build_k6_command


def test_build_k6_command_contains_one_fixed_rate(tmp_path):
    config = CapacityConfig(
        base_url="http://localhost:8080",
        k6_bin="k6",
        rates=(50, 100, 200, 400),
        duration="2m",
        cooldown_seconds=15,
        reports_root=tmp_path,
        pre_allocated_vus=None,
        max_vus=None,
    )
    command = build_k6_command(
        config=config,
        item_id=77,
        target_rps=100,
        summary_path=tmp_path / "100.json",
        script_path=Path("load/k6/detail_capacity.js"),
    )
    joined = " ".join(str(part) for part in command)
    assert "TARGET_RPS=100" in joined
    assert "ITEM_ID=77" in joined
    assert "DURATION=2m" in joined
    assert "PRE_ALLOCATED_VUS=50" in joined
    assert "MAX_VUS=200" in joined
```

- [ ] **Step 2: Run the command test and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load/test_capacity_runner.py::test_build_k6_command_contains_one_fixed_rate -q
```

Expected: collection error because `load.capacity_runner` does not exist.

- [ ] **Step 3: Implement configuration and command construction only**

Create frozen `CapacityConfig` with the fields used by the test. Implement defaults:

```python
def default_preallocated(target_rps: int) -> int:
    return max(50, math.ceil(target_rps * 0.25))


def default_max_vus(target_rps: int, preallocated: int) -> int:
    return max(preallocated, target_rps * 2)
```

`build_k6_command()` returns the same argument style already used by `load.runner`: `k6 run`, repeated `-e KEY=VALUE`, `--summary-export`, then the script path.

- [ ] **Step 4: Run the command test and verify it passes**

Run the Step 2 command. Expected: 1 passed.

- [ ] **Step 5: Add orchestration tests with a fake k6 process**

Add tests for `run_capacity(config)` by monkeypatching:

- `AuctionLifecycle.create_started_auction` to return IDs and a fake merchant client;
- `subprocess.run` to write a valid synthetic summary at the `--summary-export` path;
- `time.sleep` to record cooldown calls without waiting;
- `HealthClient.health` to return a successful health response before and after stages;
- `AuctionClient.admin_cancel` and `RoomClient.stop` to record cleanup.

Assert a clean run:

- calls k6 exactly four times in rate order;
- uses one `auctionId` for all four commands;
- creates the auction with `durationMinutes=20`;
- sleeps three times, not after the final stage;
- writes four independent summary paths and a final `summary.md`;
- executes cancel and stop exactly once.

Add a stop test where the second synthetic summary has `detail_technical_failure_rate.value == 0.10`. Assert only 50 and 100 RPS run, 200/400 are marked `not_run`, and cleanup still executes.

- [ ] **Step 6: Run orchestration tests and verify they fail because `run_capacity` is missing**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load/test_capacity_runner.py -q
```

Expected: command test passes and orchestration tests fail on missing behavior.

- [ ] **Step 7: Implement `run_capacity(config)` and CLI `main()`**

Required flow:

```text
create run_id and run directory
record OpenAPI identity
create one started auction with durationMinutes=20
for rate in config.rates:
    require a successful health check before starting the stage
    build unique summary path
    run k6 subprocess
    require summary file
    parse CapacityStageResult
    establish 50-RPS p95 baseline from first stage
    assess stage
    require a successful health check after the stage
    update manifest and Markdown
    stop if assessment.stop_escalation
    cooldown unless this was the final executed stage
finally:
    cancel auction
    stop room
    persist cleanup results
```

CLI arguments and defaults:

```text
--rates 50,100,200,400
--duration 2m
--cooldown 15
--k6 <config K6.bin or k6>
--pre-allocated-vus <optional integer>
--max-vus <optional integer>
```

Read `BASE_URL` from the existing YAML configuration. Use `datetime.now(timezone.utc)` plus a filesystem-safe UTC timestamp for `run_id`. Store all metadata without tokens or passwords.

- [ ] **Step 8: Run all runner tests and verify they pass**

Run the Step 6 command. Expected: all runner tests pass without contacting a real backend.

- [ ] **Step 9: Commit Task 4**

```powershell
git add load/capacity_runner.py tests/load/test_capacity_runner.py
git commit -m "feat: orchestrate auction detail capacity stages"
```

---

### Task 5: Real Smoke, Full Regression, and Usage Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes CLI from Task 4.
- Produces documented smoke/full commands and interpretation rules.

- [ ] **Step 1: Add README commands before executing external load**

Document:

```powershell
# Script and orchestration smoke: 1 RPS for 10 seconds
.\.venv\Scripts\python.exe -m load.capacity_runner --rates 1 --duration 10s --cooldown 0 --pre-allocated-vus 1 --max-vus 2

# Default exploratory capacity run
.\.venv\Scripts\python.exe -m load.capacity_runner
```

Also document report location, PASS/KNEE/STOP meanings, and the requirement to correlate stage times with server monitoring.

- [ ] **Step 2: Run focused automated tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/load -q
```

Expected: all load tests pass; only k6 integration tests may skip when k6 is unavailable.

- [ ] **Step 3: Run existing non-load regression tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/perf -q
```

Expected: existing functional suite passes, or any pre-existing backend failures are recorded separately and not attributed to this feature.

- [ ] **Step 4: Run the 1-RPS real smoke against the configured backend**

Run the smoke command from Step 1 only after confirming the configured backend is the intended test environment. Expected:

- one run directory is created;
- the single stage has `actual_rps` close to 1;
- technical failure rate is zero;
- dropped iterations is zero;
- cleanup records successful auction cancellation and room stop.

- [ ] **Step 5: Inspect the smoke report before full load**

Open `summary.md` and `manifest.json`. Confirm target URL, OpenAPI hash, item/room IDs, start/end times, k6 exit code, cleanup outcome, and absence of credentials.

- [ ] **Step 6: Commit Task 5**

```powershell
git add README.md
git commit -m "docs: explain auction detail capacity runs"
```

- [ ] **Step 7: Execute the default four-stage run only with monitoring ready**

Run the default command. Do not continue to full load if the smoke was invalid, k6 shares a constrained host with the backend, or server monitoring is unavailable. Preserve the full run directory as the evidence artifact.
