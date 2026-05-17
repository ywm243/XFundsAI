<script setup>
import { ref, reactive, computed, onMounted, h } from 'vue'
import {
  NCard, NTag, NButton, NSpace, NSelect, NInput, NModal,
  NDataTable, NSwitch, NPopconfirm, NText, NCode, NSpin,
  NRadioGroup, NRadio, NCheckboxGroup, NInputNumber, NAlert,
  NDivider, NBadge, useMessage,
} from 'naive-ui'

const message = useMessage()

// ============================================================
// State
// ============================================================
const categories = ref([])
const selectedAgent = ref(null)
const selectedCategoryId = ref(null)
const selectedCategory = computed(() =>
  categories.value.find(c => c.id === selectedCategoryId.value)
)
const items = ref([])
const loading = ref(false)
const previewText = ref('')
const previewResult = ref(null)
const previewLoading = ref(false)
const reloading = ref(false)

// Edit modal
const showEditModal = ref(false)
const editMode = ref('create')
const editErrors = ref([])

const editingItem = reactive({
  id: null,
  keywords_str: '',
  // Common
  priority: 0,
  description: '',
  is_ironclad: false,
  is_active: true,
  // app_id
  app_id_value: null,
  // buy_sell_direction
  direction: '',
  product_types: [],
  customer_direction: '',
  // product_type
  product_type_value: '',
  // special_trade_type
  sub_type: 'state',
  mapped_value: '',
  // time_expressions
  pattern: '',
  param: '',
  compute_start: '',
  compute_end: '',
  example: '',
  // comparison_modifiers
  comparison_type: '',
  cmp_example: '',
  cmp_note: '',
})

// Versions modal
const showVersionsModal = ref(false)
const versions = ref([])

// ============================================================
// Options
// ============================================================
const agentOptions = [
  { value: null, label: '全部' },
  { value: 'common', label: '公共 (common)' },
  { value: 'bi', label: 'BI Agent' },
  { value: 'quoting', label: '询报价 Agent' },
  { value: 'risk', label: '风控 Agent' },
]

const directionOptions = [
  { value: 'B', label: 'B（银行买入）' },
  { value: 'S', label: 'S（银行卖出）' },
]

const productTypeOptions = [
  { value: 'spot', label: '即期外汇' },
  { value: 'fwd', label: '远期外汇' },
  { value: 'swap', label: '外汇掉期' },
]

const appIdOptions = [
  { value: 1, label: '外汇 (1)' },
  { value: 2, label: '结售汇 (2)' },
]

const tradeTypeOptions = [
  { value: 'all', label: '所有交易 (all)' },
  { value: 'spot', label: '即期外汇 (spot)' },
  { value: 'fwd', label: '远期外汇 (fwd)' },
  { value: 'swap', label: '外汇掉期 (swap)' },
]

const specialSubTypeOptions = [
  { value: 'state', label: '特殊状态' },
  { value: 'class_kaicang', label: '开仓交易' },
  { value: 'class_pingcang', label: '平仓交易' },
  { value: 'class_zhanqi', label: '展期交易' },
  { value: 'class_jiaoge', label: '提前交割交易' },
]

const stateValueOptions = [
  { value: '0', label: '0 - 正常交易' },
  { value: '1,2,6,7,10,11,15,17', label: '平仓（全部子类）' },
  { value: '4,16', label: '提前交割（全部子类）' },
  { value: '3,5,12,13', label: '展期（全部子类）' },
]

const lifecycleStatusValueOptions = [
  { value: 'not_due', label: 'not_due - 未到期' },
  { value: 'overdue', label: 'overdue - 逾期' },
  { value: 'due_today', label: 'due_today - 已到期' },
  { value: 'unclosed', label: 'unclosed - 未完结' },
  { value: 'closed', label: 'closed - 已完结' },
]

const tradeClassValueOptions = [
  { value: 0, label: '0 - 普通交易' },
  { value: 1, label: '1 - 提前平仓' },
  { value: 2, label: '2 - 交割日平仓' },
  { value: 3, label: '3 - 市价展期' },
  { value: 4, label: '4 - 提前交割' },
  { value: 5, label: '5 - 原价展期' },
  { value: 6, label: '6 - 全部平仓' },
  { value: 7, label: '7 - 反向平盘' },
  { value: 10, label: '10 - 提前平仓' },
  { value: 11, label: '11 - 到期平仓' },
  { value: 12, label: '12 - 近端原价展期' },
  { value: 13, label: '13 - 近端市价展期' },
  { value: 14, label: '14 - 近端到期交割' },
  { value: 15, label: '15 - 近端到期平仓' },
  { value: 16, label: '16 - 近端提前交割' },
  { value: 17, label: '17 - 近端提前平仓' },
]

// ============================================================
// Helpers
// ============================================================
function currentCategory() {
  const cat = selectedCategory.value
  return cat ? cat.category : ''
}

function catDisplayName() {
  const cat = selectedCategory.value
  return cat ? (cat.display_name || cat.category) : ''
}

function getItemCount(cat) {
  return cat.item_count || 0
}

function parseKeywords(raw) {
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return [raw] }
  }
  return []
}

function parseRuleData(raw) {
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return {} }
  }
  return raw || {}
}

// ============================================================
// API helpers
// ============================================================
const api = {
  async get(path) {
    const resp = await fetch(path)
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
  async post(path, body) {
    const resp = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${resp.status}`)
    }
    return resp.json()
  },
  async put(path, body) {
    const resp = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${resp.status}`)
    }
    return resp.json()
  },
  async del(path) {
    const resp = await fetch(path, { method: 'DELETE' })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
}

// ============================================================
// Data loading
// ============================================================
async function loadCategories() {
  loading.value = true
  try {
    const params = selectedAgent.value ? `?agent_type=${selectedAgent.value}` : ''
    const data = await api.get(`/api/admin/rules/categories${params}`)
    categories.value = data.categories
  } catch (err) {
    message.error(`加载分类失败: ${err.message}`)
  } finally {
    loading.value = false
  }
}

async function loadItems(categoryId) {
  selectedCategoryId.value = categoryId
  loading.value = true
  try {
    const data = await api.get(`/api/admin/rules/categories/${categoryId}/items`)
    items.value = data.items
  } catch (err) {
    message.error(`加载规则失败: ${err.message}`)
  } finally {
    loading.value = false
  }
}

onMounted(() => loadCategories())

// ============================================================
// Item actions
// ============================================================
function resetEditingItem() {
  editingItem.id = null
  editingItem.keywords_str = ''
  editingItem.priority = 0
  editingItem.description = ''
  editingItem.is_ironclad = false
  editingItem.is_active = true
  editingItem.app_id_value = null
  editingItem.app_id_meaning = ''
  editingItem.direction = ''
  editingItem.product_types = []
  editingItem.customer_direction = ''
  editingItem.product_type_value = ''
  editingItem.sub_type = 'state'
  editingItem.mapped_value = ''
  editingItem.pattern = ''
  editingItem.param = ''
  editingItem.compute_start = ''
  editingItem.compute_end = ''
  editingItem.example = ''
  editingItem.comparison_type = ''
  editingItem.cmp_example = ''
  editingItem.cmp_note = ''
  // dimension_labels
  editingItem.editing_dim_key = ''
  editingItem.display_label = ''
  editingItem.count_unit = ''
  editingItem.sql_select_col = ''
  editingItem.sql_group_col = ''
  editingItem.join_clause = ''
  editingItem.label_col_names_str = ''
  editingItem.amount_col_names_str = ''
  editingItem.yoy_label = ''
  editingItem.mom_label = ''
  editErrors.value = []
}

function openCreate() {
  editMode.value = 'create'
  resetEditingItem()
  showEditModal.value = true
}

function openEdit(item) {
  editMode.value = 'edit'
  editErrors.value = []
  resetEditingItem()

  editingItem.id = item.id
  const kws = parseKeywords(item.keywords)
  editingItem.keywords_str = kws.join(', ')
  editingItem.is_ironclad = !!item.is_ironclad
  editingItem.priority = item.priority || 0
  editingItem.is_active = item.is_active !== false

  const rd = parseRuleData(item.rule_data)
  editingItem.description = rd.description || ''

  const cat = currentCategory()

  if (cat === 'app_id') {
    editingItem.app_id_value = rd.value || null
    editingItem.app_id_meaning = rd.meaning || ''
  } else if (cat === 'buy_sell_direction') {
    editingItem.direction = rd.direction || ''
    editingItem.product_types = rd.product_types || []
    editingItem.customer_direction = rd.customer_direction || ''
    editingItem.app_id_value = rd.set_app_id || null
  } else if (cat === 'product_type') {
    editingItem.product_type_value = rd.value || ''
  } else if (cat === 'special_trade_type') {
    editingItem.sub_type = rd.sub_type || 'state'
    editingItem.mapped_value = rd.value !== undefined ? String(rd.value) : ''
  } else if (cat === 'lifecycle_status') {
    editingItem.mapped_value = rd.value || ''
  } else if (cat === 'comparison_modifiers') {
    editingItem.comparison_type = rd.keyword === '环比' ? 'mom' : 'yoy'
    editingItem.compute_start = rd.compute_start || ''
    editingItem.compute_end = rd.compute_end || ''
    editingItem.cmp_example = rd.example || ''
    editingItem.cmp_note = rd.note || ''
  } else if (cat === 'time_expressions') {
    editingItem.pattern = rd.pattern || ''
    editingItem.param = rd.param || ''
    editingItem.compute_start = rd.compute_start || ''
    editingItem.compute_end = rd.compute_end || ''
    editingItem.example = rd.example || ''
  } else if (cat === 'dimension_labels') {
    editingItem.editing_dim_key = kws[0] || ''
    editingItem.display_label = rd.display_label || ''
    editingItem.count_unit = rd.count_unit || ''
    editingItem.sql_select_col = rd.sql_select_col || ''
    editingItem.sql_group_col = rd.sql_group_col || ''
    editingItem.join_clause = rd.join_clause || ''
    editingItem.label_col_names_str = (rd.label_col_names || []).join(', ')
    editingItem.amount_col_names_str = (rd.amount_col_names || []).join(', ')
    editingItem.yoy_label = (rd.comparison_labels || {}).yoy || ''
    editingItem.mom_label = (rd.comparison_labels || {}).mom || ''
  }

  showEditModal.value = true
}

function validateItem() {
  const errors = []
  const kw = editingItem.keywords_str.split(',').map(k => k.trim()).filter(Boolean)

  if (kw.length === 0 && currentCategory() !== 'time_expressions') {
    errors.push('关键词不能为空')
  }

  const cat = currentCategory()

  if (cat === 'buy_sell_direction' && !editingItem.direction) {
    errors.push('买卖方向不能为空')
  }
  if (cat === 'app_id' && !editingItem.app_id_value) {
    errors.push('产品ID不能为空')
  }
  if (cat === 'product_type' && !editingItem.product_type_value) {
    errors.push('交易类型不能为空')
  }
  if (cat === 'special_trade_type' && !editingItem.mapped_value) {
    errors.push('映射值不能为空')
  }
  if (cat === 'lifecycle_status' && !editingItem.mapped_value) {
    errors.push('生命周期状态值不能为空')
  }
  if (cat === 'comparison_modifiers' && !editingItem.comparison_type) {
    errors.push('对比类型不能为空')
  }
  if (cat === 'time_expressions' && !editingItem.pattern) {
    errors.push('表达式模式不能为空')
  }
  if (cat === 'dimension_labels' && editingItem.keywords_str.trim() !== '_meta') {
    if (!editingItem.display_label) errors.push('显示标签不能为空')
    if (!editingItem.sql_select_col) errors.push('SQL选择列不能为空')
  }
  if (editingItem.is_ironclad && !editingItem.description) {
    errors.push('铁律规则必须填写说明')
  }
  if (editingItem.priority < 0) {
    errors.push('优先级必须是非负整数')
  }

  return { valid: errors.length === 0, errors, keywords: kw }
}

function buildRuleData() {
  const rd = {}
  const cat = currentCategory()

  switch (cat) {
    case 'app_id':
      rd.value = editingItem.app_id_value
      if (editingItem.app_id_meaning) rd.meaning = editingItem.app_id_meaning
      break
    case 'buy_sell_direction':
      rd.direction = editingItem.direction
      rd.product_types = editingItem.product_types
      rd.customer_reversible = !editingItem.is_ironclad
      if (!editingItem.is_ironclad && editingItem.customer_direction) {
        rd.customer_direction = editingItem.customer_direction
      }
      if (editingItem.app_id_value) rd.set_app_id = editingItem.app_id_value
      break
    case 'product_type':
      rd.value = editingItem.product_type_value
      break
    case 'special_trade_type':
      rd.sub_type = editingItem.sub_type
      rd.value = editingItem.mapped_value
      rd.field = editingItem.sub_type === 'state' ? 'SPECIALSTATE' : 'SPECTRADECLASS'
      break
    case 'lifecycle_status':
      rd.field = 'LIFECYCLE_STATUS'
      rd.value = editingItem.mapped_value
      rd.meaning = lifecycleStatusLabel(editingItem.mapped_value)
      break
    case 'comparison_modifiers':
      rd.comparison_type = editingItem.comparison_type
      rd.compute_start = editingItem.compute_start
      rd.compute_end = editingItem.compute_end
      rd.example = editingItem.cmp_example
      rd.note = editingItem.cmp_note
      break
    case 'time_expressions':
      rd.pattern = editingItem.pattern
      rd.param = editingItem.param || undefined
      rd.compute_start = editingItem.compute_start
      rd.compute_end = editingItem.compute_end
      rd.example = editingItem.example
      break
    case 'dimension_labels':
      if (editingItem.keywords_str.trim() === '_meta') {
        rd.amount_col_names = editingItem.amount_col_names_str.split(',').map(s => s.trim()).filter(Boolean)
        rd.comparison_labels = {
          yoy: editingItem.yoy_label || '同比',
          mom: editingItem.mom_label || '环比',
        }
      } else {
        rd.display_label = editingItem.display_label
        rd.count_unit = editingItem.count_unit
        rd.sql_select_col = editingItem.sql_select_col
        rd.sql_group_col = editingItem.sql_group_col
        rd.join_clause = editingItem.join_clause
        rd.label_col_names = editingItem.label_col_names_str.split(',').map(s => s.trim()).filter(Boolean)
      }
      break
  }
  rd.description = editingItem.description
  return rd
}

async function saveItem() {
  const { valid, errors, keywords } = validateItem()
  if (!valid) { editErrors.value = errors; return }
  editErrors.value = []

  const body = {
    keywords,
    rule_data: buildRuleData(),
    is_ironclad: editingItem.is_ironclad,
    priority: editingItem.priority,
  }

  try {
    if (editMode.value === 'create') {
      await api.post(`/api/admin/rules/categories/${selectedCategoryId.value}/items`, body)
    } else {
      await api.put(`/api/admin/rules/items/${editingItem.id}`, body)
    }
    message.success('保存成功')
    showEditModal.value = false
    loadItems(selectedCategoryId.value)
    loadCategories()
  } catch (err) {
    editErrors.value = [err.message]
  }
}

async function toggleActive(item) {
  try {
    await api.put(`/api/admin/rules/items/${item.id}`, { is_active: !item.is_active })
    message.success(item.is_active ? '已禁用' : '已启用')
    loadItems(selectedCategoryId.value)
    loadCategories()
  } catch (err) {
    message.error(`操作失败: ${err.message}`)
  }
}

async function deleteItem(item) {
  try {
    await api.del(`/api/admin/rules/items/${item.id}`)
    message.success('已删除')
    loadItems(selectedCategoryId.value)
    loadCategories()
  } catch (err) {
    message.error(`删除失败: ${err.message}`)
  }
}

// ============================================================
// Versions
// ============================================================
async function loadVersions() {
  try {
    const data = await api.get(`/api/admin/rules/categories/${selectedCategoryId.value}/versions`)
    versions.value = data.versions
    showVersionsModal.value = true
  } catch (err) {
    message.error(`加载版本失败: ${err.message}`)
  }
}

async function doRollback(versionNum) {
  try {
    await api.post(`/api/admin/rules/categories/${selectedCategoryId.value}/rollback?version_num=${versionNum}`)
    message.success(`已回滚到版本 ${versionNum}`)
    showVersionsModal.value = false
    loadItems(selectedCategoryId.value)
    loadCategories()
  } catch (err) {
    message.error(`回滚失败: ${err.message}`)
  }
}

// ============================================================
// Preview
// ============================================================
async function runPreview() {
  previewLoading.value = true
  try {
    const data = await api.post('/api/admin/rules/preview', { text: previewText.value })
    previewResult.value = data
  } catch (err) {
    message.error(`预览失败: ${err.message}`)
  } finally {
    previewLoading.value = false
  }
}

// ============================================================
// Hot-reload
// ============================================================
async function doReload() {
  reloading.value = true
  try {
    await api.post('/api/admin/rules/reload')
    message.success('规则已热部署，所有缓存已刷新')
  } catch (err) {
    message.error(`热部署失败: ${err.message}`)
  } finally {
    reloading.value = false
  }
}

// ============================================================
// Rule card display helpers
// ============================================================
function formatKeywords(keywords) {
  return parseKeywords(keywords)
}

function appIdLabel(v) {
  return v === 1 ? '外汇' : v === 2 ? '结售汇' : String(v)
}

function directionLabel(d) {
  return d === 'B' ? 'B(银行买入)' : d === 'S' ? 'S(银行卖出)' : d
}

function productTypeLabels(types) {
  const map = { spot: '即期外汇', fwd: '远期外汇', swap: '外汇掉期' }
  return (types || []).map(t => map[t] || t).join('/')
}

function tradeTypeLabel(v) {
  const map = { spot: '即期外汇交易', fwd: '远期外汇交易', swap: '外汇掉期交易', all: '所有交易' }
  return map[v] || v
}

function specialStateMeaning(v) {
  const map = {
    '0': '正常交易',
    '1,2,6,7,10,11,15,17': '平仓（全部子类）',
    '4,16': '提前交割（全部子类）',
    '3,5,12,13': '展期（全部子类）',
  }
  return map[String(v)] || String(v)
}

function lifecycleStatusLabel(v) {
  const map = {
    not_due: '未到期',
    overdue: '逾期',
    due_today: '已到期',
    unclosed: '未完结',
    closed: '已完结',
  }
  return map[String(v)] || String(v)
}

function tradeClassMeaning(v) {
  const map = {
    0: '普通交易', 1: '提前平仓', 2: '交割日平仓', 3: '市价展期', 4: '提前交割', 5: '原价展期',
    6: '全部平仓', 7: '反向平盘', 10: '提前平仓', 11: '到期平仓', 12: '近端原价展期',
    13: '近端市价展期', 14: '近端到期交割', 15: '近端到期平仓', 16: '近端提前交割', 17: '近端提前平仓',
  }
  return map[Number(v)] || String(v)
}

function specialSubTypeLabel(st) {
  const map = { state: '特殊状态', class: '平仓交易', class_kaicang: '开仓交易', class_pingcang: '平仓交易', class_zhanqi: '展期交易', class_jiaoge: '提前交割交易' }
  return map[st] || (st || '')
}

function isSpecialState(st) {
  return (st || '').startsWith('state')
}

// Build current rule JSON for technical preview
function buildCurrentRuleJSON() {
  const cat = selectedCategory.value
  if (!cat || items.value.length === 0) return []
  return items.value.map(item => {
    const kws = parseKeywords(item.keywords)
    const rd = parseRuleData(item.rule_data)
    return {
      keywords: kws,
      ...rd,
      _ironclad: item.is_ironclad || undefined,
      _priority: item.priority,
      _active: item.is_active,
    }
  })
}

// ============================================================
// Edit form: determine mapped value options based on sub_type
// ============================================================
const mappedValueOptions = computed(() => {
  if (editingItem.sub_type === 'state') {
    return stateValueOptions
  }
  // class_*
  return tradeClassValueOptions
})

const showCustomerDirection = computed(() => {
  return currentCategory() === 'buy_sell_direction' && !editingItem.is_ironclad
})
</script>

<template>
  <div style="height: calc(100vh - 42px); display: flex; flex-direction: column;">

    <!-- ====== Top bar ====== -->
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid var(--border); flex-shrink: 0;">
      <NSpace align="center" :size="12">
        <NText depth="3" style="font-size: 13px;">Agent 筛选</NText>
        <NSelect
          v-model:value="selectedAgent"
          :options="agentOptions"
          style="width: 150px;"
          size="small"
          @update:value="loadCategories"
        />
      </NSpace>
      <NSpace :size="8">
        <NButton size="small" @click="runPreview" :loading="previewLoading">
          预览测试
        </NButton>
        <NButton size="small" type="warning" @click="doReload" :loading="reloading">
          热部署
        </NButton>
      </NSpace>
    </div>

    <!-- ====== Main area ====== -->
    <div style="flex: 1; display: flex; overflow: hidden;">

      <!-- === Left: category nav === -->
      <div style="width: 200px; flex-shrink: 0; border-right: 1px solid var(--border); overflow-y: auto; background: var(--bg-sidebar); padding: 8px 0;">
        <div
          v-for="cat in categories"
          :key="cat.id"
          @click="loadItems(cat.id)"
          :style="{
            padding: '10px 16px',
            cursor: 'pointer',
            borderLeft: selectedCategoryId === cat.id ? '3px solid var(--accent)' : '3px solid transparent',
            background: selectedCategoryId === cat.id ? 'rgba(29,78,216,0.12)' : 'transparent',
            transition: 'background 0.15s',
          }"
        >
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <NText
              :depth="selectedCategoryId === cat.id ? 1 : 3"
              :strong="selectedCategoryId === cat.id"
              style="font-size: 13px;"
            >
              {{ cat.display_name || cat.category }}
            </NText>
            <NTag :bordered="false" size="tiny" :type="cat.active_count > 0 ? 'success' : 'default'">
              {{ cat.item_count }}
            </NTag>
          </div>
        </div>
      </div>

      <!-- === Right: rule details === -->
      <div style="flex: 1; overflow-y: auto; padding: 16px 20px;">

        <!-- Category header -->
        <div v-if="selectedCategory" style="margin-bottom: 16px;">
          <NSpace justify="space-between" align="center">
            <div>
              <NText tag="h3" strong style="margin: 0;">
                {{ catDisplayName() }}
              </NText>
              <NText depth="3" style="font-size: 12px; display: block; margin-top: 2px;">
                共 {{ items.length }} 条规则
              </NText>
            </div>
            <NSpace :size="8">
              <NButton size="small" @click="loadVersions">版本历史</NButton>
              <NButton size="small" type="primary" @click="openCreate">+ 新增规则</NButton>
            </NSpace>
          </NSpace>
        </div>

        <!-- Rule cards -->
        <NSpin v-if="loading" />
        <NSpace v-else vertical :size="10">
          <NCard
            v-for="(item, idx) in items"
            :key="item.id"
            size="small"
            :bordered="true"
            :style="{ opacity: item.is_active === false ? 0.55 : 1 }"
          >
            <!-- === app_id === -->
            <template v-if="currentCategory() === 'app_id'">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <NTag v-for="kw in formatKeywords(item.keywords)" :key="kw" size="small" type="info" :bordered="false">
                  {{ kw }}
                </NTag>
                <NText depth="3" style="margin: 0 2px;">→</NText>
                <NBadge :value="'APPID=' + parseRuleData(item.rule_data).value" type="info" />
                <NText depth="3" style="font-size: 11px;">
                  {{ appIdLabel(parseRuleData(item.rule_data).value) }}
                </NText>
                <span style="flex:1;"></span>
                <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                <NTag v-if="item.is_ironclad" size="tiny" type="warning">铁律</NTag>
                <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                  {{ item.is_active !== false ? '启用' : '禁用' }}
                </NTag>
                <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                <NButton size="tiny" @click="toggleActive(item)">
                  {{ item.is_active !== false ? '禁用' : '启用' }}
                </NButton>
                <NPopconfirm @positive-click="() => deleteItem(item)">
                  <template #trigger>
                    <NButton size="tiny" type="error">删除</NButton>
                  </template>
                  确定删除此规则？
                </NPopconfirm>
              </div>
            </template>

            <!-- === buy_sell_direction === -->
            <template v-else-if="currentCategory() === 'buy_sell_direction'">
              <div>
                <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                  <NTag v-for="kw in formatKeywords(item.keywords)" :key="kw" size="small" type="info" :bordered="false">
                    {{ kw }}
                  </NTag>
                  <NText depth="3" style="margin: 0 2px;">→</NText>
                  <NBadge :value="parseRuleData(item.rule_data).direction === 'B' ? 'B' : 'S'" :type="parseRuleData(item.rule_data).direction === 'B' ? 'info' : 'warning'">
                    {{ directionLabel(parseRuleData(item.rule_data).direction) }}
                  </NBadge>
                  <template v-if="!item.is_ironclad">
                    <NText depth="3" style="font-size: 11px;">|</NText>
                    <NText depth="3" style="font-size: 11px;">
                      客户{{ parseRuleData(item.rule_data).customer_direction === 'B' ? 'B(银行买入)' : parseRuleData(item.rule_data).customer_direction === 'S' ? 'S(银行卖出)' : '' }}
                    </NText>
                  </template>
                  <NText depth="3" style="font-size: 11px;">
                    {{ productTypeLabels(parseRuleData(item.rule_data).product_types) }}
                  </NText>
                  <template v-if="parseRuleData(item.rule_data).set_app_id">
                    <NText depth="3" style="font-size: 10px;">
                      AppID:{{ parseRuleData(item.rule_data).set_app_id }}
                    </NText>
                  </template>
                  <span style="flex:1;"></span>
                  <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                  <NTag v-if="item.is_ironclad" size="tiny" type="warning">铁律</NTag>
                  <NTag v-else-if="parseRuleData(item.rule_data).customer_reversible !== false" size="tiny" type="success">可反转</NTag>
                  <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                    {{ item.is_active !== false ? '启用' : '禁用' }}
                  </NTag>
                  <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                  <NButton size="tiny" @click="toggleActive(item)">
                    {{ item.is_active !== false ? '禁用' : '启用' }}
                  </NButton>
                  <NPopconfirm @positive-click="() => deleteItem(item)">
                    <template #trigger>
                      <NButton size="tiny" type="error">删除</NButton>
                    </template>
                    确定删除此规则？
                  </NPopconfirm>
                </div>
                <div v-if="parseRuleData(item.rule_data).description" style="margin-top: 4px;">
                  <NText depth="3" style="font-size: 11px;">
                    说明: {{ parseRuleData(item.rule_data).description }}
                  </NText>
                </div>
              </div>
            </template>

            <!-- === product_type === -->
            <template v-else-if="currentCategory() === 'product_type'">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <NTag v-for="kw in formatKeywords(item.keywords)" :key="kw" size="small" type="info" :bordered="false">
                  {{ kw }}
                </NTag>
                <NText depth="3" style="margin: 0 2px;">→</NText>
                <NBadge :value="parseRuleData(item.rule_data).value" type="info">
                  {{ tradeTypeLabel(parseRuleData(item.rule_data).value) }}
                </NBadge>
                <span style="flex:1;"></span>
                <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                  {{ item.is_active !== false ? '启用' : '禁用' }}
                </NTag>
                <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                <NButton size="tiny" @click="toggleActive(item)">
                  {{ item.is_active !== false ? '禁用' : '启用' }}
                </NButton>
                <NPopconfirm @positive-click="() => deleteItem(item)">
                  <template #trigger>
                    <NButton size="tiny" type="error">删除</NButton>
                  </template>
                  确定删除此规则？
                </NPopconfirm>
              </div>
            </template>

            <!-- === special_trade_type === -->
            <template v-else-if="currentCategory() === 'special_trade_type'">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <NTag v-for="kw in formatKeywords(item.keywords)" :key="kw" size="small" type="info" :bordered="false">
                  {{ kw }}
                </NTag>
                <NText depth="3" style="margin: 0 2px;">—</NText>
                <NText style="font-size: 12px;">{{ specialSubTypeLabel(parseRuleData(item.rule_data).sub_type) }}</NText>
                <NText depth="3" style="margin: 0 2px;">—</NText>
                <template v-if="isSpecialState(parseRuleData(item.rule_data).sub_type)">
                  <NText depth="3" style="font-size: 11px;">状态码:</NText>
                  <NBadge :value="parseRuleData(item.rule_data).value" type="warning" />
                  <NText depth="3" style="font-size: 11px;">
                    ({{ specialStateMeaning(parseRuleData(item.rule_data).value) }})
                  </NText>
                </template>
                <template v-else>
                  <NText depth="3" style="font-size: 11px;">交易类别:</NText>
                  <NBadge :value="parseRuleData(item.rule_data).value" type="warning" />
                  <NText depth="3" style="font-size: 11px;">
                    ({{ tradeClassMeaning(parseRuleData(item.rule_data).value) }})
                  </NText>
                </template>
                <span style="flex:1;"></span>
                <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                  {{ item.is_active !== false ? '启用' : '禁用' }}
                </NTag>
                <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                <NButton size="tiny" @click="toggleActive(item)">
                  {{ item.is_active !== false ? '禁用' : '启用' }}
                </NButton>
                <NPopconfirm @positive-click="() => deleteItem(item)">
                  <template #trigger>
                    <NButton size="tiny" type="error">删除</NButton>
                  </template>
                  确定删除此规则？
                </NPopconfirm>
              </div>
            </template>

            <!-- === lifecycle_status === -->
            <template v-else-if="currentCategory() === 'lifecycle_status'">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <NTag v-for="kw in formatKeywords(item.keywords)" :key="kw" size="small" type="info" :bordered="false">
                  {{ kw }}
                </NTag>
                <NText depth="3" style="margin: 0 2px;">—</NText>
                <NBadge :value="parseRuleData(item.rule_data).value" type="warning" />
                <NText depth="3" style="font-size: 11px;">
                  ({{ lifecycleStatusLabel(parseRuleData(item.rule_data).value) }})
                </NText>
                <span style="flex:1;"></span>
                <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                  {{ item.is_active !== false ? '启用' : '禁用' }}
                </NTag>
                <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                <NButton size="tiny" @click="toggleActive(item)">
                  {{ item.is_active !== false ? '禁用' : '启用' }}
                </NButton>
                <NPopconfirm @positive-click="() => deleteItem(item)">
                  <template #trigger>
                    <NButton size="tiny" type="error">删除</NButton>
                  </template>
                  确定删除此规则？
                </NPopconfirm>
              </div>
            </template>

            <!-- === time_expressions === -->
            <template v-else-if="currentCategory() === 'time_expressions'">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <NText style="font-size: 12px;">
                  模式:
                </NText>
                <NTag size="small" type="info" :bordered="false">
                  {{ parseRuleData(item.rule_data).pattern }}
                </NTag>
                <template v-if="parseRuleData(item.rule_data).param">
                  <NText depth="3" style="font-size: 11px;">— 参数:</NText>
                  <NTag size="small" :bordered="false">
                    {{ parseRuleData(item.rule_data).param }}
                  </NTag>
                </template>
                <NText depth="3" style="margin: 0 2px;">—</NText>
                <NText depth="3" style="font-size: 11px;">
                  {{ parseRuleData(item.rule_data).compute_start }} ~ {{ parseRuleData(item.rule_data).compute_end }}
                </NText>
                <span style="flex:1;"></span>
                <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                  {{ item.is_active !== false ? '启用' : '禁用' }}
                </NTag>
                <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                <NButton size="tiny" @click="toggleActive(item)">
                  {{ item.is_active !== false ? '禁用' : '启用' }}
                </NButton>
                <NPopconfirm @positive-click="() => deleteItem(item)">
                  <template #trigger>
                    <NButton size="tiny" type="error">删除</NButton>
                  </template>
                  确定删除此规则？
                </NPopconfirm>
              </div>
            </template>

            <!-- === comparison_modifiers === -->
            <template v-else-if="currentCategory() === 'comparison_modifiers'">
              <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                <NTag v-for="kw in formatKeywords(item.keywords)" :key="kw" size="small" type="info" :bordered="false">
                  {{ kw }}
                </NTag>
                <NText depth="3" style="margin: 0 2px;">→</NText>
                <NBadge :value="parseRuleData(item.rule_data).keyword === '同比' || parseRuleData(item.rule_data).keyword === '同步' ? 'yoy' : 'mom'" type="success">
                  {{ parseRuleData(item.rule_data).keyword === '同比' || parseRuleData(item.rule_data).keyword === '同步' ? '同比(yoy)' : '环比(mom)' }}
                </NBadge>
                <span style="flex:1;"></span>
                <NText depth="3" style="font-size: 11px;">#{{ item.priority }}</NText>
                <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                  {{ item.is_active !== false ? '启用' : '禁用' }}
                </NTag>
                <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                <NButton size="tiny" @click="toggleActive(item)">
                  {{ item.is_active !== false ? '禁用' : '启用' }}
                </NButton>
                <NPopconfirm @positive-click="() => deleteItem(item)">
                  <template #trigger>
                    <NButton size="tiny" type="error">删除</NButton>
                  </template>
                  确定删除此规则？
                </NPopconfirm>
              </div>
              <div v-if="parseRuleData(item.rule_data).description" style="margin-top: 6px; font-size: 10px; color: var(--text-muted);">
                {{ parseRuleData(item.rule_data).description }}
              </div>
            </template>

            <!-- === dimension_labels === -->
            <template v-else-if="currentCategory() === 'dimension_labels'">
              <div>
                <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px;">
                  <NTag size="small" type="info" :bordered="false">
                    {{ parseKeywords(item.keywords)[0] }}
                  </NTag>
                  <template v-if="parseKeywords(item.keywords)[0] === '_meta'">
                    <NText depth="3" style="font-size:11px;">全局配置 — 金额字段: </NText>
                    <NTag v-for="col in (parseRuleData(item.rule_data).amount_col_names || [])" :key="col" size="tiny" type="success" :bordered="false">{{ col }}</NTag>
                    <NText depth="3" style="font-size:11px;"> 对比标签: </NText>
                    <NText style="font-size:11px;">{{ (parseRuleData(item.rule_data).comparison_labels || {}).yoy }} / {{ (parseRuleData(item.rule_data).comparison_labels || {}).mom }}</NText>
                  </template>
                  <template v-else>
                    <NText style="font-size:12px; font-weight:500;">{{ parseRuleData(item.rule_data).display_label }}</NText>
                    <NTag size="tiny" type="warning" :bordered="false">单位: {{ parseRuleData(item.rule_data).count_unit }}</NTag>
                    <NText depth="3" style="font-size:11px;">SQL: {{ parseRuleData(item.rule_data).sql_select_col }}</NText>
                  </template>
                  <span style="flex:1;"></span>
                  <NTag :type="item.is_active !== false ? 'success' : 'default'" size="tiny">
                    {{ item.is_active !== false ? '启用' : '禁用' }}
                  </NTag>
                  <NButton size="tiny" @click="openEdit(item)">编辑</NButton>
                  <NButton size="tiny" @click="toggleActive(item)">
                    {{ item.is_active !== false ? '禁用' : '启用' }}
                  </NButton>
                  <NPopconfirm @positive-click="() => deleteItem(item)">
                    <template #trigger>
                      <NButton size="tiny" type="error">删除</NButton>
                    </template>
                    确定删除此规则？
                  </NPopconfirm>
                </div>
                <details v-if="parseKeywords(item.keywords)[0] !== '_meta'" style="margin-top:6px; font-size:11px;">
                  <summary style="cursor:pointer; color: var(--text-muted);">详细SQL配置</summary>
                  <div style="margin-top:4px; padding:6px; background: rgba(0,0,0,0.03); border-radius:4px;">
                    <div><NText depth="3">分组列: </NText><code>{{ parseRuleData(item.rule_data).sql_group_col }}</code></div>
                    <div v-if="parseRuleData(item.rule_data).join_clause" style="margin-top:2px;">
                      <NText depth="3">JOIN: </NText><code style="font-size:10px;">{{ parseRuleData(item.rule_data).join_clause }}</code>
                    </div>
                    <div v-if="(parseRuleData(item.rule_data).label_col_names || []).length > 0" style="margin-top:2px;">
                      <NText depth="3">标签列: </NText>
                      <NTag v-for="col in parseRuleData(item.rule_data).label_col_names" :key="col" size="tiny" :bordered="false">{{ col }}</NTag>
                    </div>
                  </div>
                </details>
              </div>
            </template>
          </NCard>

          <!-- Empty state -->
          <div v-if="items.length === 0 && !loading && selectedCategory" style="text-align: center; padding: 40px 0;">
            <NText depth="3">该分类暂无规则，点击"新增规则"添加</NText>
          </div>
        </NSpace>

        <!-- === Collapsed JSON preview === -->
        <details v-if="selectedCategory && items.length > 0" style="margin-top: 16px; font-size: 11px; color: var(--text-muted);">
          <summary>查看最终生成的JSON（仅供技术参考）</summary>
          <NCode :code="JSON.stringify(buildCurrentRuleJSON(), null, 2)" language="json" style="margin-top: 8px; max-height: 300px; overflow: auto;" />
        </details>

        <!-- No category selected -->
        <div v-if="!selectedCategory" style="display: flex; align-items: center; justify-content: center; height: 100%;">
          <NText depth="3">请从左侧选择一个分类查看规则</NText>
        </div>
      </div>
    </div>

    <!-- ====== Preview test (collapsed section at bottom of top bar area, only shown when active) ====== -->
    <div v-if="previewText || previewResult" style="padding: 8px 16px; border-top: 1px solid var(--border); background: var(--bg-sidebar); flex-shrink: 0;">
      <NSpace vertical :size="8">
        <NSpace align="center" :size="8">
          <NInput
            v-model:value="previewText"
            placeholder="输入测试语句，如：北京分公司今年一季度结汇交易量"
            style="width: 400px;"
            size="small"
            clearable
            @keyup.enter="runPreview"
          />
          <NButton type="primary" size="small" @click="runPreview" :loading="previewLoading">运行</NButton>
          <NButton size="tiny" @click="previewText = ''; previewResult = null">关闭</NButton>
        </NSpace>
        <NSpin v-if="previewLoading" />
        <div v-if="previewResult && !previewLoading">
          <NText depth="3" style="font-size: 11px;">
            置信度: {{ (previewResult.confidence * 100).toFixed(0) }}%
            — {{ previewResult.would_skip_llm ? '规则高置信，跳过 LLM' : '需调 LLM' }}
          </NText>
          <NCode :code="JSON.stringify(previewResult.after_gatekeep, null, 2)" language="json" style="margin-top: 4px; max-height: 200px; overflow: auto;" />
        </div>
      </NSpace>
    </div>

    <!-- ====== Edit modal ====== -->
    <NModal v-model:show="showEditModal" :title="editMode === 'create' ? '新增规则' : '编辑规则'">
      <NCard style="width: 580px; max-height: 80vh; overflow-y: auto;" size="small">
        <NSpace vertical :size="14">

          <!-- Keywords (all categories except time_expressions where pattern is the key) -->
          <div>
            <NSpace align="center">
              <NText strong style="font-size:12px;">关键词</NText>
              <NText v-if="currentCategory() !== 'time_expressions'" type="error" style="font-size:10px;">*必填</NText>
            </NSpace>
            <NInput
              v-model:value="editingItem.keywords_str"
              :placeholder="currentCategory() === 'time_expressions' ? '可选，如存在多个关键词用逗号分隔' : '用逗号分隔，如：外汇, 外汇交易'"
              style="margin-top:4px;"
            />
            <NText depth="3" style="font-size:10px;">用逗号分隔多个关键词</NText>
          </div>

          <!-- === app_id fields === -->
          <template v-if="currentCategory() === 'app_id'">
            <div>
              <NText strong style="font-size:12px;">产品ID <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NSelect
                v-model:value="editingItem.app_id_value"
                :options="appIdOptions"
                placeholder="选择产品ID"
                style="margin-top:4px;"
              />
            </div>
            <div>
              <NText strong style="font-size:12px;">说明</NText>
              <NInput v-model:value="editingItem.app_id_meaning" placeholder="如：外汇业务系统" style="margin-top:4px;" />
              <NText depth="3" style="font-size:10px;">用于日志显示的业务系统名称</NText>
            </div>
          </template>

          <!-- === buy_sell_direction fields === -->
          <template v-if="currentCategory() === 'buy_sell_direction'">
            <div>
              <NText strong style="font-size:12px;">买卖方向 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NRadioGroup v-model:value="editingItem.direction" style="margin-top:4px;">
                <NRadio value="B">B（银行买入）</NRadio>
                <NRadio value="S">S（银行卖出）</NRadio>
              </NRadioGroup>
            </div>
            <div>
              <NText strong style="font-size:12px;">适用产品类型</NText>
              <NCheckboxGroup v-model:value="editingItem.product_types" :options="productTypeOptions" style="margin-top:4px;" />
            </div>
            <div v-if="showCustomerDirection">
              <NText strong style="font-size:12px;">客户视角方向</NText>
              <NRadioGroup v-model:value="editingItem.customer_direction" style="margin-top:4px;">
                <NRadio value="B">B（银行买入）</NRadio>
                <NRadio value="S">S（银行卖出）</NRadio>
              </NRadioGroup>
              <NText depth="3" style="font-size:10px;">当查询带"客户"前缀时，方向反转为此值</NText>
            </div>
            <div>
              <NText strong style="font-size:12px;">关联产品</NText>
              <NRadioGroup v-model:value="editingItem.app_id_value" style="margin-top:4px;">
                <NRadio :value="1">外汇 (1)</NRadio>
                <NRadio :value="2">结售汇 (2)</NRadio>
              </NRadioGroup>
            </div>
          </template>

          <!-- === product_type fields === -->
          <template v-if="currentCategory() === 'product_type'">
            <div>
              <NText strong style="font-size:12px;">交易类型 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NSelect
                v-model:value="editingItem.product_type_value"
                :options="tradeTypeOptions"
                placeholder="选择交易类型"
                style="margin-top:4px;"
              />
            </div>
          </template>

          <!-- === special_trade_type fields === -->
          <template v-if="currentCategory() === 'special_trade_type'">
            <div>
              <NText strong style="font-size:12px;">子类型 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NSelect
                v-model:value="editingItem.sub_type"
                :options="specialSubTypeOptions"
                placeholder="选择子类型"
                style="margin-top:4px;"
              />
            </div>
            <div>
              <NText strong style="font-size:12px;">映射值 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NSelect
                v-model:value="editingItem.mapped_value"
                :options="mappedValueOptions"
                placeholder="选择映射值"
                style="margin-top:4px;"
              />
            </div>
          </template>

          <!-- === lifecycle_status fields === -->
          <template v-if="currentCategory() === 'lifecycle_status'">
            <div>
              <NText strong style="font-size:12px;">生命周期状态 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NSelect
                v-model:value="editingItem.mapped_value"
                :options="lifecycleStatusValueOptions"
                placeholder="选择生命周期状态"
                style="margin-top:4px;"
              />
            </div>
          </template>

          <!-- === comparison_modifiers fields === -->
          <template v-if="currentCategory() === 'comparison_modifiers'">
            <div>
              <NText strong style="font-size:12px;">对比类型 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NSelect
                v-model:value="editingItem.comparison_type"
                :options="[{ label: '同比 (yoy)', value: 'yoy' }, { label: '环比 (mom)', value: 'mom' }]"
                placeholder="选择对比类型"
                style="margin-top:4px;"
              />
            </div>
            <div>
              <NText strong style="font-size:12px;">计算起始</NText>
              <NInput v-model:value="editingItem.compute_start" placeholder="如：当前区间起点前移一年" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">计算截止</NText>
              <NInput v-model:value="editingItem.compute_end" placeholder="如：当前区间终点前移一年" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">示例</NText>
              <NInput v-model:value="editingItem.cmp_example" placeholder="如：本月同比 → 当前[本月1日, 今天] + 对比[去年本月1日, 去年今天]" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">备注</NText>
              <NInput v-model:value="editingItem.cmp_note" placeholder="如：若对比日期不存在，取当月最后一天" style="margin-top:4px;" />
            </div>
          </template>

          <!-- === time_expressions fields === -->
          <template v-if="currentCategory() === 'time_expressions'">
            <div>
              <NText strong style="font-size:12px;">表达式模式 <NText type="error" style="font-size:10px;">*必填</NText></NText>
              <NInput v-model:value="editingItem.pattern" placeholder="如：今年N月上旬" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">参数</NText>
              <NInput v-model:value="editingItem.param" placeholder="如：N" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">起算日期</NText>
              <NInput v-model:value="editingItem.compute_start" placeholder="如：本年N月1日" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">截止日期</NText>
              <NInput v-model:value="editingItem.compute_end" placeholder="如：本年N月10日" style="margin-top:4px;" />
            </div>
            <div>
              <NText strong style="font-size:12px;">示例</NText>
              <NInput v-model:value="editingItem.example" placeholder="如：今年1月上旬 → [1月1日, 1月10日]" style="margin-top:4px;" />
            </div>
          </template>

          <!-- === dimension_labels fields === -->
          <template v-if="currentCategory() === 'dimension_labels'">
            <template v-if="editingItem.keywords_str.trim() === '_meta'">
              <!-- _meta: global config -->
              <div>
                <NText strong style="font-size:12px;">金额字段名</NText>
                <NInput v-model:value="editingItem.amount_col_names_str" placeholder="用逗号分隔，如：USDAMOUNT, TOTAL_AMOUNT" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">用于识别数值列的字段名列表</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">同比标签</NText>
                <NInput v-model:value="editingItem.yoy_label" placeholder="同比" style="margin-top:4px;" />
              </div>
              <div>
                <NText strong style="font-size:12px;">环比标签</NText>
                <NInput v-model:value="editingItem.mom_label" placeholder="环比" style="margin-top:4px;" />
              </div>
            </template>
            <template v-else>
              <!-- Regular dimension -->
              <div>
                <NText strong style="font-size:12px;">维度标识</NText>
                <NInput v-model:value="editingItem.keywords_str" disabled style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">维度唯一标识（不可修改）</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">显示标签 <NText type="error" style="font-size:10px;">*必填</NText></NText>
                <NInput v-model:value="editingItem.display_label" placeholder="如：机构、客户、客户经理" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">查询摘要中显示的名称</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">计数单位</NText>
                <NInput v-model:value="editingItem.count_unit" placeholder="如：家、个、位" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">显示"共N{单位}"时的单位</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">SQL选择列 <NText type="error" style="font-size:10px;">*必填</NText></NText>
                <NInput v-model:value="editingItem.sql_select_col" placeholder="如：b.DIPNAME as 机构名称" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">GROUP BY 查询中的 SELECT 片段</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">SQL分组列</NText>
                <NInput v-model:value="editingItem.sql_group_col" placeholder="如：b.DIPNAME" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">GROUP BY 子句使用的列名</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">JOIN子句</NText>
                <NInput v-model:value="editingItem.join_clause" placeholder="如：LEFT JOIN XF_BASE_BANK b ON t.BANKID = b.BANKID" type="textarea" :rows="2" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">如需关联其他表时使用的 JOIN 语句，不需要则留空</NText>
              </div>
              <div>
                <NText strong style="font-size:12px;">标签列名</NText>
                <NInput v-model:value="editingItem.label_col_names_str" placeholder="用逗号分隔，如：DIPNAME, BANKNAME" style="margin-top:4px;" />
                <NText depth="3" style="font-size:10px;">用于识别文本标签的列名列表</NText>
              </div>
            </template>
          </template>

          <!-- ====== Common fields (end of form) ====== -->
          <NDivider style="margin: 4px 0;" />

          <NSpace :size="16" style="width: 100%;">
            <div style="flex: 1;">
              <NText strong style="font-size: 12px;">优先级</NText>
              <NInputNumber v-model:value="editingItem.priority" :min="0" style="margin-top:4px; width:100%;" />
              <NText depth="3" style="font-size: 10px;">数字越小越优先匹配</NText>
            </div>
          </NSpace>

          <div>
            <NText strong style="font-size: 12px;">说明</NText>
            <NInput v-model:value="editingItem.description" placeholder="帮助其他人理解此规则" style="margin-top:4px;" />
          </div>

          <NSpace align="center" justify="space-between">
            <div>
              <NText strong style="font-size: 12px;">铁律规则</NText>
              <br>
              <NText depth="3" style="font-size: 10px;">不可被客户前缀反转和AI覆盖</NText>
            </div>
            <NSwitch v-model:value="editingItem.is_ironclad" />
          </NSpace>

          <NSpace align="center" justify="space-between">
            <div>
              <NText strong style="font-size: 12px;">启用</NText>
            </div>
            <NSwitch v-model:value="editingItem.is_active" />
          </NSpace>

          <!-- Validation errors -->
          <NAlert v-if="editErrors.length > 0" type="error" title="保存失败，请修正以下问题：">
            <ul style="margin: 0; padding-left: 18px;">
              <li v-for="e in editErrors" :key="e">{{ e }}</li>
            </ul>
          </NAlert>
        </NSpace>

        <template #footer>
          <NSpace justify="end">
            <NButton @click="showEditModal = false">取消</NButton>
            <NButton type="primary" @click="saveItem">保存</NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>

    <!-- ====== Versions modal ====== -->
    <NModal v-model:show="showVersionsModal" title="版本历史">
      <NCard style="width: 500px;" size="small">
        <NDataTable
          :columns="[
            { title: '版本', key: 'version_num', width: 60 },
            { title: '时间', key: 'created_at', width: 180 },
            { title: '操作', key: 'action', render: (row) => h(NButton, { size: 'tiny', onClick: () => doRollback(row.version_num) }, () => '回滚'), width: 80 },
          ]"
          :data="versions"
          size="small"
          :max-height="300"
        />
      </NCard>
    </NModal>

  </div>
</template>

<style scoped>
h3 { margin: 0; }
</style>
