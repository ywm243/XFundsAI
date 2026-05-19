<script setup>
import { reactive, ref, onMounted } from 'vue'
import { NConfigProvider, zhCN, dateZhCN, NMessageProvider, NButton, darkTheme } from 'naive-ui'
import StatusHeader from './components/StatusHeader.vue'
import MessageArea from './components/MessageArea.vue'
import InputArea from './components/InputArea.vue'
import AdminRules from './views/AdminRules.vue'
import Sidebar from './components/Sidebar.vue'
import WelcomeGuide from './components/WelcomeGuide.vue'
import { checkHealth, parseQuery, executeQuery,
         createSession, listSessions, getSession, saveTurn,
         pricingInquiry, pricingConfirm, pricingRefresh, pricingCancel } from './api.js'

const connectionStatus = ref('checking')
const messages = reactive([])
const inputAreaRef = ref(null)
const viewMode = ref('chat')  // 'chat' | 'admin'
const sessionId = ref('')
const sessions = ref([])

onMounted(async () => {
  try {
    await checkHealth()
    connectionStatus.value = 'connected'
  } catch {
    connectionStatus.value = 'disconnected'
  }
  // Create new session + load history list
  try {
    const r = await createSession()
    sessionId.value = r.session_id
  } catch { /* non-blocking */ }
  try {
    sessions.value = await listSessions()
  } catch { /* non-blocking */ }
})

async function refreshSessions() {
  try { sessions.value = await listSessions() } catch { /* */ }
}

async function handleNewChat() {
  messages.length = 0
  try {
    const r = await createSession()
    sessionId.value = r.session_id
    await refreshSessions()
  } catch { /* */ }
}

async function handleLoadSession(sid) {
  const session = await getSession(sid)
  if (!session || !session.turns) return
  messages.length = 0
  sessionId.value = sid
  for (const turn of session.turns) {
    messages.push({ type: 'user', text: turn.user_query })
    if (turn.result_summary) {
      try {
        const data = JSON.parse(turn.result_summary)
        messages.push({ type: 'bot', mode: 'result_card', data })
      } catch {
        messages.push({ type: 'bot', mode: 'text', text: turn.result_summary })
      }
    } else {
      messages.push({ type: 'bot', mode: 'text', text: '(无结果数据)' })
    }
  }
}

async function _persistTurn(userText, parsedParams, sql, summaryData) {
  if (!sessionId.value) return
  try {
    await saveTurn(sessionId.value, userText, parsedParams, sql,
                   summaryData ? JSON.stringify(summaryData) : null)
    await refreshSessions()
  } catch { /* non-blocking */ }
}

function getLastResultData() {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.mode === 'result_card' && m.data) {
      return {
        columns: m.data.columns,
        rows: m.data.rows?.slice(0, 10),
        row_count: m.data.row_count,
        comparison: m.data.comparison,
        params: m.data.params,
        sql: m.data.sql,
      }
    }
  }
  return null
}

function buildContext() {
  // Get last user query + its parsed result for multi-turn context
  const recent = []
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.type === 'user') {
      recent.unshift({ role: 'user', content: m.text })
    } else if (m.mode === 'result_card' && m.data?.params) {
      recent.push({ role: 'assistant', content: JSON.stringify(m.data.params) })
    }
    if (recent.length >= 2) break
  }
  return recent.length > 0 ? recent : null
}

async function handleSend(text) {
  messages.push({ type: 'user', text })
  const botIdx = messages.length
  messages.push({ type: 'bot', mode: 'loading' })
  inputAreaRef.value?.focus()

  // 检测询报价意图
  const pricingKeywords = ['询价', '报价', '结汇', '购汇', '成交', '点差', '比价', '价格']
  const isPricing = pricingKeywords.some(kw => text.includes(kw))

  if (isPricing) {
    messages[botIdx] = { type: 'bot', mode: 'loading' }
    try {
      const context = buildContext()
      const result = await pricingInquiry(text, {}, {
        sessionId: sessionId.value,
        context,
      })
      // Merge insights if available
      if (result.insights && result.insights.length > 0) {
        result.insights = result.insights
      }
      messages[botIdx] = { type: 'bot', mode: result.mode || 'pricing_single', data: result }
    } catch (err) {
      messages[botIdx] = { type: 'bot', mode: 'error', error: err.message }
    }
    _persistTurn()
    return
  }

  // Check if this is an analytical question (为什么/原因/分析)
  const isAnalytical = /为什么|原因|分析|怎么回事|解释/.test(text)

  try {
    if (isAnalytical && messages.length > 1) {
      // Analytical question → use mode=analyze pipeline
      const context = buildContext()
      const resp = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, context, mode: 'analyze' }),
      })
      if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error || `HTTP ${resp.status}`)
      const result = await resp.json()
      if (result.error) {
        messages[botIdx] = { type: 'bot', mode: 'error', error: result.error }
        return
      }
      messages[botIdx] = {
        type: 'bot',
        mode: 'result_card',
        data: {
          columns: result.columns || [],
          rows: result.rows || [],
          row_count: result.row_count || 0,
          sql: result.sql || '',
          comparison_sql: result.comparison_sql || null,
          params: result.params || {},
          summary: result.summary || '',
          chartOption: result.chartOption || null,
          insights: result.insights || [],
          comparison: result.comparison || null,
          analysis_data: result.analysis_data || null,
          mode: 'analyze',
        },
      }
      _persistTurn(text, result.params, result.sql, {
        columns: result.columns || [],
        rows: result.rows || [],
        row_count: result.row_count || 0,
        sql: result.sql || '',
        comparison_sql: result.comparison_sql || null,
        params: result.params || {},
        summary: result.summary || '',
        chartOption: result.chartOption || null,
        insights: result.insights || [],
        comparison: result.comparison || null,
        analysis_data: result.analysis_data || null,
        mode: 'analyze',
      })
    } else {
      // Data query → parse → execute
      const context = buildContext()
      const parseResult = await parseQuery(text, context)
      if (parseResult.error) {
        messages[botIdx] = { type: 'bot', mode: 'error', error: parseResult.error }
        return
      }
      // 直接执行查询
      const result = await executeQuery(parseResult.params, context)
      if (result.error) {
        messages[botIdx] = { type: 'bot', mode: 'error', error: result.error }
        return
      }
      // 同比/环比需要用户确认日期
      if (result.confirm_date) {
        messages[botIdx] = {
          type: 'bot',
          mode: 'confirm',
          params: result.params,
          pipeline: parseResult.pipeline,
        }
        return
      }
      messages[botIdx] = {
        type: 'bot',
        mode: 'result_card',
        data: {
          columns: result.columns,
          rows: result.rows,
          row_count: result.row_count,
          sql: result.sql,
          comparison_sql: result.comparison_sql,
          params: result.params,
          comparison: result.comparison,
          summary: result.summary,
          chartOption: result.chartOption,
          insights: result.insights,
        },
      }
      _persistTurn(text, parseResult.params, result.sql, {
        columns: result.columns,
        rows: result.rows,
        row_count: result.row_count,
        sql: result.sql,
        comparison_sql: result.comparison_sql,
        params: result.params,
        comparison: result.comparison,
        summary: result.summary,
        chartOption: result.chartOption,
        insights: result.insights,
      })
    }

    // --- 原确认环节（注释掉）---
    // messages[botIdx] = {
    //   type: 'bot',
    //   mode: 'confirm',
    //   params: parseResult.params,
    //   pipeline: parseResult.pipeline,
    //   originalText: text,
    //   querying: false,
    //   resetting: false,
    // }
  } catch (err) {
    messages[botIdx] = { type: 'bot', mode: 'error', error: err.message || String(err) }
  }
}

async function handleConfirm(params, msgIdx) {
  const msg = messages[msgIdx]
  if (!msg || msg.mode !== 'confirm') return

  messages[msgIdx] = { ...msg, querying: true }

  try {
    const result = await executeQuery(params)
    if (result.error) {
      messages[msgIdx] = { type: 'bot', mode: 'error', error: result.error }
      return
    }
    messages[msgIdx] = {
      type: 'bot',
      mode: 'result',
      data: {
        columns: result.columns,
        rows: result.rows,
        row_count: result.row_count,
        sql: result.sql,
        comparison_sql: result.comparison_sql,
        params: result.params,
        comparison: result.comparison,
        summary: result.summary,
        chartOption: result.chartOption,
        insights: result.insights,
      },
    }
  } catch (err) {
    messages[msgIdx] = { type: 'bot', mode: 'error', error: err.message || String(err) }
  }
}

async function handleReset(msgIdx) {
  const msg = messages[msgIdx]
  if (!msg || msg.mode !== 'confirm') return

  messages[msgIdx] = { ...msg, resetting: true }

  try {
    const parseResult = await parseQuery(msg.originalText)
    if (parseResult.error) {
      messages[msgIdx] = { type: 'bot', mode: 'error', error: parseResult.error }
      return
    }
    messages[msgIdx] = {
      type: 'bot',
      mode: 'confirm',
      params: parseResult.params,
      pipeline: parseResult.pipeline,
      originalText: msg.originalText,
      querying: false,
      resetting: false,
    }
  } catch (err) {
    messages[msgIdx] = { type: 'bot', mode: 'error', error: err.message || String(err) }
  }
}

async function handlePricingConfirm(pricingId) {
  const idx = messages.findIndex(m => m.type === 'bot' && m.data?.pricing_id === pricingId)
  if (idx < 0) return
  messages[idx] = { ...messages[idx], mode: 'loading' }
  try {
    const result = await pricingConfirm(pricingId, { sessionId: sessionId.value })
    messages[idx] = { type: 'bot', mode: result.mode, data: result.data || result }
  } catch (err) {
    messages[idx] = { type: 'bot', mode: 'error', error: err.message }
  }
}

async function handlePricingRefresh(pricingId) {
  const idx = messages.findIndex(m => m.type === 'bot' && m.data?.pricing_id === pricingId)
  if (idx < 0) return
  messages[idx] = { ...messages[idx], mode: 'loading' }
  try {
    const result = await pricingRefresh(pricingId)
    messages[idx] = { type: 'bot', mode: result.mode, data: result }
  } catch (err) {
    messages[idx] = { type: 'bot', mode: 'error', error: err.message }
  }
}

async function handlePricingCancel(pricingId) {
  const idx = messages.findIndex(m => m.type === 'bot' && m.data?.pricing_id === pricingId)
  if (idx < 0) return
  try {
    await pricingCancel(pricingId)
    messages[idx] = { type: 'bot', mode: 'text', text: '报价已取消' }
  } catch (err) {
    messages[idx] = { type: 'bot', mode: 'error', error: err.message }
  }
}

function handleNavigate(target) {
  if (target === 'admin') viewMode.value = 'admin'
}
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme="darkTheme">
    <NMessageProvider>
      <div style="display: flex; height: 100vh;">
        <Sidebar @navigate="handleNavigate" :sessions="sessions"
                 @new-chat="handleNewChat" @load-session="handleLoadSession"
                 :active-session="sessionId" />
        <div style="flex: 1; display: flex; flex-direction: column; min-width: 0;">
          <template v-if="viewMode === 'admin'">
            <div style="padding: 8px 16px; border-bottom: 1px solid var(--border); background: var(--bg-sidebar);">
              <NButton size="tiny" @click="viewMode = 'chat'">← 返回</NButton>
            </div>
            <AdminRules />
          </template>
          <template v-else>
            <StatusHeader :status="connectionStatus" />
            <div style="flex: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; padding: 0 16px;">
              <WelcomeGuide v-if="messages.length === 0" @quick-query="handleSend" />
              <MessageArea v-else :messages="messages" @confirm="handleConfirm" @reset="handleReset" @quick-query="handleSend" @pricing-confirm="handlePricingConfirm" @pricing-cancel="handlePricingCancel" @pricing-refresh="handlePricingRefresh" />
              <InputArea ref="inputAreaRef" @send="handleSend" />
            </div>
          </template>
        </div>
      </div>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }
#app { height: 100%; }

:root {
  --bg-primary: #0f172a;
  --bg-card: #1e293b;
  --bg-sidebar: #0b1120;
  --border: #334155;
  --accent: #1d4ed8;
  --success: #22c55e;
  --success-text: #34d399;
  --warning: #f59e0b;
  --error: #ef4444;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
}
</style>
