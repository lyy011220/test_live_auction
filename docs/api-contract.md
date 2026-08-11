# 接口契约与端点说明

## 契约来源

接口 URL、HTTP 方法、请求参数和响应字段以当前被测后端运行时 OpenAPI 为准。默认本地地址为：

- OpenAPI JSON：`http://localhost:8080/v3/api-docs`
- Swagger UI：`http://localhost:8080/swagger-ui/index.html`

OpenAPI 的 `info.version` 属于被测后端运行时信息，不在本文硬编码。切换 `AUCTION_HTTP_BASE_URL` 后，应从对应环境重新获取契约。

业务状态、权限边界、实时事件和跨接口不变量由以下来源共同约束：

1. `models/enums.py` 中的稳定角色、房间状态、竞拍状态和事件类型；
2. `clients/` 与 `ws/` 中当前使用的协议形状；
3. `tests/` 中带稳定 Case ID 的验收用例；
4. [`直播竞拍平台测试用例.md`](直播竞拍平台测试用例.md) 中的可读清单。

如果 OpenAPI 没有描述某项业务行为，不应根据一次偶发现象修改断言；应先由后端或产品确认契约，再同步代码与文档。

## 当前代码使用的 HTTP 端点

| 域 | 方法与路径 | 用途 |
| --- | --- | --- |
| 健康 | `GET /api/health` | 后端健康检查 |
| 认证 | `POST /api/auth/register` | 注册普通用户或主播 |
| 认证 | `POST /api/auth/login` | 登录并获取 Token |
| 直播间管理 | `POST /api/admin/room` | 创建直播间 |
| 直播间管理 | `PUT /api/admin/room/{roomId}` | 修改直播间 |
| 直播间管理 | `POST /api/admin/room/{roomId}/start` | 开播 |
| 直播间管理 | `POST /api/admin/room/{roomId}/stop` | 下播 |
| 直播间管理 | `GET /api/admin/room` | 查询当前主播房间 |
| 直播间管理 | `GET /api/admin/room/live` | 查询后台直播中房间 |
| 直播间公开 | `GET /api/rooms` | 查询公开直播中房间 |
| 直播间公开 | `GET /api/rooms/{roomId}/online` | 查询在线人数 |
| 竞拍管理 | `POST /api/admin/auction` | 创建竞拍，JSON body |
| 竞拍管理 | `PUT /api/admin/auction/{auctionId}` | 修改竞拍规则，JSON body |
| 竞拍管理 | `POST /api/admin/auction/{auctionId}/start` | 启动竞拍 |
| 竞拍管理 | `POST /api/admin/auction/{auctionId}/cancel` | 取消竞拍，`reason` 为 query 参数 |
| 竞拍管理 | `GET /api/admin/auction/{auctionId}` | 查询后台竞拍详情 |
| 竞拍管理 | `GET /api/admin/auctions` | 查询主播竞拍列表，使用 `page`、`size` |
| 竞拍公开 | `GET /api/auction/{auctionId}` | 查询公开竞拍详情 |
| 竞拍公开 | `GET /api/room/{roomId}/auctions` | 查询房间竞拍列表 |
| 竞拍公开 | `GET /api/auction/{auctionId}/ranking` | 查询竞拍排名 |
| 出价 | `POST /api/auction/{auctionId}/bid` | 出价，`amount` 为 query 参数 |
| 出价 | `GET /api/user/bids` | 查询当前用户出价记录 |

端点表描述的是测试客户端当前调用范围，不代替完整 OpenAPI，也不表示后端只提供这些接口。

## WebSocket 与 STOMP 契约

| 项目 | 默认值或形状 |
| --- | --- |
| 握手地址 | `ws://localhost:8080/ws/websocket` |
| 连接鉴权 | STOMP `CONNECT` 携带 Token |
| 房间广播订阅 | `/topic/auction/{roomId}` |
| 用户被超价通知 | `/user/queue/outbid` |
| STOMP 出价目的地 | `/app/bid` |
| 稳定事件类型 | `STARTED`、`BID`、`DELAYED`、`SOLD`、`ENDED`、`CANCELLED`、`OUTBID`、`ONLINE` |

事件用例必须同时匹配事件类型和关键业务字段，不能把“收到任意消息”当作通过。需要业务终态的场景还会通过 REST 再次查询确认。

## 成功、失败与状态约束

- 正向请求同时验证传输成功、业务成功和关键响应字段。
- 后端负向响应的 HTTP 状态码和业务码尚未稳定，负向用例使用统一失败判定，并继续验证资源未落库、状态未变化、价格/次数/记录未变化或没有错误消息副作用。
- 当前稳定状态值见 `models/enums.py`：房间 `CREATED=1`、`LIVE=2`、`ENDED=3`；竞拍 `PENDING=1`、`LIVE=2`、`ENDED=3`、`SOLD=4`、`CANCELLED=5`。
- 金额边界使用字符串或 `Decimal` 表达，避免二进制浮点误差影响 0.01 精度和加价边界。

## k6 结果的后端绑定

性能场景执行时会读取目标环境的 OpenAPI，并在同名 `.meta.json` 中记录：

- 目标 `base_url`；
- OpenAPI SHA-256；
- OpenAPI `info.version`；
- 可选 `BACKEND_VERSION`；
- 场景名、开始/完成时间和 k6 退出码。

pytest 验收 PERF 结果时会重新获取当前 OpenAPI，拒绝目标地址不一致、OpenAPI 指纹变化、`BACKEND_VERSION` 变化、k6 非零退出或超过有效期的摘要。有效期默认 24 小时，可通过 `K6_SUMMARY_MAX_AGE_HOURS` 调整。

## 范围边界与同步规则

订单和支付域不在当前项目范围内，封顶成交用例只验证竞拍 `SOLD` 终态、价格和重复出价拒绝，不声明订单生成行为。

后端契约变化时按以下顺序同步：

1. 在目标环境确认 OpenAPI 形状和产品业务规则；
2. 更新领域客户端或 STOMP 适配；
3. 更新或新增带 Case ID 的测试及终态断言；
4. 更新 [`直播竞拍平台测试用例.md`](直播竞拍平台测试用例.md) 和相关说明；
5. 运行 `python -m pytest --collect-only -q`，确认收集成功且 Case ID 无重复；
6. 对受影响域执行真实后端回归。
