<script setup>
import { reactive, watch, onMounted } from 'vue'
import {
  NSelect, NDatePicker, NRadioGroup, NRadio, NCheckbox, NCheckboxGroup,
  NInput, NInputNumber, NSwitch, NButton, NSpace, NTag, NCard, NText,
} from 'naive-ui'
import {
  PRODUCT_TYPE_OPTIONS, BUY_SELL_OPTIONS, APP_ID_OPTIONS, SPECIAL_STATES, DIMENSION_OPTIONS,
} from '../constants.js'

const props = defineProps({
  params: { type: Object, required: true },
  pipeline: { type: String, default: 'llm+gatekeep' },
  originalText: { type: String, default: '' },
  querying: { type: Boolean, default: false },
  resetting: { type: Boolean, default: false },
})

const emit = defineEmits(['confirm', 'reset'])

function parseSpecialStates(val) {
  if (Array.isArray(val)) return val
  if (typeof val === 'string' && val) return val.split(',').filter(Boolean)
  return []
}

function strToTs(s) {
  if (!s) return null
  const d = new Date(s + 'T00:00:00')
  return isNaN(d.getTime()) ? null : d.getTime()
}

function tsToStr(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const form = reactive({
  product_type: 'all',
  date_start: null,
  date_end: null,
  buy_sell: '',
  appid: null,
  special_states: [],
  bank_name: '',
  cust_name: '',
  aggregate: false,
  top_n: null,
  dimension: 'bank',
})

function syncFromParams(p) {
  if (!p) return
  form.product_type = p.product_type || 'all'
  form.date_start = strToTs(p.date_start)
  form.date_end = strToTs(p.date_end)
  form.buy_sell = p.buy_sell || ''
  form.appid = p.appid != null ? Number(p.appid) : null
  form.special_states = parseSpecialStates(p.special_states)
  form.bank_name = p.bank_name || ''
  form.cust_name = p.cust_name || ''
  form.aggregate = !!p.aggregate
  form.top_n = p.top_n ? Number(p.top_n) : null
  form.dimension = p.dimension || 'bank'
}

onMounted(() => syncFromParams(props.params))
watch(() => props.params, (newVal) => syncFromParams(newVal), { deep: true })

function handleConfirm() {
  const collected = {
    product_type: form.product_type,
    date_start: tsToStr(form.date_start),
    date_end: tsToStr(form.date_end),
    buy_sell: form.buy_sell,
    appid: form.appid !== null && form.appid !== '' ? Number(form.appid) : null,
    special_states: form.special_states.join(','),
    bank_name: form.bank_name,
    cust_name: form.cust_name,
    aggregate: form.aggregate,
    top_n: form.top_n ? Number(form.top_n) : 0,
    dimension: form.dimension,
    comparison: props.params.comparison || '',
  }
  emit('confirm', collected)
}
</script>

<template>
  <NCard :bordered="true" style="margin-top: 8px;" size="small">
    <template #header>
      <NSpace align="center">
        <NText strong>参数确认</NText>
        <NTag
          :type="pipeline === 'llm+gatekeep' ? 'success' : 'warning'"
          :bordered="false"
          size="small"
        >
          {{ pipeline === 'llm+gatekeep' ? 'LLM解析' : '规则匹配' }}
        </NTag>
        <NTag
          v-if="params.comparison === 'yoy'"
          type="info"
          :bordered="false"
          size="small"
        >
          同比
        </NTag>
        <NTag
          v-if="params.comparison === 'mom'"
          type="info"
          :bordered="false"
          size="small"
        >
          环比
        </NTag>
      </NSpace>
    </template>

    <NSpace vertical :size="12">
      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">产品类型</NText>
        <NSelect
          v-model:value="form.product_type"
          :options="PRODUCT_TYPE_OPTIONS"
          style="width: 120px;"
          size="small"
        />
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">日期范围</NText>
        <NDatePicker
          v-model:value="form.date_start"
          type="date"
          placeholder="开始日期"
          size="small"
          style="width: 140px;"
          clearable
          format="yyyy-MM-dd"
        />
        <NText depth="3">至</NText>
        <NDatePicker
          v-model:value="form.date_end"
          type="date"
          placeholder="结束日期"
          size="small"
          style="width: 140px;"
          clearable
          format="yyyy-MM-dd"
        />
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">买卖方向</NText>
        <NRadioGroup v-model:value="form.buy_sell" size="small">
          <NRadio
            v-for="opt in BUY_SELL_OPTIONS"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </NRadio>
        </NRadioGroup>
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">业务系统</NText>
        <NRadioGroup v-model:value="form.appid" size="small">
          <NRadio
            v-for="opt in APP_ID_OPTIONS"
            :key="String(opt.value)"
            :value="opt.value"
          >
            {{ opt.label }}
          </NRadio>
        </NRadioGroup>
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">特殊状态</NText>
        <NCheckboxGroup v-model:value="form.special_states">
          <NSpace>
            <NCheckbox
              v-for="st in SPECIAL_STATES"
              :key="st.value"
              :value="st.value"
            >
              {{ st.label }}
            </NCheckbox>
          </NSpace>
        </NCheckboxGroup>
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">银行名称</NText>
        <NInput
          v-model:value="form.bank_name"
          placeholder="如：工商银行"
          size="small"
          style="width: 200px;"
          clearable
        />
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">客户名称</NText>
        <NInput
          v-model:value="form.cust_name"
          placeholder="如：测试客户"
          size="small"
          style="width: 200px;"
          clearable
        />
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">聚合/TopN</NText>
        <NSwitch v-model:value="form.aggregate" size="small" />
        <NText depth="3" style="font-size: 13px;">汇总</NText>
        <NText depth="3" style="margin-left: 12px; font-size: 13px;">Top N</NText>
        <NInputNumber
          v-model:value="form.top_n"
          :min="1"
          placeholder="不限"
          size="small"
          style="width: 90px;"
          clearable
        />
      </NSpace>

      <NSpace align="center">
        <NText depth="3" style="min-width: 62px; font-size: 13px;">统计维度</NText>
        <NSelect
          v-model:value="form.dimension"
          :options="DIMENSION_OPTIONS"
          style="width: 160px;"
          size="small"
        />
      </NSpace>
    </NSpace>

    <template #footer>
      <NSpace justify="end">
        <NButton
          type="primary"
          :loading="querying"
          :disabled="querying"
          @click="handleConfirm"
        >
          确认查询
        </NButton>
        <NButton
          :loading="resetting"
          :disabled="resetting || querying"
          @click="$emit('reset')"
        >
          重置
        </NButton>
      </NSpace>
    </template>
  </NCard>
</template>
