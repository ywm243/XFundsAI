<script setup>
import { BarChart3, TrendingUp, ShieldCheck, Calendar, ArrowLeftRight, Users } from 'lucide-vue-next'

const emit = defineEmits(['quickQuery'])

const quickExamples = [
  { icon: BarChart3, label: '本月交易量', text: '本月交易量' },
  { icon: TrendingUp, label: '各银行排名', text: '各银行交易量排名' },
  { icon: ShieldCheck, label: '套保率分析', text: '套保率排名' },
  { icon: Calendar, label: '一季度趋势', text: '今年一季度每月交易量趋势' },
  { icon: ArrowLeftRight, label: '同比对比', text: '本月交易量同比' },
  { icon: Users, label: '客户维度', text: '各客户交易量统计' },
]
</script>

<template>
  <div class="welcome">
    <div class="welcome-brand">
      <div class="welcome-diamond">&#9670;</div>
      <div class="welcome-title">XFundsAI</div>
      <div class="welcome-subtitle">输入中文查询，AI 自动解析并返回结果</div>
    </div>
    <div class="welcome-chips">
      <span
        v-for="ex in quickExamples" :key="ex.text"
        class="welcome-chip"
        @click="emit('quickQuery', ex.text)"
      >
        <component :is="ex.icon" :size="14" />
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
  padding: 40px 32px;
  gap: 32px;
}
.welcome-brand {
  text-align: center;
}
.welcome-diamond {
  font-size: 28px;
  color: var(--accent);
  margin-bottom: 12px;
  filter: drop-shadow(0 0 12px rgba(200,141,10,0.3));
}
.welcome-title {
  font-family: var(--font-sans);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  margin-bottom: 4px;
}
.welcome-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
}
.welcome-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  max-width: 520px;
}
.welcome-chip {
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  padding: 8px 14px;
  border-radius: 20px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.18s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.welcome-chip:hover {
  background: var(--bg-elevated);
  border-color: var(--accent-dim);
  color: var(--accent);
  transform: translateY(-1px);
}
</style>
