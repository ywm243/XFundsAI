<script setup>
import { NCard, NSpin, NAlert, NText } from 'naive-ui'
import ConfirmCard from './ConfirmCard.vue'
import ResultPanel from './ResultPanel.vue'
import ResultCard from './ResultCard.vue'

defineProps({
  message: { type: Object, required: true },
})

defineEmits(['confirm', 'reset', 'quickQuery'])
</script>

<template>
  <div style="display: flex; justify-content: flex-start;">
    <NCard
      style="max-width: 85%; border-bottom-left-radius: 4px;"
      size="small"
    >
      <!-- Loading -->
      <template v-if="message.mode === 'loading'">
        <div style="display: flex; align-items: center; gap: 8px;">
          <NSpin :size="16" />
          <NText depth="3">思考中...</NText>
        </div>
      </template>

      <!-- Error -->
      <template v-else-if="message.mode === 'error'">
        <NAlert type="error" :bordered="false">
          {{ message.error }}
        </NAlert>
      </template>

      <!-- Confirm -->
      <template v-else-if="message.mode === 'confirm'">
        <NText depth="3" style="font-size: 13px;">已解析查询条件，请确认：</NText>
        <ConfirmCard
          :params="message.params"
          :pipeline="message.pipeline"
          :original-text="message.originalText"
          :querying="message.querying"
          :resetting="message.resetting"
          @confirm="(p) => $emit('confirm', p)"
          @reset="$emit('reset')"
        />
      </template>

      <!-- Analysis -->
      <template v-else-if="message.mode === 'analysis'">
        <div style="font-size:14px; line-height:1.8; white-space:pre-wrap;">{{ message.text }}</div>
      </template>

      <!-- Result Card (4-section) -->
      <template v-else-if="message.mode === 'result_card'">
        <ResultCard :data="message.data" @quick-query="(q) => $emit('quickQuery', q)" />
      </template>

      <!-- Result -->
      <template v-else-if="message.mode === 'result'">
        <ResultPanel :data="message.data" />
      </template>
    </NCard>
  </div>
</template>
