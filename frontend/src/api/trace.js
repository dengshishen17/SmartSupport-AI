import http from './http'

/**
 * Trace 观测接口（Python 双栈 FastAPI 8001）。
 *
 * 对应后端：
 *   GET /py/ops/traces                最近 trace 列表
 *   GET /py/ops/trace/{traceId}       单次请求的完整 span 调用链
 *   GET /py/ops/slow-spans            慢 span 排行
 *   GET /py/ops/trace-stats           按 span 类型聚合的耗时画像
 *   GET /py/ops/stats                 调用量 / 成功率 / 延迟分位 / Token
 */

/** 最近 trace 列表 */
export async function fetchTraces(limit = 20) {
  const res = await http.get(`/py/ops/traces?limit=${limit}`)
  return unwrap(res)
}

/**
 * 拆出业务数据。
 *
 * http.js 的响应拦截器已经返回 body.data，但这里再兜一层：
 * 不同接口的 data 可能是数组、也可能是 {key: [...]}，
 * 统一成 {list: [...]}，避免调用方各自判断形状。
 */
function unwrap(res) {
  if (Array.isArray(res)) return { list: res }
  if (res && Array.isArray(res.traces)) return { list: res.traces }
  if (res && Array.isArray(res.spans)) return { list: res.spans }
  if (res && Array.isArray(res.items)) return { list: res.items }
  return { list: [] }
}

/** 单次请求的完整 span 调用链 */
export async function fetchTrace(traceId) {
  const res = await http.get(`/py/ops/trace/${traceId}`)
  return { spans: unwrap(res).list }
}

/** 慢 span 排行 */
export async function fetchSlowSpans(thresholdMs = 500, limit = 20) {
  const res = await http.get(`/py/ops/slow-spans?thresholdMs=${thresholdMs}&limit=${limit}`)
  return { list: unwrap(res).list }
}

/** 按 span 类型聚合的耗时画像 */
export async function fetchTraceStats() {
  const res = await http.get('/py/ops/trace-stats')
  if (res && res.stats && typeof res.stats === 'object') return res.stats
  if (res && typeof res === 'object' && !Array.isArray(res)) {
    // 直接就是 {spanType: {...}} 的形状
    const keys = Object.keys(res)
    if (keys.length && typeof res[keys[0]] === 'object') return res
  }
  return {}
}

/** 调用量 / 成功率 / 延迟分位 / Token 汇总 */
export function fetchOpsStats() {
  return http.get('/py/ops/stats')
}
