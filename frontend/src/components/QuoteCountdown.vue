<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps({
  validUntil: { type: String, required: true },
})

const emit = defineEmits(['expired'])

const remaining = ref(0)
let timer = null

const minutes = computed(() => Math.floor(remaining.value / 60))
const seconds = computed(() => remaining.value % 60)
const display = computed(() =>
  `${String(minutes.value).padStart(2, '0')}:${String(seconds.value).padStart(2, '0')}`
)
const isUrgent = computed(() => remaining.value <= 30)

function tick() {
  const now = Date.now()
  const target = new Date(props.validUntil).getTime()
  remaining.value = Math.max(0, Math.floor((target - now) / 1000))
  if (remaining.value <= 0) {
    clearInterval(timer)
    emit('expired')
  }
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
})

onUnmounted(() => {
  clearInterval(timer)
})
</script>

<template>
  <div class="countdown" :class="{ urgent: isUrgent }">
    <span class="countdown-label">有效期</span>
    <span class="countdown-value">{{ display }}</span>
  </div>
</template>

<style scoped>
.countdown {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 6px;
  background: var(--gray-100);
  font-size: 13px;
}
.countdown-label {
  color: var(--text-muted);
}
.countdown-value {
  font-family: 'Consolas', monospace;
  font-weight: 600;
  color: var(--text-primary);
}
.countdown.urgent {
  background: var(--red-light);
}
.countdown.urgent .countdown-value {
  color: var(--error);
}
</style>
