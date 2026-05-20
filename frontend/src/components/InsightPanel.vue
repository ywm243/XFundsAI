<script setup>
import { AlertTriangle, TrendingUp, FileText, Lightbulb } from 'lucide-vue-next'

defineProps({
  insights: { type: Array, default: () => [] },
})

const emit = defineEmits(['click'])

const iconMap = {
  risk: AlertTriangle,
  growth: TrendingUp,
  quality: FileText,
}

const colorMap = {
  risk: 'var(--warning)',
  growth: 'var(--success-text)',
  quality: 'var(--info)',
}
</script>

<template>
  <div v-if="insights.length > 0" class="insight-panel">
    <div class="insight-title"><Lightbulb :size="12" /> 数据分析与建议（点击可快捷查询）</div>
    <div
      v-for="(item, i) in insights" :key="i"
      class="insight-item"
      :class="{ clickable: !!item.query }"
      @click="item.query && emit('click', item.query)"
    >
      <span class="insight-icon" :style="{ color: colorMap[item.type] || colorMap.quality }">
        <component :is="iconMap[item.type] || FileText" :size="13" />
      </span>
      <span class="insight-text">
        <strong :style="{ color: colorMap[item.type] || colorMap.quality }">{{ item.title }}：</strong>
        {{ item.detail }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.insight-panel {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
}
.insight-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.insight-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 6px;
}
.insight-item.clickable {
  cursor: pointer;
  border-radius: var(--radius-md);
  padding: 4px 8px;
  margin-left: -8px;
  transition: background 0.15s;
}
.insight-item.clickable:hover {
  background: rgba(99,102,241,0.08);
}
.insight-icon { flex-shrink: 0; margin-top: 1px; }
.insight-text { color: var(--text-secondary); }
</style>
