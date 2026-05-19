<script setup>
import { ref, computed } from 'vue'
import { NCard, NButton, NSpace, NTag, NDivider } from 'naive-ui'
import QuoteCountdown from './QuoteCountdown.vue'
import RiskDisclosure from './RiskDisclosure.vue'
import ScenarioCompare from './ScenarioCompare.vue'
import PricingInsight from './PricingInsight.vue'

const props = defineProps({
  data: { type: Object, required: true },
})

const emit = defineEmits(['confirm', 'cancel', 'refresh', 'quickQuery'])

// Internal state
const showRisk = ref(false)

// Helper functions
function directionLabel(d) {
  if (d === 'B') return '结汇'
  if (d === 'S') return '购汇'
  return d
}

function productLabel(p) {
  const map = { SPOT: '即期', FWD: '远期', SWAP: '掉期' }
  return map[p] || p
}

// Computed
const isPricingMode = computed(() => {
  const m = props.data.mode || ''
  return m.startsWith('pricing_') || m === 'trade_success' || m === 'trade_failed'
})

const isDirectTrade = computed(() => props.data.mode === 'pricing_direct_trade')

const isCompare = computed(
  () => props.data.mode === 'pricing_compare' || props.data.intent_type === 'COMPARE'
)

const isScenario = computed(
  () => props.data.mode === 'pricing_scenario' || props.data.intent_type === 'SCENARIO'
)

// Handlers
function handleTradeClick() {
  if (props.data.risk_disclosure) {
    showRisk.value = true
  } else {
    emit('confirm', props.data.pricing_id)
  }
}

function handleRiskConfirmed() {
  showRisk.value = false
  emit('confirm', props.data.pricing_id)
}

function onExpired() {
  emit('refresh', props.data.pricing_id)
}
</script>

<template>
  <div v-if="isPricingMode" class="pricing-container">
    <!-- Compare / Scenario mode: show ScenarioCompare -->
    <ScenarioCompare
      v-if="isCompare || isScenario"
      :data="data"
      @confirm="emit('confirm', data.pricing_id)"
    />

    <!-- Single / Multi quote mode: render NCard per quote -->
    <template v-else>
      <NCard
        v-for="(quote, idx) in data.quotes"
        :key="quote.quote_id || idx"
        class="quote-card"
        size="small"
      >
        <!-- Header: currency pair + product tag -->
        <div class="quote-header">
          <span class="quote-pair">{{ quote.currency_pair }}</span>
          <NTag size="small" :bordered="false">
            {{ productLabel(quote.product_type) }}{{ directionLabel(quote.direction) }}
          </NTag>
        </div>

        <NDivider style="margin: 8px 0" />

        <!-- Rate display -->
        <div class="quote-rate">{{ quote.customer_rate }}</div>

        <!-- Meta info -->
        <div class="quote-meta">
          <span>点差：{{ quote.spread_bp }}bp</span>
          <span v-if="quote.value_date">交割日：{{ quote.value_date }}</span>
        </div>

        <!-- Countdown -->
        <QuoteCountdown
          v-if="data.valid_until"
          :valid-until="data.valid_until"
          @expired="onExpired"
        />

        <!-- Action buttons -->
        <NSpace justify="end" style="margin-top: 12px">
          <NButton size="small" @click="emit('cancel', data.pricing_id)">
            取消
          </NButton>
          <NButton size="small" @click="emit('refresh', data.pricing_id)">
            刷新
          </NButton>
          <NButton
            v-if="isDirectTrade || data.show_trade_button"
            size="small"
            type="error"
            @click="handleTradeClick"
          >
            确认交易
          </NButton>
        </NSpace>
      </NCard>
    </template>

    <!-- Insights panel -->
    <PricingInsight
      v-if="data.insights && data.insights.length"
      :insights="data.insights"
      @quickQuery="emit('quickQuery', $event)"
    />

    <!-- Novice mode tip -->
    <div v-if="data.novice_mode" class="novice-bar">
      💡 点击专业术语可查看解释
    </div>

    <!-- Risk disclosure modal -->
    <RiskDisclosure
      :show="showRisk"
      :title="data.risk_disclosure?.title || '风险提示'"
      :items="data.risk_disclosure?.items || []"
      @confirm="handleRiskConfirmed"
      @cancel="showRisk = false"
    />
  </div>
  <div v-else class="pricing-fallback">
    <NSpace>
      <NButton size="small" @click="emit('cancel', data.pricing_id)">取消</NButton>
      <NButton size="small" @click="emit('refresh', data.pricing_id)">刷新</NButton>
    </NSpace>
  </div>
</template>

<style scoped>
.pricing-container {
  max-width: 520px;
}

.quote-card {
  margin-bottom: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.quote-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.quote-pair {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.quote-rate {
  font-size: 28px;
  font-weight: 700;
  color: var(--accent);
  margin: 4px 0;
  font-family: 'Consolas', 'Courier New', monospace;
}

.quote-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.novice-bar {
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--blue-light);
  border-radius: 6px;
  font-size: 12px;
  color: var(--blue);
}

.pricing-fallback {
  padding: 12px;
}
</style>
