<script setup>
import { ref, computed } from 'vue'
import { NTabs, NTabPane, NDataTable, NCode } from 'naive-ui'
import ChartView from './ChartView.vue'
import InsightPanel from './InsightPanel.vue'
import { COLUMN_LABELS, formatCellValue } from '../constants.js'
import * as XLSX from 'xlsx'

const props = defineProps({
  data: { type: Object, required: true },
  showSql: { type: Boolean, default: false },
  showParams: { type: Boolean, default: false },
})

const emit = defineEmits(['quickQuery'])

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
  return props.data.rows.map(row => {
    const obj = {}
    props.data.columns.forEach((col, i) => { obj[col] = row[i] })
    return obj
  })
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
    <div v-if="data.summary" class="result-summary">
      <div class="summary-text">{{ data.summary }}</div>
      <div class="summary-meta">
        <span v-if="data.params?.date_start">🕐 {{ data.params.date_start }} ~ {{ data.params.date_end }}</span>
        <span v-if="data.comparison" :style="{ color: (data.comparison.change_amount ?? 0) >= 0 ? 'var(--success-text)' : 'var(--error)' }">
          {{ data.comparison.change_amount >= 0 ? '▲' : '▼' }} {{ data.comparison.label }} {{ data.comparison.change_rate }}%
        </span>
      </div>
    </div>

    <!-- Section 2: Chart -->
    <div v-if="data.chartOption?.series" class="result-chart">
      <div class="section-label">📈 {{ data.chartOption._title || '数据图表' }}</div>
      <ChartView :option="data.chartOption" />
    </div>

    <!-- Section 3: Insights -->
    <InsightPanel :insights="data.insights || []" @click="onInsightClick" />

    <!-- Section 4: Data table -->
    <NTabs v-model:value="activeTab" type="line" :tabs-padding="0">
      <NTabPane tab="数据" name="data">
        <NDataTable
          :columns="tableColumns"
          :data="tableData"
          :max-height="360"
          :bordered="true"
          size="small"
          striped
        />
      </NTabPane>
      <NTabPane v-if="data.sql" tab="SQL" name="sql">
        <NCode :code="data.sql" language="sql" :word-wrap="true" />
      </NTabPane>
      <NTabPane v-if="data.params" tab="参数" name="params">
        <NCode :code="JSON.stringify(data.params, null, 2)" language="json" :word-wrap="true" />
      </NTabPane>
    </NTabs>

    <!-- Footer -->
    <div class="result-footer">
      <span class="footer-row-count">共 {{ data.row_count ?? data.rows?.length ?? 0 }} 行</span>
      <span class="footer-export">
        <span class="export-btn" @click="handleExportExcel">📥 Excel</span>
        <span class="export-btn" @click="handleExportPdf">📄 PDF</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.result-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  font-size: 13px;
}
.result-summary {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, #1e3a5f20, #1e293b);
}
.summary-text { font-size: 14px; line-height: 1.6; }
.summary-meta {
  margin-top: 6px;
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-secondary);
}
.result-chart {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}
.section-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.result-footer {
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
}
.footer-export { display:flex; gap:12px; }
.export-btn { cursor: pointer; }
.export-btn:hover { color: var(--text-secondary); }
</style>
