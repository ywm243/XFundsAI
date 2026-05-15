<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeSession: { type: String, default: '' },
})

const emit = defineEmits(['navigate', 'newChat', 'loadSession'])
const expanded = ref(false)
const activeAgent = ref('bi')

const agents = [
  { key: 'bi', icon: '💬', label: 'BI Agent', active: true },
  { key: 'quoting', icon: '📊', label: '询报价 Agent', active: false },
  { key: 'risk', icon: '⚠️', label: '风控 Agent', active: false },
]

const sortedSessions = computed(() => {
  return [...props.sessions].sort((a, b) => {
    // Current session first
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
}

function handleNewChat() {
  expanded.value = false
  emit('newChat')
}

function handleSelectSession(sid) {
  expanded.value = false
  emit('loadSession', sid)
}

function handleAdminClick() {
  emit('navigate', 'admin')
}
</script>

<template>
  <div class="sidebar" :class="{ expanded }">
    <div class="sidebar-logo" @click="handleNewChat" title="新查询">◆</div>

    <div
      v-for="agent in agents" :key="agent.key"
      class="sidebar-icon"
      :class="{ active: activeAgent === agent.key, disabled: !agent.active }"
      :title="agent.label"
      @click="handleAgentClick(agent)"
    >
      {{ agent.icon }}
    </div>

    <div class="sidebar-spacer"></div>

    <div class="sidebar-icon" title="查询历史" @click="handleHistoryClick">
      🕐
    </div>

    <div class="sidebar-icon" title="规则管理" @click="handleAdminClick">
      ⚙
    </div>

    <div v-if="expanded" class="sidebar-panel">
      <div class="sidebar-panel-header">
        <span class="sidebar-panel-title">查询历史</span>
        <span class="sidebar-new-btn" @click="handleNewChat">+ 新查询</span>
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
          <div class="session-meta">{{ s.turn_count }}轮 · {{ (s.updated_at || '').slice(5, 16) }}</div>
        </div>
      </div>
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
  padding: 12px 0;
  gap: 4px;
  position: relative;
  transition: width 0.2s;
  flex-shrink: 0;
}
.sidebar.expanded { width: 220px; }

.sidebar-logo {
  font-size: 20px;
  margin-bottom: 16px;
  opacity: 0.8;
  cursor: pointer;
}
.sidebar-logo:hover { opacity: 1; }

.sidebar-icon {
  padding: 8px;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.15s;
}
.sidebar-icon:hover { background: #1e293b; }
.sidebar-icon.active { background: var(--accent); color: #fff; }
.sidebar-icon.disabled { opacity: 0.35; cursor: not-allowed; }

.sidebar-spacer { flex: 1; }

.sidebar-panel {
  position: absolute;
  left: 100%;
  top: 0;
  bottom: 0;
  width: 220px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  padding: 16px;
  z-index: 10;
  display: flex;
  flex-direction: column;
}
.sidebar-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.sidebar-panel-title {
  font-size: 12px;
  color: var(--text-muted);
}
.sidebar-new-btn {
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
}
.sidebar-new-btn:hover { text-decoration: underline; }
.sidebar-panel-empty {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px 0;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.session-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.session-item:hover { background: #1e293b; }
.session-item.current { background: #1e3a5f; }
.session-title {
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-meta {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}
</style>
