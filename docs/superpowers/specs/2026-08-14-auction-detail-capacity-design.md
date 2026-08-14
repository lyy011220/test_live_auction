# 竞拍详情容量测试设计

## 1. 背景与决策

当前项目已有的 pytest 并发用例和多数 k6 场景主要验证并发正确性；`mixed_stress` 虽能制造持续负载，但使用固定 VU、混合多个接口并聚合指标，不能形成可解释的单接口容量曲线。

本设计在现有工程中新增竞拍详情容量测试，只测试：

```text
GET /api/auction/{ITEM_ID}
```

由于目前没有业务目标 RPS 或正式延迟 SLA，第一版采用探索性容量测试。用户已确认使用“同一脚本、四档固定 RPS、每档独立运行并生成独立报告”的方案。

## 2. 目标

本场景要回答：

1. 热门竞拍详情接口在 50、100、200、400 RPS 下，实际能完成多少 RPS？
2. 随着目标 RPS 增长，成功请求的 p95/p99 如何变化？
3. 从哪一档开始出现 5xx、网络错误、超时或 dropped iterations？
4. 当前环境下，详情接口的容量拐点位于哪两个相邻档位之间？

## 3. 非目标

第一版不测试：

- 排行榜、出价、直播间列表或 WebSocket；
- 多竞拍分散流量；
- 登录和 Token 性能；
- 业务写入吞吐；
- 正式生产 SLA；
- 自动采集服务端 CPU、内存、GC、数据库连接池指标。

服务端指标仍需与每档运行时间对齐，由测试人员从部署监控中记录。若 k6 与后端运行在同一台机器，本结果只用于脚本验证和版本对比，不作为正式容量结论。

## 4. 负载模型

### 4.1 热点数据

四档运行访问同一个 `ITEM_ID`，模拟大量观众集中观看同一场热门竞拍。竞拍全程不发生出价等业务写入，避免状态变化影响各档比较。

### 4.2 固定到达率

`detail_capacity.js` 每次只执行一个固定目标，使用 k6 `constant-arrival-rate`：

| 档位 | 目标速率 | 持续时间 |
| --- | ---: | ---: |
| L1 | 50 RPS | 2 分钟 |
| L2 | 100 RPS | 2 分钟 |
| L3 | 200 RPS | 2 分钟 |
| L4 | 400 RPS | 2 分钟 |

相邻档位之间默认冷却 15 秒。目标 RPS、持续时间、预分配 VU、最大 VU 和冷却时间都必须支持通过命令行参数或环境变量覆盖，但上述数值作为可复现的默认值。

### 4.3 VU 容量

目标 RPS 不等于 VU 数。k6 根据响应耗时占用 VU：

- `preAllocatedVUs` 默认取 `max(50, ceil(targetRps × 0.25))`；
- `maxVUs` 默认取 `max(preAllocatedVUs, targetRps × 2)`；
- 两项均允许覆盖；
- `dropped_iterations > 0` 必须单独记录，不能把负载生成器 VU 不足误判为后端容量不足。

## 5. 测试数据生命周期

容量调度器在四档运行开始前只创建一次测试资源：

```text
注册主播 → 创建直播间 → 开播 → 创建竞拍 → 开始竞拍
```

竞拍 `durationMinutes` 固定为 20 分钟，覆盖 8 分钟负载、档位冷却、准备和清理时间。四档完成或提前终止后：

```text
取消竞拍 → 下播
```

详情接口公开访问，因此该场景不创建 bidder 用户池、不生成 Token 文件。准备阶段与负载阶段必须解耦，资源创建请求不计入详情容量指标。

## 6. 组件设计

### 6.1 `load/k6/detail_capacity.js`

职责：

- 读取 `BASE_URL`、`ITEM_ID`、`TARGET_RPS`、`DURATION`、`PRE_ALLOCATED_VUS`、`MAX_VUS`；
- 使用 `constant-arrival-rate` 生成单接口固定到达率；
- 为请求设置稳定低基数名称 `GET /api/auction/:id`；
- 校验 HTTP 状态、业务码和返回竞拍 ID；
- 记录详情接口专属成功率、技术失败率、成功响应耗时与错误分类；
- 不打印每次成功响应，避免日志 I/O 干扰负载生成。

现有 `fetchDetail` 可用向后兼容方式增加可选请求参数，以便容量脚本设置稳定 tags；旧场景调用方式保持不变。

### 6.2 `load/capacity_runner.py`

职责：

- 复用 `AuctionLifecycle` 创建一次 20 分钟竞拍；
- 不调用用户池生成逻辑；
- 按 50、100、200、400 RPS 顺序分别启动 k6；
- 每档写入独立 summary 和 metadata；
- 每档结束后解析安全指标并决定是否继续升档；
- 无论正常结束或异常退出都尝试取消竞拍并下播。

该调度器与现有 `load.runner` 并存，避免把公开读容量测试强行塞入“每个场景都需要 bidder Token”的旧抽象。后续其他容量场景稳定后，再评估是否统一调度模型。

### 6.3 报告目录

每轮容量测试使用独立 `run_id`：

```text
reports/k6/detail_capacity/{run_id}/
├─ manifest.json
├─ detail_capacity_0050rps.json
├─ detail_capacity_0050rps.meta.json
├─ detail_capacity_0100rps.json
├─ detail_capacity_0100rps.meta.json
├─ detail_capacity_0200rps.json
├─ detail_capacity_0200rps.meta.json
├─ detail_capacity_0400rps.json
├─ detail_capacity_0400rps.meta.json
└─ summary.md
```

若提前停止，未运行档位不得生成伪造结果；`manifest.json` 记录其状态为 `not_run` 和停止原因。

## 7. 请求校验与指标口径

每次请求的成功条件同时满足：

```text
HTTP status == 200
body.code == 200
body.data.id == ITEM_ID
响应体是可解析 JSON
```

需要独立输出：

- `detail_requests`：总请求数；
- `detail_success_rate`：满足全部成功条件的比例；
- `detail_technical_failure_rate`：网络错误、超时、5xx 或不可解析响应比例；
- `detail_4xx`、`detail_5xx`、`detail_network_errors`：错误分类计数；
- `detail_success_duration`：只记录成功请求的响应耗时；
- k6 内置 `http_reqs`、`http_req_failed`、`dropped_iterations`、`vus_max`。

成功请求耗时必须与失败请求分开。不能使用包含快速 500 或 status=0 请求的聚合 `http_req_duration p95` 代表正常用户体验。

## 8. 容量判断与安全停止

在没有业务 SLA 的前提下，某一档出现任一条件即判为“不可接受档位”：

- 实际完成 RPS 小于目标 RPS 的 99%；
- `detail_technical_failure_rate >= 1%`；
- `dropped_iterations > 0`；
- 成功请求 p95 超过 50 RPS 基线 p95 的 2 倍。

容量拐点记录为“最后一个可接受档位”和“第一个不可接受档位”之间，而不是直接宣称一个精确最大 RPS。

为保护目标服务，出现以下任一条件时停止当前档并不再升档：

- 技术失败率达到 10%，持续观察窗口不少于 30 秒；
- 健康检查失败；
- k6 无法生成有效 summary；
- 测试人员从服务端监控发现资源达到预设保护线。

安全停止不等于测试通过；报告必须保留已完成档位和终止原因。

## 9. 运行元数据

每档 metadata 至少记录：

- `run_id`、档位、目标 RPS、持续时间；
- 目标 `base_url`、`auction_id`、`room_id`；
- OpenAPI SHA-256、可选 `BACKEND_VERSION`；
- 开始和完成时间；
- k6 退出码；
- 目标和实际 VU 配置；
- 压测机与后端是否同机；
- 提前停止原因。

`summary.md` 生成一张按目标 RPS 排序的对比表，禁止只展示整轮聚合数字。

## 10. 错误处理

- 准备资源失败：不启动任何 k6 档位；
- 某档 k6 启动失败或 summary 缺失：标记该档 `invalid` 并停止升档；
- 响应 JSON 解析失败：计入技术失败，日志仅采样有限错误，避免海量输出；
- 清理失败：保留资源 ID 和错误信息，不能覆盖容量运行结论；
- 用户中断：执行 `finally` 清理，并保留已完成报告。

## 11. 验证策略

实现顺序遵循先小后大：

1. 使用 1 RPS、10 秒验证脚本参数、业务断言和报告结构；
2. 使用无效 `ITEM_ID` 验证业务失败不会被算作成功；
3. 为调度器的档位命名、停止判断和报告聚合编写单元测试；
4. 使用 5 RPS、30 秒完成调度器集成冒烟；
5. 确认负载机和服务端监控后，执行正式 50/100/200/400 RPS 阶梯。

第一版只完成热点详情容量闭环。排行榜、写入和混合负载不在本次实现中顺带扩展。
