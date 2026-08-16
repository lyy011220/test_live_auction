// PERF-CAPACITY-001 | 竞拍详情热点接口容量测试
// 单次运行只施加一个固定 RPS；不同档位由外部命令分别启动。
// 全部请求访问同一个 ITEM_ID，用于探测热点详情接口容量。
import { check } from 'k6';
import { fetchDetail, requireEnv } from '../lib/common.js';
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
const detailMetrics = createPerformanceMetrics('detail');

if (MAX_VUS < PRE_ALLOCATED_VUS) {
  throw new Error('MAX_VUS must be >= PRE_ALLOCATED_VUS');
}

function positiveInt(name) {
  const value = Number(requireEnv(name));

  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }

  return value;
}


//Options 配置
export const options = {
  // summaryTrendStats：定义要记录的趋势统计指标
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
    detail_capacity: {
      // 容量测试专用——精确控制每秒请求数，探测接口容量拐点
      executor: 'constant-arrival-rate', // 固定到达率执行器
      rate: TARGET_RPS,                  // 目标 RPS
      timeUnit: '1s',
      duration: DURATION,                // 压测持续时间
      preAllocatedVUs: PRE_ALLOCATED_VUS,// 预分配 VUs 数量
      maxVUs: MAX_VUS,                   // 最大 VUs 数量
    },
  },
  // thresholds：定义压测阈值，用于判断是否需要停止压测或触发失败
  // 通过不通过的标准：
  // 1. 断言通过率 > 99%
  // 2. 详情成功率 > 99%
  // 3. 详情技术失败率 < 10%
  // 4. 无丢弃迭代次数
  thresholds: {
    checks: ['rate>0.99'],
    detail_success_rate: ['rate>0.99'],
    detail_technical_failure_rate: [
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
  const response = fetchDetail(BASE, ITEM_ID);
  const parsed = parseJsonSafely(response);
  const payload = parsed.body || {};

  const businessCodeMatched =
    !parsed.parseFailed && Number(payload.code) === 200;

  const itemIdMatched =
    !parsed.parseFailed
    && payload.data
    && String(payload.data.id) === String(ITEM_ID);

  const success =
    response.status === 200
    && businessCodeMatched
    && itemIdMatched;

  recordPerformanceResult(detailMetrics, response, {
    businessSuccess: success,
    parseFailed: parsed.parseFailed,
  });

  check(response, {
    '详情请求返回 HTTP 200': () => response.status === 200,
    '详情业务码为 200': () => businessCodeMatched,
    '详情竞拍 ID 匹配': () => itemIdMatched,
  });
}
