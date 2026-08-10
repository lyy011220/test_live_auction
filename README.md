# 直播竞拍平台自动化测试框架 (live_auction_qa)

独立测试框架, 覆盖直播竞拍系统的 REST API、STOMP over WebSocket、Python 确定性并发与 k6 性能测试。
- 接口形状来源: 后端运行时 OpenAPI；契约说明见 `docs/api-contract.md`。
- 业务行为来源: `models/enums.py` 与 `tests/` 中带稳定 Case ID 的验收用例。
- Allure 报告体系参考 `D:\project\api_test_frame\api_test_frame`。

## 目录结构

```
live_auction_qa/
├─ commons/        # 工具类 (allure_reports/logger_util/yaml_util)
├─ config/         # config.yaml 配置；环境变量/.env 可覆盖
├─ clients/        # 薄客户端层 (一资源一模块) + 逐请求 allure.attach
├─ ws/             # STOMP 客户端 + 事件谓词
├─ models/         # 稳定枚举(状态/角色/事件) + payload builders
├─ scenarios/      # AuctionLifecycle 链式 builder
├─ support/        # assertions/concurrency/traceability
├─ tests/          # 8 域用例 (health/auth/room/auction/bid/ws/concurrency/perf)
├─ load/           # k6 runner + 5 场景 + summary/provenance
├─ docs/           # 接口契约来源与维护说明
├─ conftest.py     # session banner + terminal_summary(result.txt) + 失败 attach
├─ run.py          # 一键: pytest -> allure generate -> 改报告标题
├─ environment.xml / categories.json   # Allure 报告环境与失败分类
└─ reports/        # temps(原始)/allures(报告)/k6/result.txt/traceability.md
```

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# 需安装 allure 命令行: https://docs.qameta.io/allure/
```

后端默认 `http://localhost:8080`, WS `ws://localhost:8080/ws/websocket`, 见 `config/config.yaml`。
可复制 `.env.example` 为 `.env`；环境变量优先于 `.env` 和 YAML 配置。

## 运行

```powershell
# 收集
python -m pytest --collect-only -q

# 仅跑某域示范用例 (需后端在线)
python -m pytest tests/health tests/auth -v
python -m pytest tests/bid -k "nor_001 or bnd_005" -v

# 一键跑测 + 生成 Allure 报告 (含自定义标题/环境信息)
python run.py
# 报告: reports\allures\index.html  或  allure serve reports\temps

# k6 性能 (需装 k6)
python -m load.runner --scenario bid_concurrent
python -m load.runner --scenario mixed_stress
```

## 用例与追溯

- 每个测试函数对应一个 Case ID (如 `AUTH-NOR-001`), 用 `@case("AUTH-NOR-001")` 登记；
  参数化用例会产生多个 pytest 执行项，因此 Case ID 数与执行项数不同。
- Allure 四件套: `@allure.epic("直播竞拍平台")` / `@feature(域)` / `@story(case-id)` / `@severity`+`@title`。
- session 结束生成 `reports/traceability.md`（完整源码目录）和
  `reports/traceability-current.md`（本次实际导入范围）。
- 结果路径固定在项目根目录，允许从任意子目录启动 pytest。

## 分层纪律

- 测试层只调 `clients/`/`scenarios/`/`support/`，不直接使用 `requests`；只有缺字段、非法路径等
  客户端正常方法无法表达的协议负向场景，才允许通过 `ApiClient` 发送原始请求。
- 稳定状态、角色和事件类型引用 `models/enums.py` 常量；不稳定错误码不固化为枚举。
- 客户端不足时先在 `clients/` 加方法, 不在测试里拼 URL。

## 已知实现行为

后端错误响应的 HTTP/业务码目前不稳定。负向用例统一使用 `assert_failed` 验证请求未成功，
并继续断言 token 未签发、资源未落库、价格/次数/记录不变等业务不变量；错误码仅用于失败诊断。

生命周期 fixture 和 k6 runner 会在结束时尽力取消活动竞拍并停止直播间。由于后端没有删除接口，
历史用户、房间和竞拍仍会保留；列表用例只匹配本轮创建的资源 ID。

k6 摘要必须带同名 `.meta.json`，且默认不得早于 24 小时。可通过
`K6_SUMMARY_MAX_AGE_HOURS` 调整有效期，通过 `BACKEND_VERSION` 强制绑定部署版本。
