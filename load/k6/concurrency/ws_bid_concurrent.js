// PERF-LOAD-004 | 二十人 WebSocket (STOMP) 并发出价
// 设计: 每个 VU 独立 STOMP 连接 -> 订阅 /topic/auction/{roomId} -> 错峰出价 ->
// 等待 BID 广播, 校验 WS 广播往返可用且无 5xx。teardown 断言最终价 == max(AMOUNTS)。
//
// 鉴权镜像 ws/stomp_client.py: token 走 STOMP CONNECT 帧的 Authorization 头 (非 HTTP 握手头),
// 并补 Protocol12 自动注入的 host 头。
import ws from 'k6/ws';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import { fetchDetail, parseData, loadTokens, requireEnv } from '../lib/common.js';

const BASE = requireEnv('BASE_URL');
const ITEM_ID = requireEnv('ITEM_ID');
const ROOM_ID = requireEnv('ROOM_ID');
const BID_DESTINATION = requireEnv('BID_DESTINATION');
const TOKENS = loadTokens();
const VUS = 20;
const wsBidBroadcast = new Trend('ws_bid_broadcast_ms', true);

const WS_URL = requireEnv('WS_URL');
const WS_HOST = (() => { try { return new URL(WS_URL).hostname; } catch (_) { return 'localhost'; } })();

const START_PRICE = 109; // startPrice(100) + increment(9)
// 20 个递增唯一价: 109, 118, ..., 280; max 唯一, 终价由最高有效出价决定。
const AMOUNTS = Array.from({ length: VUS }, (_, i) => START_PRICE + i * 9);
const EXPECTED_FINAL = Math.max(...AMOUNTS);

if (TOKENS.length < VUS) {
  throw new Error(`tokens.json 仅 ${TOKENS.length} 个用户, 本脚本需要 ${VUS} 个`);
}

export const options = {
  scenarios: {
    ws_bid: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: 1,
      maxDuration: '1m',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    ws_bid_broadcast_ms: ['p(95)<2000'],
  },
};

// STOMP 1.2 帧: COMMAND\nk:v\n...\n\nbody\x00
function stompFrame(cmd, headers, body) {
  let s = cmd + '\n';
  for (const [k, v] of Object.entries(headers || {})) {
    s += `${k}:${v}\n`;
  }
  s += '\n' + (body || '');
  return s + '\x00';
}

function parseStompFrame(raw) {
  const trimmed = String(raw).replace(/\x00$/, '');
  const idx = trimmed.indexOf('\n\n');
  let headerPart = trimmed;
  let body = '';
  if (idx >= 0) {
    headerPart = trimmed.slice(0, idx);
    body = trimmed.slice(idx + 2);
  }
  const lines = headerPart.split('\n');
  const headers = {};
  for (const line of lines.slice(1)) {
    const separator = line.indexOf(':');
    if (separator > 0) headers[line.slice(0, separator)] = line.slice(separator + 1);
  }
  return { cmd: lines[0] || '', headers, body };
}

export default function () {
  const index = __VU - 1;
  const t = TOKENS[index];
  const amount = AMOUNTS[index];
  let connected = false;
  let subscribed = false;
  let sentBid = false;
  let sentAt = 0;
  let gotBid = false;
  let buffer = '';
  const receiptId = `sub-${__VU}`;

  const res = ws.connect(WS_URL, {}, function (socket) {
    socket.on('open', () => {
      socket.send(stompFrame('CONNECT', {
        'accept-version': '1.2',
        'host': WS_HOST,
        'heart-beat': '10000,10000',
        'Authorization': `Bearer ${t.token}`,
      }));
    });

    socket.on('message', (data) => {
      buffer += data;
      // STOMP 帧以 \x00 结尾; 一次 WS message 可能含多帧或半帧, 按 \x00 切分并保留尾巴。
      const frames = buffer.split('\x00');
      buffer = frames.pop();
      for (const raw of frames) {
        const f = raw.trim();
        if (!f) continue;
        const parsed = parseStompFrame(f);
        if (!connected && parsed.cmd === 'CONNECTED') {
          connected = true;
          socket.send(stompFrame('SUBSCRIBE', {
            destination: `/topic/auction/${ROOM_ID}`,
            id: `sub-${__VU}`,
            ack: 'auto',
            receipt: receiptId,
          }));
        } else if (parsed.cmd === 'RECEIPT' && parsed.headers['receipt-id'] === receiptId) {
          subscribed = true;
          // 错峰出价: 按 VU 索引延迟 (index+1 避免setTimeout(0)), 保证递增到达 -> 终价 == max。
          socket.setTimeout(() => {
            const body = JSON.stringify({
              itemId: Number(ITEM_ID),
              userId: Number(t.userid),
              amount,
            });
            sentBid = true;
            sentAt = Date.now();
            socket.send(stompFrame('SEND', {
              destination: BID_DESTINATION,
              'content-type': 'application/json',
            }, body));
          }, (index + 1) * 50);
        } else if (parsed.cmd === 'MESSAGE') {
          // 调试: 记录每个 MESSAGE 帧的 body 片段, 用于排查广播格式。
          console.log(JSON.stringify({ vu: __VU, msg: (parsed.body || '').slice(0, 300) }));
          try {
            const msg = JSON.parse(parsed.body || '{}');
            const evt = msg.event || msg.type;
            if (sentBid && evt === 'BID' && String(msg.itemId) === String(ITEM_ID)) {
              gotBid = true;
              wsBidBroadcast.add(Date.now() - sentAt);
              socket.close();
            }
          } catch (_) { /* 非 JSON 帧忽略 */ }
        } else if (parsed.cmd === 'ERROR') {
          console.log(JSON.stringify({ vu: __VU, error: (parsed.body || '').slice(0, 300) }));
          socket.close();
        }
      }
    });

    socket.on('error', () => {});
    // 安全兜底: 5s 内未收到 BID 广播则关闭, 避免 VU 挂死。
    socket.setTimeout(() => { socket.close(); }, 5000);
  });

  check(res, {
    'WS 握手成功(101)': () => res.status === 101,
    'STOMP 已连接': () => connected,
    '订阅已确认': () => subscribed,
    '当前 VU 已发送出价': () => sentBid,
    '发送后收到 BID 广播': () => gotBid,
  });

  console.log(JSON.stringify({ vu: __VU, userid: t.userid, amount, connected, subscribed, sentBid, gotBid }));
}

export function teardown() {
  const detail = fetchDetail(BASE, ITEM_ID);
  const data = parseData(detail);
  const finalPrice = Number(data.currentPrice);

  check(detail, {
    '获取竞拍详情成功': () => detail.status === 200,
    '最终价格等于最高有效出价': () => finalPrice === EXPECTED_FINAL,
  });

  console.log(JSON.stringify({ finalPrice, expected: EXPECTED_FINAL }));
}
