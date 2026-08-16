// PERF-LOAD-001 | 二十人乱序不同金额并发
// 设计点: 含非法价(<109)/重复价/最高价300(在 index 12, 非末位), 验证最终价由最高有效出价决定。
import { check } from 'k6';
import { bidOnce, fetchDetail, fetchRanking, isBusinessHandled, loadTokens, parseData, parseList, requireEnv } from '../lib/common.js';

const BASE = requireEnv('BASE_URL');
const ITEM_ID = requireEnv('ITEM_ID');
const TOKENS = loadTokens();

// 出价集合: 含非法价(<109)/重复价/最高价300(非末位), 验证最终价由最高有效出价决定。
// 预期终价 = max(集合); 最高出价人 = 该价首次出现位置对应的 token (动态推导, 改集合即自动同步)。
// 约束: 最高价需在集合中唯一, 否则 indexOf 取首个匹配 (当前 300 唯一)。
const ROUND_AMOUNTS = [
  117, 103, 226, 108, 241,
  112, 234, 105, 241, 220,
  101, 110, 300, 245, 110,
  231, 254, 106, 245, 275,
];
const EXPECTED_FINAL_PRICE = Math.max(...ROUND_AMOUNTS);
const EXPECTED_HIGHEST_USER_ID = TOKENS[ROUND_AMOUNTS.indexOf(EXPECTED_FINAL_PRICE)].userid;

if (TOKENS.length < ROUND_AMOUNTS.length) {
  throw new Error(`tokens.json 仅 ${TOKENS.length} 个用户, 本脚本需要 ${ROUND_AMOUNTS.length} 个`);
}

export const options = {
  scenarios: {
    concurrent_bid: {
      executor: 'per-vu-iterations',
      vus: TOKENS.length,
      iterations: 1,
      maxDuration: '1m',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const index = __VU - 1;
  const t = TOKENS[index];
  const amount = ROUND_AMOUNTS[index];
  const res = bidOnce(BASE, ITEM_ID, t.token, amount);
  const body = parseData(res);
  const currentPrice = Number(body.currentPrice);
  const success = res.status === 200;
  const belowMin = amount < 109; // 最低合法价 = startPrice(100) + increment(9)

  check(res, {
    '出价请求被业务处理': () => isBusinessHandled(res.status),
    '出价请求无服务端错误': () => res.status < 500,
    '低于最低合法价的出价必须失败': () => !belowMin || !success,
    '成功出价必须返回当前价': () => !success || !Number.isNaN(currentPrice),
    '成功出价后当前价不低于提交价': () => !success || currentPrice >= amount,
  });

  console.log(JSON.stringify({ vu: __VU, userid: t.userid, amount, status: res.status, success, currentPrice }));
}

export function teardown() {
  const detail = fetchDetail(BASE, ITEM_ID);
  const ranking = fetchRanking(BASE, ITEM_ID);
  const data = parseData(detail);
  const rankingData = parseList(ranking);
  const finalPrice = Number(data.currentPrice);
  const top = rankingData[0] || {};

  check(detail, {
    '获取竞拍详情成功': () => detail.status === 200,
    '最终价格等于最高有效出价300': () => finalPrice === EXPECTED_FINAL_PRICE,
  });

  check(ranking, {
    '获取排行榜成功': () => ranking.status === 200,
    '排行榜最高出价为300': () => Number(top.amount) === EXPECTED_FINAL_PRICE,
    '最高出价用户是tokens[12]': () => String(top.userId || '') === String(EXPECTED_HIGHEST_USER_ID),
  });

  console.log(JSON.stringify({ finalPrice, highestBidderId: top.userId, highestBidAmount: top.amount }));
}
