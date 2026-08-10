# 接口契约来源

本项目不再引用仓库中不存在的外部 Markdown。接口形状以当前被测后端自动生成的 OpenAPI 为准：

- OpenAPI JSON：`http://localhost:8080/v3/api-docs`
- Swagger UI：`http://localhost:8080/swagger-ui/index.html`
- 当前 OpenAPI 声明版本：`1.0.0`

OpenAPI 用于确认 URL、请求参数和响应字段；业务状态与跨接口不变量由 `models/enums.py` 和对应的 `tests/` 用例表达。如果 OpenAPI 没有描述某个业务行为，不应根据一次偶发现象修改断言，应先由后端或产品确认契约。

订单与支付域不在本项目当前测试范围内。

性能结果额外记录 OpenAPI SHA-256、目标地址、运行完成时间和可选的 `BACKEND_VERSION`。设置环境变量 `BACKEND_VERSION` 后，pytest 会拒绝其他后端版本生成的 k6 摘要；未设置时使用 OpenAPI 指纹与 24 小时有效期兜底。
