// PERF-STRESS-001 | 五十人混合场景稳定性 (5 分钟)
// 设计: 50 VU constant-vus 持续 5 分钟; 每 VU 首轮出价一次 (递增唯一价, max=550<1000 不封顶),
// 后续持续读详情/排行榜模拟观众观看负载。校验: 无网络错误 (checks 全过)、5xx 错误率 < 1%、
// 压测后服务仍可用 (teardown 详情 200)。
//
// checks 刻意宽松 (status>0 = 收到响应): 罕见 5xx 计入 http_req_failed_rate (稳定性指标),
// 不直接 fail check, 避免 5 分钟长压测因单次毛刺整体红。
import { check, sleep } from 'k6';
import {
  bidOnce,
  fetchDetail,
  fetchRanking,
  isBusinessHandled,
  loadTokens,
  requireEnv,
} from '../lib/common.js';
import {
  createPerformanceMetrics,
  parseJsonSafely,
  recordPerformanceResult,
} from '../lib/performance_metrics.js';

const BASE = requireEnv('BASE_URL');
const ITEM_ID = requireEnv('ITEM_ID');
const TOKENS = loadTokens();
const bidMetrics = createPerformanceMetrics('bid');
const detailMetrics = createPerformanceMetrics('detail');
const rankingMetrics = createPerformanceMetrics('ranking');

const START_PRICE = 109; // startPrice(100) + increment(9)
// per-VU 状态: 首轮出价一次, 后续只读 (k6 模块级变量在同一个 VU 的多次迭代间保留)。
let hasBid = false;

export const options = {
  summaryTrendStats: [
    'avg',
    'min',
    'med',
    'max',
    'p(90)',
    'p(95)',
    'p(99)',
  ],
  scenarios: {
    mixed_stress: {
      executor: 'constant-vus',
      vus: 50,
      duration: '5m',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
    bid_success_rate: ['rate>0.99'],
    bid_technical_failure_rate: ['rate<0.01'],
    detail_success_rate: ['rate>0.99'],
    detail_technical_failure_rate: ['rate<0.01'],
    ranking_success_rate: ['rate>0.99'],
    ranking_technical_failure_rate: ['rate<0.01'],
  },
};

export default function () {
  const t = TOKENS[(__VU - 1) % TOKENS.length];

  if (!hasBid) {
    // 递增唯一价: VU1=109 ... VU50=550, 均 < maxPrice(1000), 不触发封顶成交。
    const amount = START_PRICE + (__VU - 1) * 9;
    const bid = bidOnce(BASE, ITEM_ID, t.token, amount);
    const parsedBid = parseJsonSafely(bid);
    recordPerformanceResult(bidMetrics, bid, {
      businessSuccess: !parsedBid.parseFailed
        && isBusinessHandled(bid.status),
      parseFailed: parsedBid.parseFailed,
    });
    check(bid, { '出价收到响应': () => bid.status > 0 });
    hasBid = true;
  }

  const detail = fetchDetail(BASE, ITEM_ID);
  const ranking = fetchRanking(BASE, ITEM_ID);
  const parsedDetail = parseJsonSafely(detail);
  const parsedRanking = parseJsonSafely(ranking);

  recordPerformanceResult(detailMetrics, detail, {
    businessSuccess: detail.status === 200
      && !parsedDetail.parseFailed
      && parsedDetail.body
      && Number(parsedDetail.body.code) === 200,
    parseFailed: parsedDetail.parseFailed,
  });
  recordPerformanceResult(rankingMetrics, ranking, {
    businessSuccess: ranking.status === 200
      && !parsedRanking.parseFailed
      && parsedRanking.body
      && Number(parsedRanking.body.code) === 200,
    parseFailed: parsedRanking.parseFailed,
  });

  check(detail, { '详情请求收到响应': () => detail.status > 0 });
  check(ranking, { '排行榜请求收到响应': () => ranking.status > 0 });

  // 节流模拟真实观看节奏, 避免 empty loop 打爆本地后端。
  sleep(0.3);
}

export function teardown() {
  const detail = fetchDetail(BASE, ITEM_ID);
  check(detail, { '压测后服务仍可用': () => detail.status === 200 });
  console.log(JSON.stringify({ postStressStatus: detail.status }));
}
