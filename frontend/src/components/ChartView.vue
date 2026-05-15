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
