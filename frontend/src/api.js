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

export async function executeQuery(params) {
  const resp = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
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
