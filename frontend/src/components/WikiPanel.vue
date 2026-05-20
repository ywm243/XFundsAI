<script setup>
import { ref } from 'vue'
import { NInput, NButton, NTag, NEmpty, NSpin } from 'naive-ui'
import { wikiSearch, wikiGetPage } from '../api.js'
import { Search, ArrowLeft, BookOpen, Tag } from 'lucide-vue-next'

const keyword = ref('')
const results = ref([])
const currentPage = ref(null)
const loading = ref(false)

async function handleSearch() {
  if (!keyword.value.trim()) return
  loading.value = true
  results.value = []
  currentPage.value = null
  try {
    const res = await wikiSearch(keyword.value.trim())
    results.value = res.results || []
  } catch { results.value = [] }
  loading.value = false
}

async function handleOpen(slug) {
  loading.value = true
  try {
    const res = await wikiGetPage(slug)
    currentPage.value = res.data || null
  } catch { currentPage.value = null }
  loading.value = false
}

function goBack() {
  currentPage.value = null
}

function typeColor(t) {
  const m = { concept: 'info', entity: 'success', reference: 'warning', synthesis: 'error', source: 'default' }
  return m[t] || 'default'
}
</script>

<template>
  <div class="wiki-panel">
    <template v-if="currentPage">
      <div class="wiki-back">
        <NButton text size="small" @click="goBack">
          <ArrowLeft :size="14" /> 返回搜索
        </NButton>
      </div>
      <h3 class="wiki-page-title">{{ currentPage.title }}</h3>
      <NTag :type="typeColor(currentPage.type)" size="small" style="margin-bottom: 8px">
        {{ currentPage.type }}
      </NTag>
      <div class="wiki-body">{{ currentPage.body }}</div>
      <div v-if="currentPage.tags?.length" class="wiki-tags">
        <Tag :size="11" />
        <NTag v-for="t in currentPage.tags" :key="t" size="small" style="margin: 1px">{{ t }}</NTag>
      </div>
    </template>
    <template v-else>
      <NInput v-model:value="keyword" placeholder="搜索知识库..." @keyup.enter="handleSearch" />
      <NButton type="primary" size="small" block style="margin-top: 8px" @click="handleSearch" :loading="loading">
        <Search :size="14" /> 搜索
      </NButton>
      <NSpin :show="loading" style="margin-top: 12px">
        <NEmpty v-if="results.length === 0 && !loading" description="输入关键词搜索" />
        <div v-else class="wiki-results">
          <div v-for="r in results" :key="r.slug" class="wiki-result-item" @click="handleOpen(r.slug)">
            <div class="wiki-result-header">
              <BookOpen :size="14" />
              <strong>{{ r.title }}</strong>
              <NTag :type="typeColor(r.type)" size="tiny">{{ r.type }}</NTag>
            </div>
            <div class="wiki-result-snippet">{{ r.body?.slice(0, 120) }}...</div>
          </div>
        </div>
      </NSpin>
    </template>
  </div>
</template>

<style scoped>
.wiki-panel { padding: 0; }
.wiki-back { margin-bottom: 12px; }
.wiki-page-title {
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text-primary);
}
.wiki-body {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin-top: 10px;
}
.wiki-tags {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  color: var(--text-muted);
}
.wiki-results { margin-top: 8px; }
.wiki-result-item {
  padding: 10px;
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: background 0.15s;
}
.wiki-result-item:hover { background: var(--bg-hover); }
.wiki-result-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
}
.wiki-result-snippet {
  color: var(--text-muted);
  font-size: 11px;
  margin-top: 4px;
  padding-left: 20px;
  line-height: 1.5;
}
</style>
