// k6 共享工具: 出价 / 查详情 / 查排名 / 解析响应 / 环境校验。
// 各 scenario 脚本 import 复用, 避免重复样板。
import http from 'k6/http';

// 业务拒绝(400/409)是预期行为, 仅 5xx/网络错误计入 http_req_failed。
// 默认回调把 4xx 也算失败, 会误报压测失败率, 这里收窄到 200-499。
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

// 读取必填环境变量, 缺失则抛错 (由 runner.py 注入)。
export function requireEnv(name) {
  const v = __ENV[name];
  if (!v) {
    throw new Error(`missing env ${name}; run: python -m load.runner --scenario ...`);
  }
  return v;
}

// 加载 tokens.json: [{ userid, token }, ...]。
export function loadTokens() {
  const path = requireEnv('TOKENS_FILE');
  const parsed = JSON.parse(open(path));
  return Array.isArray(parsed) ? parsed : (parsed.bidders || []);
}

// REST 出价: amount 走 query param (master 约定, 非 JSON body)。
export function bidOnce(base, itemId, token, amount) {
  return http.post(
    `${base}/api/auction/${itemId}/bid?amount=${amount}`,
    null,
    { headers: { Authorization: `Bearer ${token}` } }
  );
}

export function fetchDetail(base, itemId) {
  return http.get(`${base}/api/auction/${itemId}`);
}

export function fetchRanking(base, itemId) {
  return http.get(`${base}/api/auction/${itemId}/ranking`);
}

// 安全解析 data 对象 (容错: 非 JSON 或异常时返回 {})。
export function parseData(resp) {
  try {
    return resp.json('data') || {};
  } catch (_) {
    return {};
  }
}

export function parseList(resp) {
  try {
    return resp.json('data') || [];
  } catch (_) {
    return [];
  }
}

// 业务可接受: 成功 / 业务拒绝(400) / 并发冲突(409); 5xx 视为缺陷。
export function isBusinessHandled(status) {
  return status === 200 || status === 400 || status === 409;
}
