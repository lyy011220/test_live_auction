// PERF-LOAD-002 | 五人同时同价竞价
// 5 个用户几乎同时提交相同价格 110 (>= 最低合法价 109), 仅一人成为有效最高出价。
import { check } from 'k6';
import { bidOnce, fetchDetail, fetchRanking, isBusinessHandled, loadTokens, parseData, parseList, requireEnv } from './lib/common.js';

const BASE = requireEnv('BASE_URL');
const ITEM_ID = requireEnv('ITEM_ID');
const TOKENS = loadTokens();
const BID_AMOUNT = 110;
const USER_COUNT = 5;

if (TOKENS.length < USER_COUNT) {
  throw new Error(`tokens.json 仅 ${TOKENS.length} 个用户, 本脚本需要 ${USER_COUNT} 个`);
}

export const options = {
  scenarios: {
    same_amount_race: {
      executor: 'per-vu-iterations',
      vus: USER_COUNT,
      iterations: 1,
      maxDuration: '30s',
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
  const res = bidOnce(BASE, ITEM_ID, t.token, BID_AMOUNT);
  const success = res.status === 200;

  check(res, {
    '同价出价请求被业务处理': () => isBusinessHandled(res.status),
    '同价出价请求无服务端错误': () => res.status < 500,
  });

  console.log(JSON.stringify({ vu: __VU, userid: t.userid, amount: BID_AMOUNT, status: res.status, success }));
}

export function teardown() {
  const detail = fetchDetail(BASE, ITEM_ID);
  const ranking = fetchRanking(BASE, ITEM_ID);
  const detailData = parseData(detail);
  const rankingData = parseList(ranking);
  const finalPrice = Number(detailData.currentPrice);
  const top = rankingData[0] || {};
  const expectedUserIds = TOKENS.slice(0, USER_COUNT).map(t => String(t.userid));

  check(detail, {
    '获取竞拍详情成功': () => detail.status === 200,
    '最终成交价为110': () => finalPrice === BID_AMOUNT,
  });

  check(ranking, {
    '获取排行榜成功': () => ranking.status === 200,
    '只存在一个有效出价': () => rankingData.length === 1,
    '最高出价为110': () => Number(top.amount) === BID_AMOUNT,
    '最高出价用户属于本轮同价参与用户': () => expectedUserIds.includes(String(top.userId)),
  });

  console.log(JSON.stringify({ finalPrice, topUserId: top.userId, topAmount: top.amount, expectedUserIds }));
}
