import http from 'k6/http';
import {
  createPerformanceMetrics,
  parseJsonSafely,
  recordPerformanceResult,
} from '../../../load/k6/lib/performance_metrics.js';

const probeMetrics = createPerformanceMetrics('probe');

export const options = {
  vus: 1,
  iterations: 1,
  summaryTrendStats: ['avg', 'p(95)', 'p(99)'],
};

export default function () {
  const response = http.get(__ENV.URL);
  const parsed = parseJsonSafely(response);
  const businessSuccess = response.status === 200
    && !parsed.parseFailed
    && Number(parsed.body.code) === 200;

  recordPerformanceResult(probeMetrics, response, {
    businessSuccess,
    parseFailed: parsed.parseFailed,
  });
}
