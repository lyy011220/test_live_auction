// PERF-LOAD-003 | 重复多轮并发与副作用核对
// 5 VU × 3 轮, 每次出价严格递增且唯一 (amount = 109 + iter*50 + (vu-1)*10), 按轮次轻度错峰。
// 校验: 无 5xx; 终态 currentPrice==排行榜最高价; 排行榜投影与 bidCount 基本一致。
import { check, sleep } from 'k6';
import { bidOnce, fetchDetail, fetchRanking, isBusinessHandled, loadTokens, parseData, parseList, requireEnv } from './lib/common.js';

const BASE = requireEnv('BASE_URL');
const ITEM_ID = requireEnv('ITEM_ID');
const TOKENS = loadTokens();
const VUS = 5;
const ROUNDS = 3;

if (TOKENS.length < VUS) {
  throw new Error(`tokens.json 仅 ${TOKENS.length} 个用户, 本脚本需要 ${VUS} 个`);
}

// 每轮每 VU 的出价: 严格递增且全局唯一。
// iter0: 109,119,129,139,149  iter1: 159,...,199  iter2: 209,...,249
function amountFor(iter, vuIndex) {
  return 109 + iter * 50 + vuIndex * 10;
}

export const options = {
  scenarios: {
    repeat_rounds: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: ROUNDS,
      maxDuration: '2m',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const vuIndex = __VU - 1;
  const iter = __ITER;
  const t = TOKENS[vuIndex];
  const amount = amountFor(iter, vuIndex);
  // 按轮次轻度错峰 (iter0 立即, iter1 延 0.1s, iter2 延 0.2s), 形成 3 个松散并发轮次,
  // 区别于 PERF-LOAD-001 的纯 stampede, 聚焦"多轮重复"语义。仍保留 5xx 断言。
  sleep(iter * 0.1);
  const res = bidOnce(BASE, ITEM_ID, t.token, amount);
  const body = parseData(res);
  const success = res.status === 200;
  const currentPrice = Number(body.currentPrice);

  check(res, {
    '递增出价请求被业务处理': () => isBusinessHandled(res.status),
    '递增出价请求无服务端错误': () => res.status < 500,
    '成功出价后当前价不低于提交价': () => !success || currentPrice >= amount,
  });

  console.log(JSON.stringify({ vu: __VU, iter, userid: t.userid, amount, status: res.status, success, currentPrice }));
}

export function teardown() {
  const detail = fetchDetail(BASE, ITEM_ID);
  const ranking = fetchRanking(BASE, ITEM_ID);
  const data = parseData(detail);
  const rankingData = parseList(ranking);
  const finalPrice = Number(data.currentPrice);
  const bidCount = Number(data.bidCount);
  const top = rankingData[0] || {};
  const topAmount = Number(top.amount);

  check(detail, {
    '获取竞拍详情成功': () => detail.status === 200,
    '终价等于排行榜最高价': () => finalPrice === topAmount,
    // 排行榜按用户去重 (取每人最高价), 故条数 <= 总成功出价次数。
    '排行榜条数不超过出价次数 (轮间无污染)': () => bidCount >= rankingData.length,
    '至少有一个有效出价': () => rankingData.length >= 1,
  });

  console.log(JSON.stringify({ finalPrice, bidCount, rankingCount: rankingData.length, topAmount, topUserId: top.userId }));
}
