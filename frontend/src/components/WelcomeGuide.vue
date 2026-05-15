<script setup>
const emit = defineEmits(['quickQuery'])

const quickExamples = [
  { label: '📊 本月交易量', text: '本月交易量' },
  { label: '🏆 各银行排名', text: '各银行交易量排名' },
  { label: '📈 套保率分析', text: '套保率排名' },
  { label: '📅 一季度趋势', text: '今年一季度每月交易量趋势' },
  { label: '🔄 同比对比', text: '本月交易量同比' },
  { label: '👤 客户维度', text: '各客户交易量统计' },
]
</script>

<template>
  <div class="welcome">
    <div class="welcome-icon">💬</div>
    <div class="welcome-title">今天想了解什么？</div>
    <div class="welcome-subtitle">输入中文查询，AI 自动解析并返回结果</div>
    <div class="welcome-chips">
      <span
        v-for="ex in quickExamples" :key="ex.text"
        class="welcome-chip"
        @click="emit('quickQuery', ex.text)"
      >
        {{ ex.label }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 32px;
}
.welcome-icon { font-size: 32px; margin-bottom: 8px; }
.welcome-title { font-size: 18px; font-weight: 600; margin-bottom: 4px; }
.welcome-subtitle { font-size: 12px; color: var(--text-secondary); margin-bottom: 20px; }
.welcome-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  max-width: 500px;
}
.welcome-chip {
  background: var(--bg-card);
  color: #93c5fd;
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}
.welcome-chip:hover { background: #1e3a5f; }
</style>
