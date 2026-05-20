<script setup>
import { ref, computed } from 'vue'
import { getAuditLog } from '../api.js'
import WikiPanel from './WikiPanel.vue'
import {
  Diamond, MessageSquare, TrendingUp, Shield,
  History, ClipboardList, BookOpen, Settings, Plus, Clock
} from 'lucide-vue-next'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeSession: { type: String, default: '' },
})

const emit = defineEmits(['navigate', 'newChat', 'loadSession'])
const expanded = ref(false)
const auditExpanded = ref(false)
const wikiExpanded = ref(false)
const auditLogs = ref([])
const activeAgent = ref('bi')

const agents = [
  { key: 'bi', component: MessageSquare, label: 'BI 智能分析', active: true },
  { key: 'quoting', component: TrendingUp, label: '询报价', active: false },
  { key: 'risk', component: Shield, label: '风控', active: false },
]

const sortedSessions = computed(() => {
  return [...props.sessions].sort((a, b) => {
    if (a.id === props.activeSession) return -1
    if (b.id === props.activeSession) return 1
    return (b.updated_at || '').localeCompare(a.updated_at || '')
  })
})

function handleAgentClick(agent) {
  if (!agent.active) return
  activeAgent.value = agent.key
}

function handleHistoryClick() {
  expanded.value = !expanded.value
  if (expanded.value) { auditExpanded.value = false; wikiExpanded.value = false }
}

async function handleAuditClick() {
  auditExpanded.value = !auditExpanded.value
  if (auditExpanded.value) {
    expanded.value = false; wikiExpanded.value = false
    try {
      auditLogs.value = await getAuditLog('', 30)
    } catch { auditLogs.value = [] }
  }
}

function handleWikiClick() {
  wikiExpanded.value = !wikiExpanded.value
  if (wikiExpanded.value) { expanded.value = false; auditExpanded.value = false }
}

function handleNewChat() {
  expanded.value = false
  auditExpanded.value = false
  wikiExpanded.value = false
  emit('newChat')
}

function handleSelectSession(sid) {
  expanded.value = false
  emit('loadSession', sid)
}

function handleAdminClick() {
  emit('navigate', 'admin')
}

function formatTime(ts) {
  if (!ts) return ''
  return ts.slice(5, 16).replace('T', ' ')
}
</script>

<template>
  <div class="sidebar" :class="{ expanded }">
    <div class="sidebar-logo" @click="handleNewChat" title="新查询">
      <Diamond :size="22" class="logo-icon" />
    </div>

    <div class="agent-group">
      <div
        v-for="agent in agents" :key="agent.key"
        class="sidebar-icon"
        :class="{ active: activeAgent === agent.key, disabled: !agent.active }"
        :title="agent.label"
        @click="handleAgentClick(agent)"
      >
        <component :is="agent.component" :size="18" />
        <span class="icon-label">{{ agent.label }}</span>
      </div>
    </div>

    <div class="sidebar-divider"></div>

    <div class="sidebar-icon" title="查询历史" @click="handleHistoryClick">
      <History :size="18" />
    </div>

    <div class="sidebar-icon" title="审计日志" @click="handleAuditClick">
      <ClipboardList :size="18" />
    </div>

    <div class="sidebar-icon" title="知识库" @click="handleWikiClick">
      <BookOpen :size="18" />
    </div>

    <div class="sidebar-icon" title="规则管理" @click="handleAdminClick">
      <Settings :size="18" />
    </div>

    <div v-if="expanded" class="sidebar-panel">
      <div class="sidebar-panel-header">
        <span class="sidebar-panel-title">查询历史</span>
        <span class="sidebar-new-btn" @click="handleNewChat">
          <Plus :size="13" /> 新查询
        </span>
      </div>
      <div v-if="sortedSessions.length === 0" class="sidebar-panel-empty">
        暂无历史记录
      </div>
      <div v-else class="session-list">
        <div
          v-for="s in sortedSessions" :key="s.id"
          class="session-item"
          :class="{ current: s.id === activeSession }"
          @click="handleSelectSession(s.id)"
        >
          <div class="session-title">{{ s.first_query || '(空会话)' }}</div>
          <div class="session-meta">
            <Clock :size="10" />
            {{ s.turn_count || 0 }}轮 · {{ (s.updated_at || '').slice(5, 16) }}
          </div>
        </div>
      </div>
    </div>

    <div v-if="auditExpanded" class="sidebar-panel">
      <div class="sidebar-panel-header">
        <span class="sidebar-panel-title">审计日志</span>
      </div>
      <div v-if="auditLogs.length === 0" class="sidebar-panel-empty">
        暂无审计记录
      </div>
      <div v-else class="session-list">
        <div
          v-for="log in auditLogs" :key="log.id"
          class="session-item"
        >
          <div class="session-title">{{ log.raw_input || '(空)' }}</div>
          <div class="session-meta">{{ log.result_rows || 0 }}行 · {{ formatTime(log.created_at) }}</div>
        </div>
      </div>
    </div>

    <div v-if="wikiExpanded" class="sidebar-panel">
      <div class="sidebar-panel-header">
        <span class="sidebar-panel-title">知识库</span>
      </div>
      <WikiPanel />
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 56px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 8px;
  gap: 2px;
  position: relative;
  transition: width 0.2s ease;
  flex-shrink: 0;
  z-index: 10;
}
.sidebar.expanded { width: 232px; }

.sidebar-logo {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
  cursor: pointer;
  color: var(--accent);
  transition: all 0.2s ease;
}
.sidebar-logo:hover { color: var(--accent-hover); transform: scale(1.08); }
.logo-icon { filter: drop-shadow(0 0 6px rgba(200,141,10,0.3)); }

.agent-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
}

.sidebar-divider {
  width: 24px;
  height: 1px;
  background: var(--border);
  margin: 8px 0;
  flex-shrink: 0;
}

.sidebar-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-muted);
  transition: all 0.18s ease;
  position: relative;
}
.sidebar-icon:hover { background: var(--bg-hover); color: var(--text-secondary); }
.sidebar-icon.active { background: var(--accent-dim); color: var(--accent); }
.sidebar-icon.disabled { opacity: 0.3; cursor: not-allowed; }
.sidebar-icon.disabled:hover { background: transparent; color: var(--text-muted); }
.icon-label { display: none; }

.sidebar-panel {
  position: absolute;
  left: 100%;
  top: 0;
  bottom: 0;
  width: 232px;
  background: var(--bg-primary);
  border-right: 1px solid var(--border);
  padding: 16px;
  z-index: 20;
  display: flex;
  flex-direction: column;
  animation: panelSlideIn 0.18s ease;
}
@keyframes panelSlideIn {
  from { opacity: 0; transform: translateX(-8px); }
  to   { opacity: 1; transform: translateX(0); }
}

.sidebar-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.sidebar-panel-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.sidebar-new-btn {
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 3px;
}
.sidebar-new-btn:hover { color: var(--accent-hover); }

.sidebar-panel-empty {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 24px 0;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.session-item {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}
.session-item:hover { background: var(--bg-hover); }
.session-item.current {
  background: var(--bg-elevated);
  border-color: var(--border-light);
}

.session-title {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 3px;
}
.session-meta {
  font-size: 10px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
