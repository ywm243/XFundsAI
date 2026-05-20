<script setup>
import { computed, h } from 'vue'
import { NCard, NDataTable } from 'naive-ui'
import { BarChart3, Layers, FileText } from 'lucide-vue-next'

const props = defineProps({
  data: { type: Object, required: true },
})

// ── formatters ─────────────────────────────────────────
function fmtNum(n) {
  if (n == null || n === '' || !Number.isFinite(n)) return '-'
  return Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function fmtPct(n) {
  if (n == null || n === '' || !Number.isFinite(n)) return '-'
  const s = (n >= 0 ? '+' : '') + Number(n).toFixed(2)
  return s + '%'
}

// ── derived data ───────────────────────────────────────
const analysisData = computed(() => props.data.analysis_data)

const baseline = computed(() => analysisData.value?.baseline || {})

const metricLabel = computed(() => analysisData.value?.metric_label || '交易量')

const dimensions = computed(() => analysisData.value?.dimensions || [])

const isUp = computed(() => {
  const c = baseline.value.total_change
  return c != null && c >= 0
})

const hasPositiveDrivers = (drivers) => drivers.some(d => d.contrib_pct > 0)
const hasNegativeDrivers = (drivers) => drivers.some(d => d.contrib_pct < 0)

// ── contribution bar column render ─────────────────────
// Normalize against the max absolute contrib in the current dimension table
// so bars are proportional even when contrib_pct > 100%
const _maxContribCache = new WeakMap()

function _getMaxContrib(drivers) {
  if (_maxContribCache.has(drivers)) return _maxContribCache.get(drivers)
  const maxVal = drivers.reduce((m, d) => Math.max(m, Math.abs(d.contrib_pct || 0)), 0) || 100
  _maxContribCache.set(drivers, maxVal)
  return maxVal
}

function renderContrib(row, index) {
  const pct = row.contrib_pct
  if (pct == null) return '-'
  const drivers = row._drivers_ref
  const maxAbs = drivers ? _getMaxContrib(drivers) : 100
  const barWidth = Math.min((Math.abs(pct) / maxAbs) * 100, 100)
  const color = pct >= 0 ? 'var(--success-text)' : 'var(--error)'
  return h('div', { class: 'contrib-cell' }, [
    h('div', {
      class: 'contrib-bar',
      style: {
        width: barWidth + '%',
        backgroundColor: color,
      },
    }),
    h('span', { class: 'contrib-text' }, fmtPct(pct)),
  ])
}

function renderChange(row) {
  const v = row.change_value
  if (v == null) return '-'
  const color = v >= 0 ? 'var(--success-text)' : 'var(--error)'
  return h('span', { style: { color } }, (v >= 0 ? '+' : '') + fmtNum(v))
}

function getDimColumns(drivers) {
  const contribRenderer = (row) => renderContrib(row, 0)
  return [
    { title: '名称', key: 'dimension_value', ellipsis: { tooltip: true } },
    {
      title: `${metricLabel.value}变化`,
      key: 'change_value',
      render: renderChange,
      sorter: (a, b) => (a.change_value || 0) - (b.change_value || 0),
    },
    {
      title: '贡献度',
      key: 'contrib_pct',
      render: contribRenderer,
      sorter: (a, b) => Math.abs(b.contrib_pct || 0) - Math.abs(a.contrib_pct || 0),
    },
  ]
}
</script>

<template>
  <div class="analysis-result">
    <!-- ── Fallback: no structured data ── -->
    <div v-if="!analysisData" class="summary-plain">{{ data.summary }}</div>

    <!-- ── Structured view ── -->
    <template v-else>
      <!-- Overview KPI card -->
      <NCard class="ana-card" size="small" :bordered="true">
        <template #header><BarChart3 :size="15" /> 总览</template>
        <div class="kpi-row">
          <div class="kpi-box">
            <div class="kpi-label">当期{{ metricLabel }}</div>
            <div class="kpi-value">{{ fmtNum(baseline.total_trading_volume) }}</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">上期{{ metricLabel }}</div>
            <div class="kpi-value">{{ fmtNum(baseline.prev_total_trading_volume) }}</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">变化量</div>
            <div class="kpi-value" :class="isUp ? 'up' : 'down'">{{ fmtNum(baseline.total_change) }}</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-label">变化率</div>
            <div class="kpi-value" :class="isUp ? 'up' : 'down'">{{ fmtPct(baseline.total_change_pct) }}</div>
          </div>
        </div>
      </NCard>

      <!-- Dimension cards with driver tables -->
      <NCard
        v-for="dim in dimensions"
        :key="dim.dimension"
        class="ana-card"
        size="small"
        :bordered="true"
      >
        <template #header><Layers :size="15" /> {{ dim.dim_label }}</template>
        <div class="dim-subtitle">
          总变化：<span :class="baseline.total_change >= 0 ? 'up' : 'down'">
            {{ fmtNum(baseline.total_change) }}（{{ fmtPct(baseline.total_change_pct) }}）
          </span>
        </div>

        <NDataTable
          :columns="getDimColumns(dim.drivers)"
          :data="dim.drivers.map(d => ({...d, _drivers_ref: dim.drivers}))"
          :max-height="320"
          :bordered="false"
          size="small"
          striped
          :single-line="false"
        />

        <!-- Legend for dual-sign contributions -->
        <div v-if="hasPositiveDrivers(dim.drivers) && hasNegativeDrivers(dim.drivers)" class="dim-legend">
          <span class="legend-dot" style="background:var(--success-text)" /> 正向贡献
          <span class="legend-dot" style="background:var(--error);margin-left:16px" /> 负向贡献
        </div>
      </NCard>

      <!-- Summary / conclusions card -->
      <NCard v-if="data.summary" class="ana-card" size="small" :bordered="true">
        <template #header><FileText :size="15" /> 总结</template>
        <div class="summary-text">{{ data.summary }}</div>
      </NCard>
    </template>
  </div>
</template>

<style scoped>
.analysis-result {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ana-card {
  background: var(--bg-card, #1e293b);
  border: 1px solid var(--border, #334155);
  border-radius: 10px;
}

/* ── Fallback plain text ── */
.summary-plain {
  padding: 16px;
  line-height: 1.8;
  font-size: 13px;
  color: var(--text-primary, #e2e8f0);
  white-space: pre-wrap;
}

/* ── KPI row ── */
.kpi-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.kpi-box {
  flex: 1;
  min-width: 140px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 8px;
  padding: 14px 16px;
  text-align: center;
}

.kpi-label {
  font-size: 11px;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.kpi-value {
  font-size: 16px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary, #e2e8f0);
}

/* ── Dimension card ── */
.dim-subtitle {
  font-size: 12px;
  color: var(--text-secondary, #94a3b8);
  margin-bottom: 10px;
}

.dim-legend {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-muted, #64748b);
  display: flex;
  align-items: center;
}

.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 4px;
}

/* ── Contribution bar column ── */
.contrib-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
}

.contrib-bar {
  height: 16px;
  border-radius: 3px;
  min-width: 2px;
  transition: width 0.3s ease;
  opacity: 0.7;
  flex-shrink: 0;
}

.contrib-text {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
  white-space: nowrap;
  z-index: 1;
}

/* ── Summary text ── */
.summary-text {
  line-height: 1.8;
  font-size: 13px;
  color: var(--text-primary, #e2e8f0);
  white-space: pre-wrap;
}

/* ── Colors ── */
.up { color: var(--success-text, #22c55e); }
.down { color: var(--error, #ef4444); }
</style>
