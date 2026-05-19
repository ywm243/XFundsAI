<script setup>
const props = defineProps({
  insights: { type: Array, default: () => [] },
})

const emit = defineEmits(['quickQuery'])

const iconMap = {
  rate_chart: '\u{1F4C8}',         // chart with upward trend
  product_comparison: '\u{1F4CA}', // bar chart
  history: '\u{1F4DD}',            // memo
  market: '\u{1F4B1}',             // currency exchange
}
</script>

<template>
  <div v-if="insights.length" class="insight-list">
    <div v-for="(item, idx) in insights" :key="idx" class="insight-item">
      <span class="insight-icon">{{ iconMap[item.type] || '\u{1F4CB}' }}</span>
      <div class="insight-body">
        <div class="insight-title">{{ item.title }}</div>
        <div class="insight-detail">{{ item.detail || item.summary }}</div>
      </div>
      <button
        v-if="item.action"
        class="insight-action"
        @click="emit('quickQuery', item.action_params)"
      >
        {{ item.action_label || '查看' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.insight-list {
  margin-top: 12px;
}
.insight-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 6px;
}
.insight-icon {
  font-size: 16px;
  flex-shrink: 0;
  margin-top: 1px;
}
.insight-body {
  flex: 1;
  min-width: 0;
}
.insight-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.insight-detail {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.5;
}
.insight-action {
  flex-shrink: 0;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.insight-action:hover {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
</style>
