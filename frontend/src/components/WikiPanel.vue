<script setup>
import { ref } from 'vue'
import { NInput, NButton, NTag, NEmpty, NSpin } from 'naive-ui'
import { wikiSearch, wikiGetPage } from '../api.js'

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
        <NButton text size="small" @click="goBack">&larr; 返回搜索</NButton>
      </div>
      <h3>{{ currentPage.title }}</h3>
      <NTag :type="typeColor(currentPage.type)" size="small" style="margin-bottom: 8px">
        {{ currentPage.type }}
      </NTag>
      <div class="wiki-body">{{ currentPage.body }}</div>
      <div v-if="currentPage.tags?.length" style="margin-top: 8px">
        <NTag v-for="t in currentPage.tags" :key="t" size="small" style="margin: 2px">{{ t }}</NTag>
      </div>
    </template>
    <template v-else>
      <NInput v-model:value="keyword" placeholder="搜索知识库..." @keyup.enter="handleSearch" />
      <NButton type="primary" size="small" style="margin-top: 8px" @click="handleSearch" :loading="loading">搜索</NButton>
      <NSpin :show="loading" style="margin-top: 12px">
        <NEmpty v-if="results.length === 0 && !loading" description="输入关键词搜索" />
        <div v-else class="wiki-results">
          <div v-for="r in results" :key="r.slug" class="wiki-result-item" @click="handleOpen(r.slug)">
            <strong>{{ r.title }}</strong>
            <NTag :type="typeColor(r.type)" size="tiny" style="margin-left: 6px">{{ r.type }}</NTag>
            <div class="wiki-result-snippet">{{ r.body?.slice(0, 120) }}...</div>
          </div>
        </div>
      </NSpin>
    </template>
  </div>
</template>

<style scoped>
.wiki-panel { padding: 12px; }
.wiki-back { margin-bottom: 8px; }
.wiki-body { white-space: pre-wrap; font-size: 14px; line-height: 1.6; }
.wiki-results { margin-top: 8px; }
.wiki-result-item { padding: 8px; cursor: pointer; border-radius: 4px; }
.wiki-result-item:hover { background: #f0f0f0; }
.wiki-result-snippet { color: #888; font-size: 12px; margin-top: 4px; }
</style>
