<script setup>
import { watch, ref, nextTick } from 'vue'
import { NScrollbar, NEmpty } from 'naive-ui'
import BotMessage from './BotMessage.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
})

const emit = defineEmits(['confirm', 'reset', 'quickQuery'])

const scrollbarRef = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (scrollbarRef.value) {
      const el = scrollbarRef.value.$el?.querySelector('.n-scrollbar-container')
      if (el) el.scrollTop = el.scrollHeight
    }
  })
}

watch(() => props.messages.length, scrollToBottom)
watch(() => props.messages, () => {
  // Check if last message just changed (e.g., loading → confirm)
  scrollToBottom()
}, { deep: true })
</script>

<template>
  <NScrollbar ref="scrollbarRef" style="flex: 1; padding: 20px 24px; background: var(--bg-primary);">
    <div
      v-if="messages.length === 0"
      style="display: flex; align-items: center; justify-content: center; height: 100%;"
    >
      <NEmpty :description="`输入自然语言查询，例如「上个月的销售数据」`" />
    </div>
    <div v-for="(msg, idx) in messages" :key="idx" style="margin-bottom: 16px;">
      <!-- User message -->
      <div v-if="msg.type === 'user'" style="display: flex; justify-content: flex-end;">
        <div class="user-bubble">{{ msg.text }}</div>
      </div>
      <!-- Bot message -->
      <BotMessage
        v-else
        :message="msg"
        @confirm="(params) => emit('confirm', params, idx)"
        @reset="emit('reset', idx)"
        @quick-query="(q) => emit('quickQuery', q)"
      />
    </div>
  </NScrollbar>
</template>

<style scoped>
.user-bubble {
  max-width: 85%;
  padding: 12px 16px;
  border-radius: 12px;
  border-bottom-right-radius: 4px;
  line-height: 1.5;
  font-size: 14px;
  word-wrap: break-word;
  background: var(--accent);
  color: #fff;
}
</style>
