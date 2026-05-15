<script setup>
import { computed } from 'vue'
import { NTabs, NTabPane, NDataTable, NCode, NText, NCard, NSpace, NTag } from 'naive-ui'
import { COLUMN_LABELS, formatCellValue } from '../constants.js'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
})

const hasData = computed(() =>
  props.data.columns?.length > 0 && props.data.rows?.length > 0
)
const hasSql = computed(() => !!props.data.sql)
const hasParams = computed(() =>
  props.data.params && Object.keys(props.data.params).length > 0
)
const hasComparison = computed(() => !!props.data.comparison)

const comparison = computed(() => props.data.comparison)
const changeTagType = computed(() => {
  if (!comparison.value) return 'default'
  return (comparison.value.change_amount ?? 0) >= 0 ? 'success' : 'error'
})
const changeSign = computed(() => {
  if (!comparison.value) return ''
  return (comparison.value.change_amount ?? 0) >= 0 ? '+' : '-'
})

const tableColumns = computed(() => {
  if (!props.data.columns) return []
  return props.data.columns.map((col) => ({
    title: COLUMN_LABELS[col] || col,
    key: col,
    ellipsis: { tooltip: true },
    render(row) {
      return formatCellValue(col, row[col])
    },
  }))
})

const tableData = computed(() => {
  if (!props.data.columns || !props.data.rows) return []
  return props.data.rows.map((row) => {
    const obj = {}
    props.data.columns.forEach((col, i) => {
      obj[col] = row[i]
    })
    return obj
  })
})

const paramsString = computed(() => {
  if (!hasParams.value) return ''
  return JSON.stringify(props.data.params, null, 2)
})
</script>

<template>
  <div v-if="hasComparison" style="margin-top: 8px;">
    <NCard size="small" :bordered="true">
      <template #header>
        <NSpace align="center">
          <NText strong>{{ comparison.label }}对比</NText>
          <NTag :type="changeTagType" size="small">
            {{ changeSign }}{{ comparison.change_rate }}%
          </NTag>
        </NSpace>
      </template>
      <NSpace :size="24">
        <div>
          <NText depth="3" style="font-size: 12px;">当期 ({{ comparison.current_period }})</NText>
          <br>
          <NText strong style="font-size: 16px;">{{ comparison.current_amount?.toLocaleString() }} 万美元</NText>
        </div>
        <div>
          <NText depth="3" style="font-size: 12px;">{{ comparison.label }} ({{ comparison.compare_period }})</NText>
          <br>
          <NText strong style="font-size: 16px;">{{ comparison.compare_amount?.toLocaleString() }} 万美元</NText>
        </div>
        <div>
          <NText depth="3" style="font-size: 12px;">变化</NText>
          <br>
          <NText
            :type="changeTagType"
            strong
            style="font-size: 16px;"
          >
            {{ changeSign }}{{ Math.abs(comparison.change_amount)?.toLocaleString() }} 万美元
          </NText>
        </div>
      </NSpace>
    </NCard>
  </div>

  <NTabs type="line" :tabs-padding="0" style="margin-top: 8px;">
    <NTabPane v-if="hasData" tab="数据" name="data">
      <NDataTable
        :columns="tableColumns"
        :data="tableData"
        :max-height="400"
        :bordered="true"
        :single-line="false"
        size="small"
        striped
      />
      <NText depth="3" style="font-size: 12px; margin-top: 6px; display: block;">
        共 {{ data.row_count ?? data.rows?.length ?? 0 }} 行
      </NText>
    </NTabPane>
    <NTabPane v-if="hasSql" tab="SQL" name="sql">
      <NCode :code="data.sql" language="sql" :word-wrap="true" />
    </NTabPane>
    <NTabPane v-if="hasParams" tab="参数" name="params">
      <NCode :code="paramsString" language="json" :word-wrap="true" />
    </NTabPane>
  </NTabs>
</template>
