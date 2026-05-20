export async function checkHealth() {
  const resp = await fetch('/api/health', { signal: AbortSignal.timeout(5000) })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = await resp.json()
  if (data.status !== 'ok') throw new Error('Unexpected response')
  return data
}

export async function parseQuery(text, context) {
  const body = { text }
  if (context) body.context = context
  const resp = await fetch('/api/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.error || `HTTP ${resp.status}`)
  }
  return resp.json()
}

export async function executeQuery(params, context, mode) {
  const body = { params }
  if (context) body.context = context
  if (mode) body.mode = mode
  const resp = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.error || `HTTP ${resp.status}`)
  }
  return resp.json()
}

// ---- Session / History ----

export async function createSession() {
  const resp = await fetch('/api/sessions', { method: 'POST' })
  return resp.json()
}

export async function listSessions() {
  const resp = await fetch('/api/sessions')
  if (!resp.ok) return []
  return resp.json()
}

export async function getSession(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}`)
  if (!resp.ok) return null
  return resp.json()
}

export async function saveTurn(sessionId, userQuery, parsedParams, executedSql, resultSummary) {
  const resp = await fetch(`/api/sessions/${sessionId}/turns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_query: userQuery,
      parsed_params: parsedParams,
      executed_sql: executedSql,
      result_summary: resultSummary,
    }),
  })
  return resp.json()
}

export async function deleteSession(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
  return resp.json()
}

// ---- Audit Log ----

export async function getAuditLog(sessionId = '', limit = 50) {
  const params = new URLSearchParams()
  if (sessionId) params.set('session_id', sessionId)
  params.set('limit', limit)
  const resp = await fetch(`/api/audit-log?${params}`)
  if (!resp.ok) return []
  return resp.json()
}

// ---- 询报价相关 ----

export async function pricingInquiry(text, intent, options = {}) {
  const body = {
    text,
    intent: intent || {},
    session_id: options.sessionId || '',
    customer_id: options.customerId || '',
    customer_info: options.customerInfo || null,
    context: options.context || null,
  }
  const resp = await fetch('/api/pricing/inquiry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `询价失败 (${resp.status})`)
  }
  return resp.json()
}

export async function pricingConfirm(pricingId, options = {}) {
  const body = {
    pricing_id: pricingId,
    session_id: options.sessionId || '',
    customer_id: options.customerId || '',
    customer_info: options.customerInfo || null,
  }
  const resp = await fetch('/api/pricing/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `下单失败 (${resp.status})`)
  }
  return resp.json()
}

export async function pricingRefresh(pricingId) {
  const resp = await fetch('/api/pricing/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pricing_id: pricingId }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `刷新失败 (${resp.status})`)
  }
  return resp.json()
}

export async function pricingCancel(pricingId) {
  const resp = await fetch('/api/pricing/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pricing_id: pricingId }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `取消失败 (${resp.status})`)
  }
  return resp.json()
}

// Wiki knowledge base
export const wikiSearch = (keyword) =>
  fetch(`${API_BASE}/wiki/search?keyword=${encodeURIComponent(keyword)}&limit=10`).then(r => r.json())

export const wikiGetPage = (slug) =>
  fetch(`${API_BASE}/wiki/pages/${encodeURIComponent(slug)}`).then(r => r.json())

export const wikiGetByTag = (tag) =>
  fetch(`${API_BASE}/wiki/by-tag/${encodeURIComponent(tag)}?limit=20`).then(r => r.json())

export const wikiGetCustomer = (customerId) =>
  fetch(`${API_BASE}/wiki/customer/${encodeURIComponent(customerId)}`).then(r => r.json())

export const wikiCompile = () =>
  fetch(`${API_BASE}/wiki/compile`, { method: 'POST' }).then(r => r.json())
