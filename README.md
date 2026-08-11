# 直播竞拍平台自动化测试框架

`live_auction_qa` 是面向直播竞拍后端的独立自动化测试项目，覆盖 REST API、STOMP over WebSocket、Python 确定性并发和 k6 性能测试。

当前源码登记 **72 个稳定 Case ID**，pytest 收集 **90 个执行项**；参数化场景会让一个 Case ID 生成多个执行项。用例明细见 [`docs/直播竞拍平台测试用例.md`](docs/直播竞拍平台测试用例.md)。

## 文档导航

- [`docs/直播竞拍平台测试用例.md`](docs/直播竞拍平台测试用例.md)：与当前 `tests/` 一一对应的用例清单、参数化覆盖和范围说明。
- [`docs/项目理解.md`](docs/项目理解.md)：项目架构、数据生命周期、断言策略、报告和维护指南。
- [`docs/api-contract.md`](docs/api-contract.md)：接口契约来源、当前端点矩阵和同步规则。

## 测试范围

| 域 | 覆盖内容 | 稳定 Case ID |
| --- | --- | ---: |
| HEALTH | 后端健康检查 | 1 |
| AUTH | 注册、登录、字段校验和管理接口鉴权 | 8 |
| ROOM | 直播间生命周期、列表、在线人数和归属权限 | 15 |
| AUC | 竞拍生命周期、列表、数值边界和归属权限 | 14 |
| BID | 出价规则、参数校验、鉴权和状态限制 | 14 |
| WS | 事件、在线人数、订阅隔离和 STOMP 出价安全 | 12 |
| CON | 同价竞争、重复请求和陈旧价格竞争 | 3 |
| PERF | 4 个负载场景和 1 个混合压力场景 | 5 |

订单、支付和数据库直连校验不在当前范围内。查询与数据一致性通过上述业务域中的终态、列表、排名和出价记录断言完成，不另设 `DATA` Case ID 域。

## 目录结构

```text
live_auction_qa/
├─ clients/        # REST 领域客户端与统一响应封装
├─ commons/        # 配置、日志和 Allure 辅助
├─ config/         # 默认运行配置
├─ docs/           # 用例、架构与契约说明
├─ load/           # k6 runner、5 个场景、摘要与来源校验
├─ models/         # 稳定状态/角色/事件枚举和 payload builders
├─ scenarios/      # 可复用竞拍生命周期与等待逻辑
├─ support/        # 断言、并发、追溯、时间与用户池
├─ tests/          # 8 个测试域及共享 fixtures
├─ ws/             # STOMP 客户端和事件谓词
├─ conftest.py     # 报告、结果汇总和追溯钩子
├─ run.py          # pytest + Allure 静态报告入口
└─ reports/        # Allure、k6、文本结果和追溯矩阵运行产物
```

## 环境准备

基础运行需要 Python、可访问的直播竞拍后端和 `requirements.txt` 中的依赖。生成 Allure 静态报告需另装 Allure CLI；执行性能场景需另装 k6。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

默认地址：

- HTTP：`http://localhost:8080`
- WebSocket：`ws://localhost:8080/ws/websocket`
- STOMP 出价目的地：`/app/bid`

配置优先级为：**进程环境变量 > 项目根目录 `.env` > `config/config.yaml`**。

| 环境变量 | 对应配置 | 默认值 |
| --- | --- | --- |
| `AUCTION_HTTP_BASE_URL` | `BASE.base_live_auction_url` | `http://localhost:8080` |
| `AUCTION_WS_URL` | `BASE.ws_url` | `ws://localhost:8080/ws/websocket` |
| `AUCTION_API_TIMEOUT` | `API_TIMEOUT.timeout` | `5` 秒 |
| `AUCTION_DEFAULT_PASSWORD` | `ACCOUNT.default_password` | `123456` |
| `K6_BIN` | `K6.bin` | `k6` |
| `AUCTION_REPORT_TYPE` | `REPORT_TYPE` | `allure` |
| `BACKEND_VERSION` | k6 结果部署版本约束 | 未设置 |
| `K6_SUMMARY_MAX_AGE_HOURS` | k6 结果最大有效期 | `24` 小时 |

## 运行测试

```powershell
# 仅收集，不访问后端；当前应为 90 个执行项
python -m pytest --collect-only -q

# 健康检查或指定业务域
python -m pytest tests/health -v
python -m pytest tests/auth tests/room tests/auction tests/bid -v
python -m pytest tests/ws tests/concurrency -v

# 按 marker、Case ID 片段或慢速属性筛选
python -m pytest -m "room or auction" -v
python -m pytest tests/bid -k "nor_001 or bnd_005" -v
python -m pytest -m "not slow and not perf" -v

# 完整 pytest，并在随后调用 Allure CLI 生成静态报告
python run.py
```

`python run.py` 将静态报告写到 `reports/allures/index.html`。只需查看 pytest 产生的原始 Allure 数据时，可运行：

```powershell
allure serve reports\temps
```

## 运行 k6 场景

pytest 中的 PERF 用例只验收已有 k6 摘要；摘要不存在时相应用例会跳过。先运行目标场景，再执行 `tests/perf`：

```powershell
python -m load.runner --scenario bid_concurrent
python -m load.runner --scenario bid_same_amount_race
python -m load.runner --scenario bid_repeat_rounds
python -m load.runner --scenario ws_bid_concurrent
python -m load.runner --scenario mixed_stress

python -m pytest tests/perf -v
```

每个 `reports/k6/<scenario>.json` 必须配套同名 `.meta.json`。验收时会检查场景名、k6 退出码、目标地址、OpenAPI 指纹、可选 `BACKEND_VERSION` 和结果新鲜度，防止复用错误环境或过期结果。

## 用例与追溯

- 每个测试函数通过 `@case("域-类型-编号")` 登记唯一 Case ID。
- Allure 使用 epic、feature、story、severity 和 title 描述业务层级。
- 参数化场景共享一个业务意图和 Case ID，但会产生多个 pytest 执行项。
- 正常执行结束后生成 `reports/traceability.md`（完整源码清单）和 `reports/traceability-current.md`（本次导入范围）。
- `reports/result.txt` 汇总本次执行项总数、通过、失败、跳过、错误、时长和成功率；`--collect-only` 不写执行结果。

## 实现约束

- 测试优先调用 `clients/`、`scenarios/` 和 `support/`，只有正常客户端无法表达的畸形请求才直接使用 `ApiClient`。
- 状态、角色和事件类型引用 `models/enums.py`；后端尚未稳定的错误码不固化为枚举。
- 负向用例除验证请求失败外，还验证 Token、状态、价格、次数、记录或消息等业务不变量。
- fixture 和 k6 runner 会尽力取消活动竞拍并停止直播间，但后端没有物理删除接口，历史用户、房间和竞拍仍会保留。
- 列表和历史类断言只匹配本轮创建的资源 ID 或唯一名称，不依赖后端总量。

## 接口契约

URL、参数和响应字段以被测后端运行时 OpenAPI 为准；状态流转、权限边界和跨接口不变量以稳定枚举及验收用例为准。默认 OpenAPI 地址为：

- `http://localhost:8080/v3/api-docs`
- `http://localhost:8080/swagger-ui/index.html`

调整后端契约或测试用例后，请同时更新测试用例清单和相关说明文档，并重新运行收集检查。
