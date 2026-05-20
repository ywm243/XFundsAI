<script setup>
import { ref } from 'vue'
import { NModal, NCheckbox, NButton, NSpace } from 'naive-ui'
import { AlertTriangle } from 'lucide-vue-next'

const props = defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: '风险提示' },
  items: { type: Array, default: () => ['请谨慎交易'] },
})

const emit = defineEmits(['confirm', 'cancel'])
const agreed = ref(false)
</script>

<template>
  <NModal :show="show" :mask-closable="false" title="">
    <div class="risk-modal">
      <h3 class="risk-title"><AlertTriangle :size="17" /> {{ title }}</h3>
      <ul class="risk-items">
        <li v-for="item in items" :key="item">{{ item }}</li>
      </ul>
      <NCheckbox v-model:checked="agreed">
        我已了解上述风险，确认交易
      </NCheckbox>
      <NSpace justify="end" style="margin-top: 16px">
        <NButton @click="emit('cancel')">取消</NButton>
        <NButton type="error" :disabled="!agreed" @click="emit('confirm')">
          确认交易
        </NButton>
      </NSpace>
    </div>
  </NModal>
</template>

<style scoped>
.risk-modal {
  padding: 8px;
  max-width: 420px;
}
.risk-title {
  color: var(--text-primary);
  font-size: 16px;
  margin-bottom: 12px;
}
.risk-items {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 2;
  padding-left: 20px;
  margin-bottom: 16px;
}
</style>
