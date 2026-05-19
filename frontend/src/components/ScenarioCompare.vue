<script setup>
import { computed } from 'vue'
import { NDataTable } from 'naive-ui'

const props = defineProps({
  data: { type: Object, required: true },
})

const emit = defineEmits(['confirm'])

const columns = [
  { title: '产品', key: 'product', width: 120 },
  { title: '价格', key: 'rate', width: 100 },
  { title: '点差', key: 'spread', width: 80 },
  { title: '期限', key: 'tenor', width: 80 },
  { title: '交割日', key: 'value_date', width: 120 },
]

const productLabel = (p) => ({ SPOT: '即期', FWD: '远期', SWAP: '掉期' })[p] || p
const directionLabel = (d) => d === 'B' ? '结汇' : d === 'S' ? '购汇' : ''

const rows = computed(() =>
  (props.data.quotes || []).map((q, i) => ({
    key: i,
    product: `${productLabel(q.product_type)}${directionLabel(q.direction)}`,
    rate: q.customer_rate,
    spread: `${q.spread_bp}bp`,
    tenor: q.tenor || '-',
    value_date: q.value_date || '-',
  }))
)
</script>

<template>
  <div class="compare-table">
    <h4 class="compare-title">{{ data.scenario_name || '报价对比' }}</h4>
    <NDataTable :columns="columns" :data="rows" size="small" />
    <div class="scenario-disclaimer">
      模拟结果，不代表实际盈亏。实际成交价格以询价接口返回为准。
    </div>
    <div class="scenario-source" v-if="data.data_source">
      数据来源：{{ data.data_source }}
    </div>
  </div>
</template>

<style scoped>
.compare-table {
  margin-bottom: 12px;
}
.compare-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.scenario-disclaimer {
  margin-top: 12px;
  padding: 8px 12px;
  background: #fff3e0;
  border: 1px solid #ffcc02;
  border-left: 4px solid #e65100;
  border-radius: 4px;
  font-size: 12px;
  color: #bf360c;
  font-weight: 500;
}

.scenario-source {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: right;
}
</style>
