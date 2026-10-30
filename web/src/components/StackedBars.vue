<script setup lang="ts">
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'

use([BarChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export interface BarSeries {
  name: string
  /** CSS custom property with the series color, e.g. `--series-1`. */
  token: string
  values: number[]
}

const props = defineProps<{ days: string[]; series: BarSeries[]; format: (v: number) => string }>()

const tokens = ref<Record<string, string>>({})
let media: MediaQueryList | undefined
function readTokens() {
  const css = getComputedStyle(document.documentElement)
  const names = [
    '--ink-2',
    '--ink-3',
    '--line',
    '--axis',
    '--surface-1',
    '--ink-1',
    ...props.series.map((s) => s.token),
  ]
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
  const labels = props.days.map((d) =>
    new Date(`${d}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
  )
  return {
    animation: false,
    grid: { left: 64, right: 12, top: 12, bottom: 28 },
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(127,127,127,0.08)' } },
      backgroundColor: t['--surface-1'],
      borderColor: t['--line'],
      textStyle: { color: t['--ink-1'], fontSize: 12 },
      valueFormatter: (v: number) => (v ? props.format(v) : '–'),
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: t['--axis'] } },
      axisTick: { show: false },
      axisLabel: { color: t['--ink-3'], fontSize: 11, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: t['--ink-3'], fontSize: 11, formatter: (v: number) => props.format(v) },
      splitLine: { lineStyle: { color: t['--line'] } },
    },
    series: props.series.map((s) => ({
      name: s.name,
      type: 'bar',
      stack: 'total',
      barMaxWidth: 28,
      data: s.values.map((v) => v || null),
      // A thin surface-colored edge separates stacked segments.
      itemStyle: { color: t[s.token], borderColor: t['--surface-1'], borderWidth: 1 },
      emphasis: { focus: 'series' },
    })),
  }
})
</script>

<template>
  <div>
    <!-- vue-echarts ships unlayered height: 100%, which beats Tailwind utilities: size the wrapper instead. -->
    <div class="h-64"><VChart :option="option" autoresize /></div>
    <ul class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      <li v-for="s in series" :key="s.name" class="flex items-center gap-1.5">
        <span class="h-2.5 w-2.5 rounded-sm" :style="{ background: `var(${s.token})` }" aria-hidden="true" />
        {{ s.name }}
      </li>
    </ul>
  </div>
</template>
