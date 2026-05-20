<script setup>
import { ref, nextTick } from 'vue'
import { NInput, NButton } from 'naive-ui'
import { Send } from 'lucide-vue-next'

const emit = defineEmits(['send'])

defineProps({
  disabled: { type: Boolean, default: false },
})

const text = ref('')
const inputRef = ref(null)

function handleSend() {
  const trimmed = text.value.trim()
  if (!trimmed) return
  emit('send', trimmed)
  text.value = ''
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function focus() {
  nextTick(() => inputRef.value?.focus())
}

defineExpose({ focus })
</script>

<template>
  <div class="input-area">
    <div class="input-row">
      <NInput
        ref="inputRef"
        v-model:value="text"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 4 }"
        :placeholder="'输入查询，例如「本月各银行交易量排名」'"
        :maxlength="2000"
        :disabled="disabled"
        @keydown="handleKeydown"
        class="query-input"
      />
      <button
        class="send-btn"
        :disabled="disabled || !text.trim()"
        @click="handleSend"
        :title="'发送'"
      >
        <Send :size="17" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.input-area {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg-primary);
  flex-shrink: 0;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.query-input {
  flex: 1;
}
.send-btn {
  width: 40px;
  height: 36px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.18s ease;
  flex-shrink: 0;
}
.send-btn:hover:not(:disabled) {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent);
}
.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
</style>
