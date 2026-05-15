<script setup>
import { ref, nextTick } from 'vue'
import { NInput, NButton } from 'naive-ui'

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
  <div style="padding: 16px 24px; border-top: 1px solid var(--border); display: flex; gap: 10px; background: var(--bg-card);">
    <NInput
      ref="inputRef"
      v-model:value="text"
      type="textarea"
      :autosize="{ minRows: 1, maxRows: 4 }"
      :placeholder="`输入自然语言查询，例如「上个月的销售数据」...`"
      :maxlength="2000"
      :disabled="disabled"
      @keydown="handleKeydown"
      style="flex: 1;"
    />
    <NButton
      type="primary"
      :disabled="disabled || !text.trim()"
      @click="handleSend"
      style="align-self: flex-end;"
    >
      发送
    </NButton>
  </div>
</template>
