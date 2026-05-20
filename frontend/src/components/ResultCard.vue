<script setup>
import { ref, computed } from 'vue'
import { NTabs, NTabPane, NDataTable, NCode } from 'naive-ui'
import ChartView from './ChartView.vue'
import InsightPanel from './InsightPanel.vue'
import AnalysisResult from './AnalysisResult.vue'
import { COLUMN_LABELS, formatCellValue } from '../constants.js'
import * as XLSX from 'xlsx'
import { TrendingUp, Download, FileText, Clock, ChevronUp, ChevronDown, Database, Code, Filter, FileJson } from 'lucide-vue-next'

const props = defineProps({
  data: { type: Object, required: true },
  showSql: { type: Boolean, default: false },
  showParams: { type: Boolean, default: false },
})

const emit = defineEmits(['quickQuery'])

// ── Data volume guard ──────────────────────────────────────────────
const MAX_CHART_ITEMS = 100
const MAX_TABLE_ROWS = 2000
const ROW_WARN_THRESHOLD = 500

const isAnalyze = computed(() => props.data.mode === 'analyze')

const isOversized = computed(() => {
  const n = props.data.row_count ?? props.data.rows?.length ?? 0
  return n > ROW_WARN_THRESHOLD
})

const warningMessage = computed(() => {
  const n = props.data.row_count ?? props.data.rows?.length ?? 0
  if (n > MAX_TABLE_ROWS) return `数据量过大（共 ${n} 行），表格仅显示前 ${MAX_TABLE_ROWS} 行`
  if (n > ROW_WARN_THRESHOLD) return `数据量较大（共 ${n} 行）`
  return ''
})

const safeChartOption = computed(() => {
  const opt = props.data.chartOption
  if (!opt?.series) return null
  const n = props.data.row_count ?? props.data.rows?.length ?? 0
  if (n <= MAX_CHART_ITEMS) return opt
  // Truncate chart data to prevent browser OOM
  return {
    ...opt,
    xAxis: opt.xAxis ? { ...opt.xAxis, data: (opt.xAxis.data || []).slice(0, MAX_CHART_ITEMS) } : opt.xAxis,
    series: (opt.series || []).map(s => ({
      ...s,
      data: (s.data || []).slice(0, MAX_CHART_ITEMS),
    })),
  }
})

function onInsightClick(query) {
  if (query) emit('quickQuery', query)
}

const tableColumns = computed(() => {
  if (!props.data.columns) return []
  return props.data.columns.map(col => ({
    title: COLUMN_LABELS[col] || col,
    key: col,
    ellipsis: { tooltip: true },
    render(row) { return formatCellValue(col, row[col]) },
  }))
})

const tableData = computed(() => {
  if (!props.data.columns || !props.data.rows) return []
  const rows = props.data.rows.slice(0, MAX_TABLE_ROWS)
  return rows.map(row => {
    const obj = {}
    props.data.columns.forEach((col, i) => { obj[col] = row[i] })
    return obj
  })
})

const tableRowCount = computed(() => {
  return props.data.row_count ?? props.data.rows?.length ?? 0
})

const activeTab = ref('data')

// ---- export helpers ----
function buildExportData() {
  const cols = props.data.columns || []
  const rows = props.data.rows || []
  const header = cols.map(c => COLUMN_LABELS[c] || c)
  const body = rows.map(row => cols.map((c, i) => {
    const raw = row[i]
    return formatCellValue(c, raw)
  }))
  return { header, body, cols, rows: body }
}

function handleExportExcel() {
  const { header, rows } = buildExportData()
  const ws = XLSX.utils.aoa_to_sheet([header, ...rows])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, '查询结果')
  XLSX.writeFile(wb, `SmartBI_${new Date().toISOString().slice(0,10)}.xlsx`)
}

function handleExportPdf() {
  const { header, rows } = buildExportData()
  const title = props.data.summary || '查询结果'
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>
<style>
  body { font-family: "Microsoft YaHei","PingFang SC",sans-serif; padding:24px; color:#1e293b; }
  h2 { font-size:16px; margin-bottom:16px; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th { background:#f1f5f9; text-align:left; padding:8px 10px; border:1px solid #e2e8f0; }
  td { padding:6px 10px; border:1px solid #e2e8f0; }
  tr:nth-child(even) { background:#f8fafc; }
  .meta { color:#94a3b8; font-size:11px; margin-bottom:16px; }
  @media print { body { padding:0; } }
</style></head><body>
  <h2>${title}</h2>
  <div class="meta">导出时间: ${new Date().toLocaleString()} | 共 ${rows.length} 行</div>
  <table><thead><tr>${header.map(h => `<th>${h}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(row => `<tr>${row.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>
  <script>window.onload=function(){window.print();}<${''}/script>
</body></html>`
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const win = window.open(url, '_blank', 'width=1000,height=700')
  if (win) {
    win.onload = () => { URL.revokeObjectURL(url) }
  } else {
    const a = document.createElement('a')
    a.href = url; a.download = `SmartBI_${new Date().toISOString().slice(0,10)}.html`; a.click()
    URL.revokeObjectURL(url)
  }
}
</script>

<template>
  <div class="result-card">
    <!-- Section 1: NL Summary -->
    <AnalysisResult v-if="isAnalyze && data.summary" :data="data" />
    <div v-else-if="data.summary" class="result-summary">
      <div class="summary-text">{{ data.summary }}</div>
      <div class="summary-meta">
        <span v-if="data.params?.date_start" class="meta-date">
          <Clock :size="11" /> {{ data.params.date_start }} ~ {{ data.params.date_end }}
        </span>
        <span v-if="data.comparison" class="meta-compare" :class="{ positive: (data.comparison.change_amount ?? 0) >= 0, negative: (data.comparison.change_amount ?? 0) < 0 }">
          <ChevronUp v-if="(data.comparison.change_amount ?? 0) >= 0" :size="13" />
          <ChevronDown v-else :size="13" />
          {{ data.comparison.label }} {{ data.comparison.change_rate }}%
        </span>
      </div>
    </div>

    <!-- Section 2: Chart (hide in analyze mode) -->
    <div v-if="!isAnalyze && safeChartOption?.series" class="result-chart">
      <div class="section-label"><TrendingUp :size="13" /> {{ safeChartOption._title || '数据图表' }}</div>
      <div v-if="isOversized" class="chart-warning">图表仅显示前 {{ MAX_CHART_ITEMS }} 项</div>
      <ChartView :option="safeChartOption" />
    </div>

    <!-- Section 3: Insights (hide in analyze mode) -->
    <InsightPanel v-if="!isAnalyze" :insights="data.insights || []" @click="onInsightClick" />

    <!-- Section 4: Data table (hide in analyze mode) -->
    <template v-if="!isAnalyze">
      <div v-if="warningMessage" class="data-warning">{{ warningMessage }}</div>
      <NTabs v-model:value="activeTab" type="line">
        <NTabPane name="data">
          <template #tab>
            <span class="tab-header"><Database :size="13" /> 数据</span>
          </template>
          <NDataTable
            :columns="tableColumns"
            :data="tableData"
            :max-height="360"
            :bordered="true"
            size="small"
            striped
          />
        </NTabPane>
        <NTabPane v-if="data.sql" name="sql">
          <template #tab>
            <span class="tab-header"><Code :size="13" /> SQL</span>
          </template>
          <NCode :code="data.sql" language="sql" :word-wrap="true" />
        </NTabPane>
        <NTabPane v-if="data.comparison_sql" name="comparison_sql">
          <template #tab>
            <span class="tab-header"><Code :size="13" /> 对比SQL</span>
          </template>
          <NCode :code="data.comparison_sql" language="sql" :word-wrap="true" />
        </NTabPane>
        <NTabPane v-if="data.params" name="params">
          <template #tab>
            <span class="tab-header"><Filter :size="13" /> 参数</span>
          </template>
          <NCode :code="JSON.stringify(data.params, null, 2)" language="json" :word-wrap="true" />
        </NTabPane>
      </NTabs>

      <!-- Footer -->
      <div class="result-footer">
        <span class="footer-row-count">共 {{ tableRowCount }} 行</span>
        <span class="footer-export">
          <span class="export-btn" @click="handleExportExcel"><Download :size="12" /> Excel</span>
          <span class="export-btn" @click="handleExportPdf"><FileText :size="12" /> PDF</span>
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.result-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  font-size: 13px;
}

.result-summary {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(200,141,10,0.04), transparent 50%);
}
.summary-text { font-size: 14px; line-height: 1.7; font-family: var(--font-sans); }
.summary-meta {
  margin-top: 8px;
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: var(--text-muted);
}
.meta-date, .meta-compare { display: flex; align-items: center; gap: 4px; }
.meta-compare.positive { color: var(--success-text); }
.meta-compare.negative { color: var(--error); }

.result-chart {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 5px;
}

.tab-header { display: inline-flex; align-items: center; gap: 5px; }

.result-footer {
  padding: 10px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
}
.footer-export { display: flex; gap: 16px; }
.export-btn {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: color 0.15s;
}
.export-btn:hover { color: var(--text-secondary); }

.data-warning, .chart-warning {
  padding: 6px 16px;
  background: var(--warning-bg);
  color: #f59e0b;
  font-size: 12px;
  border-bottom: 1px solid rgba(245,158,11,0.15);
}
.chart-warning {
  padding: 4px 0 8px;
  background: transparent;
  border: none;
}
</style>
