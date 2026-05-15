<script setup>
defineProps({
  insights: { type: Array, default: () => [] },
})

const emit = defineEmits(['click'])

const iconMap = {
  risk: '⚠️',
  growth: '📈',
  quality: '📋',
}

const colorMap = {
  risk: 'var(--warning)',
  growth: 'var(--success-text)',
  quality: '#60a5fa',
}
</script>

<template>
  <div v-if="insights.length > 0" class="insight-panel">
    <div class="insight-title">💡 数据分析与建议（点击可快捷查询）</div>
    <div
      v-for="(item, i) in insights" :key="i"
      class="insight-item"
      :class="{ clickable: !!item.query }"
      @click="item.query && emit('click', item.query)"
    >
      <span class="insight-icon" :style="{ color: colorMap[item.type] || colorMap.quality }">
        {{ iconMap[item.type] || '📋' }}
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
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: #1a2230;
}
.insight-title {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
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
  border-radius: 6px;
  padding: 4px 6px;
  margin-left: -6px;
  transition: background 0.15s;
}
.insight-item.clickable:hover {
  background: rgba(59,130,246,0.1);
}
.insight-icon { flex-shrink: 0; }
.insight-text { color: var(--text-secondary); }
</style>
