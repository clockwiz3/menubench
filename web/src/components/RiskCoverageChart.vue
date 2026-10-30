<script setup lang="ts">
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export interface CurvePoint {
  coverage: number
  risk: number
  threshold: number
}
export interface Curve {
  name: string
  points: CurvePoint[]
}

const props = defineProps<{ curves: Curve[] }>()

// Colors follow the series' position in the given list; callers keep that order stable across filters.
const SLOTS = ['--series-1', '--series-2', '--series-3']
const tokens = ref<Record<string, string>>({})
let media: MediaQueryList | undefined

function readTokens() {
  const css = getComputedStyle(document.documentElement)
  const names = [...SLOTS, '--ink-2', '--ink-3', '--line', '--axis', '--surface-1', '--ink-1']
  tokens.value = Object.fromEntries(names.map((n) => [n, css.getPropertyValue(n).trim()]))
}
const themeObserver = new MutationObserver(readTokens)
onMounted(() => {
  readTokens()
  media = window.matchMedia('(prefers-color-scheme: dark)')
  media.addEventListener('change', readTokens)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})
onBeforeUnmount(() => {
  media?.removeEventListener('change', readTokens)
  themeObserver.disconnect()
})

const option = computed(() => {
  const t = tokens.value
  const axis = {
    axisLine: { lineStyle: { color: t['--axis'] } },
    axisTick: { show: false },
    axisLabel: { color: t['--ink-3'], fontSize: 11 },
    splitLine: { lineStyle: { color: t['--line'] } },
    nameTextStyle: { color: t['--ink-3'], fontSize: 11 },
  }
  return {
    animation: false,
    grid: { left: 52, right: 20, top: props.curves.length > 1 ? 36 : 16, bottom: 44 },
    legend: {
      show: props.curves.length > 1,
      top: 0,
      left: 0,
      icon: 'roundRect',
      textStyle: { color: t['--ink-2'], fontSize: 12 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t['--surface-1'],
      borderColor: t['--line'],
      textStyle: { color: t['--ink-1'], fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: t['--axis'] } },
      valueFormatter: (v: number) => `${(v * 100).toFixed(1)}% risk`,
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: 'coverage — share of predictions kept, most confident first',
      nameLocation: 'middle',
      nameGap: 28,
      ...axis,
      axisLabel: { ...axis.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
    },
    yAxis: {
      type: 'value',
      min: 0,
      name: 'risk (errors among kept)',
      nameLocation: 'middle',
      nameGap: 40,
      ...axis,
      axisLabel: { ...axis.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
    },
    series: props.curves.slice(0, SLOTS.length).map((curve, i) => ({
      name: curve.name,
      type: 'line',
      step: 'end',
      showSymbol: false,
      lineStyle: { width: 2, color: t[SLOTS[i]!] },
      itemStyle: { color: t[SLOTS[i]!] },
      data: curve.points.map((p) => [p.coverage, p.risk]),
    })),
  }
})
</script>

<template>
  <div class="h-72"><VChart :option="option" autoresize /></div>
</template>
