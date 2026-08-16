// PERF-CAPACITY-002 | 单竞拍热点 REST 出价容量测试
// 单次进程只运行一个固定 RPS 档位；每档竞拍由 Python 适配器独立创建。
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';
import { bidOnce, loadTokens, requireEnv } from '../lib/common.js';
import {
  createPerformanceMetrics,
  parseJsonSafely,
  recordPerformanceResult,
} from '../lib/performance_metrics.js';

const BASE = requireEnv('BASE_URL');
const ITEM_ID = requireEnv('ITEM_ID');
const TARGET_RPS = positiveInt('TARGET_RPS');
const DURATION = requireEnv('DURATION');
const PRE_ALLOCATED_VUS = positiveInt('PRE_ALLOCATED_VUS');
const MAX_VUS = positiveInt('MAX_VUS');
const START_PRICE = positiveNumber('START_PRICE');
const INCREMENT_AMOUNT = positiveNumber('INCREMENT_AMOUNT');
const MAX_PRICE = positiveNumber('MAX_PRICE');
const TOKENS = loadTokens();

const bidMetrics = createPerformanceMetrics('bid');
const accepted = new Counter('bid_accepted');
const businessRejections = new Counter('bid_business_rejections');
const unexpectedRejections = new Counter('bid_unexpected_rejections');
const handledRate = new Rate('bid_handled_rate');
const handledDuration = new Trend('bid_handled_duration', true);
const acceptedAmount = new Trend('bid_accepted_amount');
const rejectedDuration = new Trend('bid_rejected_duration', true);

if (MAX_VUS < PRE_ALLOCATED_VUS) {
  throw new Error('MAX_VUS must be >= PRE_ALLOCATED_VUS');
}
if (TOKENS.length === 0) {
  throw new Error('TOKENS_FILE must contain at least one bidder token');
}

function positiveInt(name) {
  const value = Number(requireEnv(name));
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

function positiveNumber(name) {
  const value = Number(requireEnv(name));
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be a positive number`);
  }
  return value;
}

const conflictPatterns = (
  __ENV.BID_CONFLICT_PATTERNS
  || [
    '加价幅度不符合规则',
    '低于当前价格',
    '不高于当前价格',
    '必须高于当前价格',
    '未达到最低加价',
    '低于最低出价',
    '价格已经更新',
    'price must be higher than current',
    'bid must be higher than current',
    'price has changed',
    'stale bid',
    'minimum increment not met',
  ].join('|')
).split('|').map((value) => value.trim().toLowerCase()).filter(Boolean);

function isExpectedPriceConflict(status, payload) {
  if (status !== 400 && status !== 409) {
    return false;
  }
  const errorText = [
    payload.message,
    payload.msg,
    payload.error,
    payload.errors,
  ].filter((value) => value !== undefined && value !== null)
    .map((value) => (
      typeof value === 'string' ? value : JSON.stringify(value)
    ))
    .join(' ')
    .toLowerCase();
  return conflictPatterns.some((pattern) => errorText.includes(pattern));
}

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
    bid_capacity: {
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
    bid_handled_rate: ['rate>0.99'],
    bid_unexpected_rejections: ['count==0'],
    bid_technical_failure_rate: [
      {
        threshold: 'rate<0.10',
        abortOnFail: true,
        delayAbortEval: '30s',
      },
    ],
    dropped_iterations: ['count==0'],
  },
};

export default function () {
  const token = TOKENS[(__VU - 1) % TOKENS.length];
  const sequence = exec.scenario.iterationInTest + 1;
  const amount = START_PRICE + sequence * INCREMENT_AMOUNT;

  if (amount > MAX_PRICE) {
    throw new Error(
      `generated bid ${amount} exceeds MAX_PRICE ${MAX_PRICE}`
    );
  }

  const response = bidOnce(BASE, ITEM_ID, token.token, amount);
  const parsed = parseJsonSafely(response);
  const payload = parsed.body || {};
  const data = payload.data || {};
  const wasAccepted =
    response.status === 200
    && !parsed.parseFailed
    && Number(payload.code) === 200
    && Number(data.currentPrice) >= amount;
  const wasBusinessRejected =
    !parsed.parseFailed
    && isExpectedPriceConflict(response.status, payload);

  const performance = recordPerformanceResult(bidMetrics, response, {
    businessSuccess: wasAccepted,
    parseFailed: parsed.parseFailed,
  });
  const wasUnexpectedRejection =
    !wasAccepted
    && !wasBusinessRejected
    && !performance.technicalFailure;
  const wasHandled = wasAccepted || wasBusinessRejected;

  accepted.add(wasAccepted ? 1 : 0);
  businessRejections.add(wasBusinessRejected ? 1 : 0);
  unexpectedRejections.add(wasUnexpectedRejection ? 1 : 0);
  handledRate.add(wasHandled);
  if (wasHandled) {
    handledDuration.add(response.timings.duration);
  }

  if (wasAccepted) {
    acceptedAmount.add(Number(data.currentPrice));
  }
  if (wasBusinessRejected) {
    rejectedDuration.add(response.timings.duration);
  }

  check(response, {
    '出价结果被明确分类': () => (
      wasHandled || wasUnexpectedRejection || performance.technicalFailure
    ),
    '出价没有非预期业务拒绝': () => !wasUnexpectedRejection,
    '接受出价后的当前价不低于提交价': () => (
      !wasAccepted || Number(data.currentPrice) >= amount
    ),
  });
}
