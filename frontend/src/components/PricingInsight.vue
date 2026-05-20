<script setup>
import { TrendingUp, BarChart3, Pencil, Banknote } from 'lucide-vue-next'

const props = defineProps({
  insights: { type: Array, default: () => [] },
})

const emit = defineEmits(['quickQuery'])

const iconMap = {
  rate_chart: TrendingUp,
  product_comparison: BarChart3,
  history: Pencil,
  market: Banknote,
}
</script>

<template>
  <div v-if="insights.length" class="insight-list">
    <div v-for="(item, idx) in insights" :key="idx" class="insight-item">
      <span class="insight-icon">
        <component :is="iconMap[item.type] || BarChart3" :size="16" />
      </span>
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
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: 6px;
}
.insight-icon {
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--text-muted);
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
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  transition: all 0.15s ease;
}
.insight-action:hover {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent-hover);
}
</style>
