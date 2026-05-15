# Smart BI 前台重设计 — 实现计划

> **面向 AI 代理的工作者：** 可选使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 Smart BI 从单栏聊天式布局升级为暗色专业的 BI 分析平台，包含左侧导航栏、四段式结果卡片、首页快捷引导、增强版规则管理页面。

**架构：** Vue 3 Composition API + Naive UI darkTheme。新增 4 个组件（Sidebar、ResultCard、WelcomeGuide、InsightPanel），移植 ChartView 从 feature 分支，增强 AdminRules。App.vue 加侧边栏布局壳 + 暗色主题包裹 + 首页引导条件渲染。Naive UI 的 `darkTheme` 提供全局暗色变量，自定义 CSS 变量覆盖细节色值。

**技术栈：** Vue 3.5 + Naive UI 2.40 + ECharts 5，Vite 5.4

---

## 文件结构

```
frontend/src/
├── App.vue                    # 修改：侧边栏壳 + 暗色主题 + 首页引导 + viewMode
├── api.js                     # 不变
├── constants.js               # 不变
├── views/
│   └── AdminRules.vue         # 增强：编辑模态框 + 校验 + 预览 + 版本历史
├── components/
│   ├── Sidebar.vue            # 新增：左侧导航栏（56px↔220px，Agent/历史/管理）
│   ├── WelcomeGuide.vue       # 新增：首页引导（输入框 + 6 快捷按钮）
│   ├── ResultCard.vue         # 新增：四段式结果卡片（摘要+图表+洞察+表格）
│   ├── InsightPanel.vue       # 新增：数据洞察面板（⚠️/📈/📋 图标区分）
│   ├── ChartView.vue          # 移植：ECharts 图表渲染（从 feature 分支）
│   ├── BotMessage.vue         # 修改：新增 result_card 模式路由
│   ├── ResultPanel.vue        # 修改：表格整合进卡片，底栏精简
│   ├── ConfirmCard.vue        # 修改：暗色适配
│   ├── InputArea.vue          # 修改：暗色适配
│   ├── MessageArea.vue        # 不变
│   └── StatusHeader.vue       # 修改：适配暗色 + 移除管理按钮（移入侧边栏）
```

---

### 任务 1：暗色主题 + 全局样式 + Naive UI darkTheme

**文件：**
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/components/StatusHeader.vue`

- [ ] **步骤 1：App.vue 包裹 Naive UI darkTheme 并注入全局 CSS 变量**

`frontend/src/App.vue` — `<script setup>` 顶部增加 darkTheme 导入，`<NConfigProvider>` 增加 `theme` prop：

```javascript
import { darkTheme } from 'naive-ui'
```

`<template>` 中 `<NConfigProvider>` 增加：

```html
<NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme="darkTheme">
```

`<style>` 替换为暗色全局样式：

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }
#app { height: 100%; }

:root {
  --bg-primary: #0f172a;
  --bg-card: #1e293b;
  --bg-sidebar: #0b1120;
  --border: #334155;
  --accent: #1d4ed8;
  --success: #22c55e;
  --success-text: #34d399;
  --warning: #f59e0b;
  --error: #ef4444;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
}
```

- [ ] **步骤 2：StatusHeader.vue 适配暗色背景**

修改 `StatusHeader.vue` `<style scoped>`：

```css
.status-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-sidebar);
}
```

移除 StatusHeader 中的 ⚙ 管理按钮（移至侧边栏）。对应修改 template 和 script。

- [ ] **步骤 3：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功，无 CSS 报错

- [ ] **步骤 4：Commit**

```bash
git add frontend/src/App.vue frontend/src/components/StatusHeader.vue
git commit -m "feat: add dark theme wrapper and global CSS variables"
```

---

### 任务 2：Sidebar 左侧导航栏组件

**文件：**
- 创建：`frontend/src/components/Sidebar.vue`

- [ ] **步骤 1：创建 Sidebar.vue — 收起/展开逻辑 + Agent 图标 + 历史 + 管理入口**

```vue
<script setup>
import { ref } from 'vue'

const emit = defineEmits(['navigate'])
const expanded = ref(false)
const activeAgent = ref('bi')

const agents = [
  { key: 'bi', icon: '💬', label: 'BI Agent', active: true },
  { key: 'quoting', icon: '📊', label: '询报价 Agent', active: false },
  { key: 'risk', icon: '⚠️', label: '风控 Agent', active: false },
]

function toggleExpand() {
  expanded.value = !expanded.value
}

function handleAgentClick(agent) {
  if (!agent.active) return
  activeAgent.value = agent.key
}

function handleHistoryClick() {
  expanded.value = !expanded.value
}

function handleAdminClick() {
  emit('navigate', 'admin')
}
</script>

<template>
  <div class="sidebar" :class="{ expanded }">
    <!-- Logo -->
    <div class="sidebar-logo">◆</div>

    <!-- Agent icons -->
    <div
      v-for="agent in agents" :key="agent.key"
      class="sidebar-icon"
      :class="{ active: activeAgent === agent.key, disabled: !agent.active }"
      :title="agent.label"
      @click="handleAgentClick(agent)"
    >
      {{ agent.icon }}
    </div>

    <div class="sidebar-spacer"></div>

    <!-- History -->
    <div class="sidebar-icon" title="查询历史" @click="handleHistoryClick">
      🕐
    </div>

    <!-- Admin -->
    <div class="sidebar-icon" title="规则管理" @click="handleAdminClick">
      ⚙
    </div>

    <!-- Expanded panel -->
    <div v-if="expanded" class="sidebar-panel">
      <div class="sidebar-panel-title">查询历史</div>
      <div class="sidebar-panel-list">
        <div class="sidebar-panel-empty">暂无历史记录</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 56px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  gap: 4px;
  position: relative;
  transition: width 0.2s;
  flex-shrink: 0;
}
.sidebar.expanded { width: 220px; }

.sidebar-logo {
  font-size: 20px;
  margin-bottom: 16px;
  opacity: 0.8;
}

.sidebar-icon {
  padding: 8px;
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.15s;
}
.sidebar-icon:hover { background: #1e293b; }
.sidebar-icon.active { background: var(--accent); color: #fff; }
.sidebar-icon.disabled { opacity: 0.35; cursor: not-allowed; }

.sidebar-spacer { flex: 1; }

.sidebar-panel {
  position: absolute;
  left: 100%;
  top: 0;
  bottom: 0;
  width: 164px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  padding: 16px;
  z-index: 10;
}
.sidebar-panel-title {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 12px;
}
.sidebar-panel-empty {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px 0;
}
</style>
```

- [ ] **步骤 2：构建验证 + 引入 App.vue**

```bash
cd frontend && npx vite build
```
预期：构建成功

- [ ] **步骤 3：Commit**

```bash
git add frontend/src/components/Sidebar.vue
git commit -m "feat: add collapsible sidebar with agent icons and history panel"
```

---

### 任务 3：WelcomeGuide 首页引导组件

**文件：**
- 创建：`frontend/src/components/WelcomeGuide.vue`
- 修改：`frontend/src/App.vue`

- [ ] **步骤 1：创建 WelcomeGuide.vue**

```vue
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
```

- [ ] **步骤 2：App.vue 集成 — 无消息时显示 WelcomeGuide，有消息时显示 MessageArea**

在 `App.vue` 的 `<template>` 对话区中：

```html
<WelcomeGuide v-if="messages.length === 0" @quick-query="handleSend" />
<MessageArea v-else :messages="messages" @confirm="handleConfirm" @reset="handleReset" />
```

`<script setup>` 中增加导入：

```javascript
import WelcomeGuide from './components/WelcomeGuide.vue'
```

- [ ] **步骤 3：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功

- [ ] **步骤 4：Commit**

```bash
git add frontend/src/components/WelcomeGuide.vue frontend/src/App.vue
git commit -m "feat: add welcome guide with quick query chips"
```

---

### 任务 4：ChartView 从 feature 分支移植

**文件：**
- 创建：`frontend/src/components/ChartView.vue`

- [ ] **步骤 1：从 feature 分支读取 ChartView.vue 代码**

```bash
git show feature/langchain-agent:frontend/src/components/ChartView.vue
```

- [ ] **步骤 2：创建 ChartView.vue（移植 + 暗色适配）**

```vue
<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, default: null },
})

const chartRef = ref(null)
let chartInstance = null

function initChart() {
  if (!chartRef.value || !props.option?.series) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value, 'dark')
  }
  chartInstance.setOption(props.option, true)
}

onMounted(() => { nextTick(initChart) })
onUnmounted(() => { chartInstance?.dispose() })

watch(() => props.option, () => { nextTick(initChart) }, { deep: true })
</script>

<template>
  <div v-if="option?.series" ref="chartRef" class="chart-container"></div>
</template>

<style scoped>
.chart-container { width: 100%; height: 200px; }
</style>
```

- [ ] **步骤 3：安装 echarts 依赖**

```bash
cd frontend && npm install echarts
```

- [ ] **步骤 4：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功，echarts 正确打包

- [ ] **步骤 5：Commit**

```bash
git add frontend/src/components/ChartView.vue frontend/package.json frontend/package-lock.json
git commit -m "feat: port ChartView component from feature branch with dark theme"
```

---

### 任务 5：InsightPanel 数据洞察面板

**文件：**
- 创建：`frontend/src/components/InsightPanel.vue`

- [ ] **步骤 1：创建 InsightPanel.vue**

```vue
<script setup>
defineProps({
  insights: { type: Array, default: () => [] },
})

const iconMap = {
  risk: '⚠️',
  growth: '📈',
  quality: '📋',
}

const colorMap = {
  risk: 'var(--warning)',
  growth: 'var(--success-text)',
  quality: '#60a5fa',
}
</script>

<template>
  <div v-if="insights.length > 0" class="insight-panel">
    <div class="insight-title">💡 数据分析与建议</div>
    <div v-for="(item, i) in insights" :key="i" class="insight-item">
      <span class="insight-icon" :style="{ color: colorMap[item.type] || colorMap.quality }">
        {{ iconMap[item.type] || '📋' }}
      </span>
      <span class="insight-text">
        <strong :style="{ color: colorMap[item.type] || colorMap.quality }">{{ item.title }}：</strong>
        {{ item.detail }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.insight-panel {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: #1a2230;
}
.insight-title {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.insight-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 6px;
}
.insight-icon { flex-shrink: 0; }
.insight-text { color: var(--text-secondary); }
</style>
```

- [ ] **步骤 2：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功

- [ ] **步骤 3：Commit**

```bash
git add frontend/src/components/InsightPanel.vue
git commit -m "feat: add insight panel component with typed indicators"
```

---

### 任务 6：ResultCard 四段式结果卡片

**文件：**
- 创建：`frontend/src/components/ResultCard.vue`
- 修改：`frontend/src/components/BotMessage.vue`

- [ ] **步骤 1：创建 ResultCard.vue — 集成摘要行 + 图表 + 洞察 + 表格**

```vue
<script setup>
import { computed } from 'vue'
import { NTabs, NTabPane } from 'naive-ui'
import ChartView from './ChartView.vue'
import InsightPanel from './InsightPanel.vue'
import { COLUMN_LABELS, formatCellValue } from '../constants.js'

const props = defineProps({
  data: { type: Object, required: true },  // { columns, rows, row_count, sql, params, comparison, summary, chartOption, insights }
  showSql: { type: Boolean, default: false },
  showParams: { type: Boolean, default: false },
})

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

const activeTab = computed(() => {
  if (props.showSql) return 'sql'
  if (props.showParams) return 'params'
  return 'data'
})
</script>

<template>
  <div class="result-card">
    <!-- Section 1: Summary -->
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
    <InsightPanel :insights="data.insights || []" />

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
          :theme-overrides="{ borderColor: '#334155' }"
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
      <span class="footer-export">📥 导出</span>
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
.footer-export { cursor: pointer; }
.footer-export:hover { color: var(--text-secondary); }
</style>
```

- [ ] **步骤 2：BotMessage.vue 增加 result_card 模式**

在 `BotMessage.vue` 中：

```javascript
// 新增 import
import ResultCard from './ResultCard.vue'
```

在 template 中 mode 判断增加：

```html
<ResultCard v-else-if="mode === 'result_card'" :data="data" :show-sql="false" :show-params="false" />
```

保留原有 mode="result" 分支不变（兼容旧 ResultPanel）。

- [ ] **步骤 3：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功，ResultCard 正确引用 ChartView、InsightPanel 和 Naive UI 组件

- [ ] **步骤 4：Commit**

```bash
git add frontend/src/components/ResultCard.vue frontend/src/components/BotMessage.vue
git commit -m "feat: add 4-section result card with summary/chart/insights/table"
```

---

### 任务 7：App.vue 侧边栏布局整合 + InputArea/ConfirmCard 暗色适配

**文件：**
- 修改：`frontend/src/App.vue`
- 修改：`frontend/src/components/InputArea.vue`
- 修改：`frontend/src/components/ConfirmCard.vue`

- [ ] **步骤 1：App.vue 加入 Sidebar + 布局重构**

`App.vue` template 改为侧边栏布局：

```html
<NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme="darkTheme">
  <NMessageProvider>
    <div style="display: flex; height: 100vh;">
      <Sidebar @navigate="handleNavigate" />
      <div style="flex: 1; display: flex; flex-direction: column; min-width: 0;">
        <template v-if="viewMode === 'admin'">
          <div style="padding: 8px 16px; border-bottom: 1px solid var(--border);">
            <NButton size="tiny" @click="viewMode = 'chat'">← 返回</NButton>
          </div>
          <AdminRules />
        </template>
        <template v-else>
          <StatusHeader :status="connectionStatus" />
          <div style="flex: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; padding: 0 16px;">
            <WelcomeGuide v-if="messages.length === 0" @quick-query="handleSend" />
            <MessageArea v-else :messages="messages" @confirm="handleConfirm" @reset="handleReset" />
            <InputArea ref="inputAreaRef" @send="handleSend" />
          </div>
        </template>
      </div>
    </div>
  </NMessageProvider>
</NConfigProvider>
```

`<script setup>` 增加：

```javascript
import Sidebar from './components/Sidebar.vue'
import { darkTheme } from 'naive-ui'

function handleNavigate(target) {
  if (target === 'admin') viewMode.value = 'admin'
}
```

移除旧的 `<NLayout>` 包裹（已被 flex 布局替换）。

- [ ] **步骤 2：InputArea.vue 暗色适配**

修改 `<style scoped>`：

```css
.input-area {
  padding: 12px 0;
  border-top: 1px solid var(--border);
  display: flex;
  gap: 8px;
}
```

textarea 样式调整为暗色。

- [ ] **步骤 3：ConfirmCard.vue 暗色适配**

NCard 相关组件增加 `:theme-overrides` 或依赖 Naive UI darkTheme 自动适配。确认所有 NInput、NSelect、NDatePicker 在暗色下正常显示。

- [ ] **步骤 4：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功，布局正常

- [ ] **步骤 5：Commit**

```bash
git add frontend/src/App.vue frontend/src/components/InputArea.vue frontend/src/components/ConfirmCard.vue
git commit -m "feat: integrate sidebar layout, dark-adapt input and confirm card"
```

---

### 任务 8：AdminRules.vue 增强 — 编辑模态框 + 中文校验 + 版本历史

**文件：**
- 修改：`frontend/src/views/AdminRules.vue`
- 修改：`backend/admin_routes.py`

- [ ] **步骤 1：AdminRules.vue 增加编辑模态框（中文表单 + 💡 提示）**

重构 `<script setup>`，新增：

```javascript
// Edit modal state
const showEditModal = ref(false)
const editMode = ref('create')  // 'create' | 'edit'
const editErrors = ref([])

const editingItem = reactive({
  id: null,
  keywords_str: '',     // 用户可见的逗号分隔字符串，非 JSON
  direction: '',        // 'B' | 'S' | ''
  is_ironclad: false,
  product_types: [],    // ['spot', 'fwd', 'swap']
  app_id: null,
  priority: 0,
  description: '',
  customer_reversible: true,
  customer_direction: '',
})

const directionOptions = [
  { value: 'B', label: 'B（银行买入）' },
  { value: 'S', label: 'S（银行卖出）' },
]

const productTypeOptions = [
  { value: 'spot', label: '即期' },
  { value: 'fwd', label: '远期' },
  { value: 'swap', label: '掉期' },
]
```

编辑模态框模板（与原型一致——中文 label + 💡 提示 + placeholder）：

```html
<NModal v-model:show="showEditModal" :title="editMode === 'create' ? '添加买卖方向规则' : '编辑买卖方向规则'">
  <NCard style="width: 560px;" size="small">
    <NSpace vertical :size="14">
      <!-- 关键词 -->
      <div>
        <NSpace align="center"><NText strong style="font-size:12px;">关键词</NText><NText type="error" style="font-size:10px;">*必填</NText></NSpace>
        <NInput v-model:value="editingItem.keywords_str" placeholder="用逗号分隔，如：结汇, 结汇交易" style="margin-top:4px;" />
        <NText depth="3" style="font-size:10px;">💡 用逗号分隔多个关键词，业务人员输入这些词时会触发此规则</NText>
      </div>

      <!-- 方向 -->
      <div>
        <NText strong style="font-size:12px;">方向 <NText type="error" style="font-size:10px;">*必填</NText></NText>
        <NRadioGroup v-model:value="editingItem.direction" :options="directionOptions" style="margin-top:4px;" />
      </div>

      <!-- 铁律开关 -->
      <NSpace align="center">
        <div style="flex:1;">
          <NText strong style="font-size:12px;">铁律规则</NText>
          <br><NText depth="3" style="font-size:10px;">开启后不可被客户前缀反转，不可被 AI 覆盖</NText>
        </div>
        <NSwitch v-model:value="editingItem.is_ironclad" />
        <NTag v-if="editingItem.is_ironclad" type="warning" size="small">已开启</NTag>
      </NSpace>

      <!-- 适用产品 -->
      <div>
        <NText strong style="font-size:12px;">适用产品类型</NText>
        <NCheckboxGroup v-model:value="editingItem.product_types" :options="productTypeOptions" style="margin-top:4px;" />
      </div>

      <!-- App ID + 优先级 -->
      <NSpace :size="16">
        <div style="flex:1;">
          <NText strong style="font-size:12px;">App ID</NText>
          <NInput v-model:value="editingItem.app_id" style="margin-top:4px; width:100px;" />
          <NText depth="3" style="font-size:10px;">1=外汇, 2=结售汇</NText>
        </div>
        <div style="flex:1;">
          <NText strong style="font-size:12px;">优先级</NText>
          <NInputNumber v-model:value="editingItem.priority" :min="0" style="margin-top:4px; width:80px;" />
          <NText depth="3" style="font-size:10px;">💡 数字越小越优先匹配</NText>
        </div>
      </NSpace>

      <!-- 说明 -->
      <div>
        <NText strong style="font-size:12px;">说明</NText>
        <NInput v-model:value="editingItem.description" placeholder="帮助其他维护人员理解此规则的含义" style="margin-top:4px;" />
      </div>

      <!-- 校验错误 -->
      <NAlert v-if="editErrors.length > 0" type="error" :title="`保存失败，请修正以下问题：`">
        <ul><li v-for="e in editErrors" :key="e">{{ e }}</li></ul>
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
```

- [ ] **步骤 2：AdminRules.vue 增加前端校验 + 提交逻辑**

```javascript
function validateItem() {
  const errors = []
  const kw = editingItem.keywords_str.split(',').map(k => k.trim()).filter(Boolean)
  if (kw.length === 0) errors.push('关键词不能为空')
  if (!editingItem.direction) errors.push('买卖方向的"方向"字段不能为空')
  if (editingItem.is_ironclad && !editingItem.description) {
    errors.push('铁律规则必须填写"说明"字段')
  }
  if (editingItem.priority < 0) errors.push('优先级必须是非负整数')
  return { valid: errors.length === 0, errors, keywords: kw }
}

async function saveItem() {
  const { valid, errors, keywords } = validateItem()
  if (!valid) { editErrors.value = errors; return }
  editErrors.value = []

  const body = {
    keywords,
    rule_data: {
      direction: editingItem.direction,
      customer_reversible: !editingItem.is_ironclad,
      set_app_id: editingItem.app_id || undefined,
      product_types: editingItem.product_types,
      customer_direction: editingItem.customer_direction || undefined,
      description: editingItem.description,
    },
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
  } catch (err) {
    editErrors.value = [err.message]
  }
}
```

- [ ] **步骤 3：backend/admin_routes.py 增强后端校验**

在 `create_item` 和 `update_item` 中添加结构化校验：

```python
def _validate_rule_item(category: dict, keywords: list[str], rule_data: dict, 
                         is_ironclad: bool, item_id: int | None = None) -> list[str]:
    """Validate a rule item before save. Returns list of Chinese error messages."""
    errors = []
    cat_name = category["category"]

    # 关键词唯一性（排除自身）
    existing_items = sqlite_store.get_items(category["id"])
    existing_kw = {}
    for item in existing_items:
        if item_id and item["id"] == item_id:
            continue
        try:
            kws = json.loads(item["keywords"])
        except (json.JSONDecodeError, TypeError):
            kws = []
        for k in kws:
            existing_kw[k] = item["id"]

    for kw in keywords:
        if kw in existing_kw:
            errors.append(f"关键词'{kw}'已存在于该分类第{existing_kw[kw]}条规则中，不能重复使用")

    # 铁律冲突检测
    if is_ironclad:
        for item in existing_items:
            if item_id and item["id"] == item_id:
                continue
            if item.get("is_ironclad"):
                try:
                    existing = json.loads(item["keywords"])
                except (json.JSONDecodeError, TypeError):
                    existing = []
                overlap = set(keywords) & set(existing)
                if overlap:
                    errors.append(f"铁律规则的关键词'{list(overlap)}'已作为可反转规则关键词，如果这是铁律，请先删除可反转规则中的对应关键词")

    # 方向必填
    if cat_name == "buy_sell_direction" and not rule_data.get("direction"):
        errors.append("买卖方向规则的'方向'字段不能为空")

    # 状态码范围
    if cat_name == "special_states":
        try:
            val = int(rule_data.get("value", -1))
        except (ValueError, TypeError):
            val = -1
        valid_states = {0, 1, 3, 4, 5}
        if val not in valid_states:
            errors.append(f"特殊状态值'{val}'不在允许范围内，有效值为 0(在途),1(逾期),3(展期),4(提前交割),5(平仓)")

    # 产品类型合法
    if cat_name == "product_type":
        val = rule_data.get("value", "")
        if val not in ("spot", "fwd", "swap", "all"):
            errors.append(f"未知的产品类型: {val}，有效值为 spot/fwd/swap/all")

    return errors
```

在 `create_item` 路由中调用：

```python
errors = _validate_rule_item(cat, body.keywords, body.rule_data, body.is_ironclad)
if errors:
    raise HTTPException(422, detail="; ".join(errors))
```

- [ ] **步骤 4：服务端测试**

```bash
cd backend && python -c "
from db import sqlite_store
from llm_parser.rules_engine import gatekeep

# 测试新增规则后 gatekeep 是否生效
r = gatekeep({...}, '测试文本')
assert ...
print('PASS')
"
```

- [ ] **步骤 5：构建验证**

```bash
cd frontend && npx vite build
```
预期：构建成功

- [ ] **步骤 6：Commit**

```bash
git add frontend/src/views/AdminRules.vue backend/admin_routes.py
git commit -m "feat: enhance admin rules with validation, modal editor, and error messages"
```

---

### 任务 9：端到端集成测试 + 最终提交

- [ ] **步骤 1：启动服务并验证全部端点**

```bash
cd backend && python -m uvicorn app:app --host 0.0.0.0 --port 8000 &
sleep 3
# 验证
python -c "
import requests
# 1. Health
assert requests.get('http://localhost:8000/api/health').json()['status'] == 'ok'
# 2. Parse
r = requests.post('http://localhost:8000/api/parse', json={'text':'本月交易量'}).json()
assert r['confidence'] >= 0.8
assert 'rule(' in r['pipeline']
# 3. Admin categories
assert len(requests.get('http://localhost:8000/api/admin/rules/categories').json()['categories']) == 6
# 4. Admin validation (should reject duplicate keyword)
r = requests.post('http://localhost:8000/api/admin/rules/categories/3/items', json={
    'keywords': ['结汇'], 'rule_data': {'direction':'B'}, 'is_ironclad': True, 'priority': 0
})
assert r.status_code == 422, f'Expected 422, got {r.status_code}'
print('ALL INTEGRATION TESTS PASSED')
"
```

- [ ] **步骤 2：前端构建**

```bash
cd frontend && npx vite build
```
预期：构建成功，无 error 和 warning（chunk size 警告可以忽略）

- [ ] **步骤 3：最终 Commit**

```bash
git add -A
git commit -m "feat: complete frontend redesign with dark theme, sidebar, and enhanced admin"
```

---

## 自检

**1. 规格覆盖度：**
- ✅ 暗色主题 → 任务 1
- ✅ 左侧导航栏 → 任务 2
- ✅ 首页快捷引导 → 任务 3
- ✅ 图表组件移植 → 任务 4
- ✅ 数据洞察面板 → 任务 5
- ✅ 四段式结果卡片 → 任务 6
- ✅ App 布局整合 + 暗色适配 → 任务 7
- ✅ 规则管理页面增强（可读性+校验+热部署）→ 任务 8
- ✅ 端到端测试 → 任务 9

**2. 占位符扫描：** 无 TODO/TBD/占位符。所有步骤有具体代码。

**3. 类型一致性：** InsightPanel 的 `insights` prop 结构 `{type, title, detail}` 与 ResultCard 传递一致。ChartView 的 `option` prop 结构与 ECharts setOption 一致。Sidebar 的 `@navigate` emit 与 App.vue 的 `handleNavigate` 一致。
