<script setup>
import { NLayoutHeader, NTag, NSpace } from 'naive-ui'

defineProps({
  status: { type: String, default: 'checking' },
})
</script>

<template>
  <NLayoutHeader class="status-header">
    <span style="font-size: 18px; font-weight: 600;">SmartBI</span>
    <NSpace align="center" :size="6">
      <NTag
        :type="status === 'connected' ? 'success' : status === 'checking' ? 'warning' : 'error'"
        :bordered="false"
        size="small"
        round
      >
        {{ status === 'connected' ? '已连接' : status === 'checking' ? '检查连接...' : '无法连接到服务器' }}
      </NTag>
    </NSpace>
  </NLayoutHeader>
</template>

<style scoped>
.status-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-sidebar);
}
</style>
