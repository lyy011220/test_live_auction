import { Counter, Rate, Trend } from 'k6/metrics';

// 创建性能指标对象
export function createPerformanceMetrics(prefix) {
  if (!/^[a-z][a-z0-9_]*$/.test(prefix)) {
    throw new Error(`invalid performance metric prefix: ${prefix}`);
  }
  //  Object.freeze 冻结对象，不可变，防止外部修改
  return Object.freeze({
    requests: new Counter(`${prefix}_requests`),
    successRate: new Rate(`${prefix}_success_rate`),
    technicalFailureRate: new Rate(
      `${prefix}_technical_failure_rate`
    ),
    clientErrors: new Counter(`${prefix}_4xx`),
    serverErrors: new Counter(`${prefix}_5xx`),
    networkErrors: new Counter(`${prefix}_network_errors`),
    successDuration: new Trend(`${prefix}_success_duration`, true),
  });
}


export function parseJsonSafely(response) {
  try {
    return {
      body: response.json(),
      parseFailed: false,
    };
  } catch (_) {
    return {
      body: null,
      parseFailed: true,
    };
  }
}


export function recordPerformanceResult(
  metrics,
  response,
  { businessSuccess, parseFailed = false }
) {
  const networkError = response.status === 0;
  const is4xx = response.status >= 400 && response.status < 500;
  const is5xx = response.status >= 500;
  const technicalFailure = networkError || is5xx || parseFailed;
  const success = Boolean(businessSuccess) && !technicalFailure;

  metrics.requests.add(1);
  metrics.successRate.add(success);
  metrics.technicalFailureRate.add(technicalFailure);

  if (is4xx) {
    metrics.clientErrors.add(1);
  }

  if (is5xx) {
    metrics.serverErrors.add(1);
  }

  if (networkError) {
    metrics.networkErrors.add(1);
  }

  if (success) {
    metrics.successDuration.add(response.timings.duration);
  }

  return {
    success,
    technicalFailure,
    networkError,
    is4xx,
    is5xx,
  };
}
