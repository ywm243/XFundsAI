<script setup>
import { NTag, NSpace } from 'naive-ui'
import { Diamond } from 'lucide-vue-next'

defineProps({
  status: { type: String, default: 'checking' },
})
</script>

<template>
  <header class="status-header">
    <div class="brand">
      <Diamond :size="18" class="brand-icon" />
      <span class="brand-text">XFundsAI</span>
      <span class="brand-sub">代客交易智能平台</span>
    </div>
    <NSpace align="center" :size="6">
      <NTag
        :type="status === 'connected' ? 'success' : status === 'checking' ? 'warning' : 'error'"
        :bordered="false"
        size="small"
        round
      >
        {{ status === 'connected' ? '已连接' : status === 'checking' ? '检查连接...' : '无法连接到服务器' }}
      </NTag>
    </NSpace>
  </header>
</template>

<style scoped>
.status-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-sidebar);
  flex-shrink: 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-icon {
  color: var(--accent);
  filter: drop-shadow(0 0 5px rgba(200,141,10,0.25));
}
.brand-text {
  font-family: var(--font-sans);
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}
.brand-sub {
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 400;
  padding-left: 10px;
  border-left: 1px solid var(--border);
}
</style>
