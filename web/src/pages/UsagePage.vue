<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, unwrap } from '@/api/client'
import MetricTile from '@/components/MetricTile.vue'
import StackedBars, { type BarSeries } from '@/components/StackedBars.vue'
import { shortModel } from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

const range = ref(30)
const { data, error, loading } = useAsync(
  () => range.value,
  () => unwrap(api.GET('/api/usage', { params: { query: { days: range.value } } })),
)

const money = (v: number) =>
  v === 0 ? '$0' : v >= 1 ? `$${v.toFixed(2)}` : v >= 0.01 ? `$${v.toFixed(3)}` : `$${v.toFixed(4)}`
const count = (v: number) =>
  v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}K` : String(Math.round(v))
const tokens = (v: number) =>
  v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(Math.round(v))

// Five most expensive models keep their own color, the rest fold into "Other", as in fixed-order palettes.
const TOP = 5
const top = computed(() => (data.value?.models ?? []).slice(0, TOP))
function perModel(metric: string): BarSeries[] {
  const d = data.value
  if (!d) return []
  const day = (date: string) => d.series[date] ?? {}
  const series: BarSeries[] = top.value.map((m, i) => ({
    name: shortModel(m),
    token: `--series-${i + 1}`,
    values: d.days.map((date) => day(date)[m]?.[metric] ?? 0),
  }))
  const rest = d.models.slice(TOP)
  if (rest.length) {
    series.push({
      name: 'Other',
      token: '--series-other',
      values: d.days.map((date) => rest.reduce((sum, m) => sum + (day(date)[m]?.[metric] ?? 0), 0)),
    })
  }
  return series
}
function total(metric: string): number[] {
  const d = data.value
  if (!d) return []
  return d.days.map((date) => Object.values(d.series[date] ?? {}).reduce((s, v) => s + (v[metric] ?? 0), 0))
}

const spend = computed(() => perModel('cost_usd'))
const requests = computed(() => perModel('requests'))
const tokenBreakdown = computed<BarSeries[]>(() => [
  { name: 'Prompt', token: '--series-1', values: total('prompt_tokens') },
  { name: 'Completion', token: '--series-2', values: total('completion_tokens') },
  { name: 'Reasoning', token: '--series-3', values: total('reasoning_tokens') },
])
const caching = computed<BarSeries[]>(() => [
  { name: 'Paid calls', token: '--series-1', values: total('requests') },
  { name: 'Served from the local cache', token: '--series-3', values: total('cache_hits') },
])
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)
const tiles = computed(() => ({
  spend: sum(total('cost_usd')),
  requests: sum(total('requests')),
  hits: sum(total('cache_hits')),
  saved: sum(total('saved_usd')),
  providerCached: sum(total('provider_cached_tokens')),
  prompt: sum(total('prompt_tokens')),
}))
const num = (row: Record<string, unknown>, key: string) => Number(row[key] ?? 0)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Usage</h1>
        <p class="mt-1 text-sm text-ink-3">
          Every model call made from this machine: benchmark runs, the demo and pre-labelling. Calls answered
          by the local cache cost nothing and are counted as savings.
        </p>
      </div>
      <div class="flex rounded-md border border-line p-0.5 text-xs" role="radiogroup" aria-label="Range">
        <button
          v-for="d in [7, 30, 90]"
          :key="d"
          role="radio"
          :aria-checked="range === d"
          class="rounded px-2 py-1"
          :class="range === d ? 'bg-surface-2 text-ink-1' : 'text-ink-3 hover:text-ink-1'"
          @click="range = d"
        >
          {{ d }} days
        </button>
      </div>
    </div>

    <p v-if="error" class="card p-4 text-sm text-critical">{{ error }}</p>
    <p v-else-if="loading && !data" class="text-sm text-ink-3">Loading…</p>

    <template v-if="data">
      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricTile label="Spend" :value="money(tiles.spend)" :hint="`last ${range} days`" />
        <MetricTile label="Paid calls" :value="count(tiles.requests)" />
        <MetricTile
          label="From the local cache"
          :value="count(tiles.hits)"
          :hint="`${money(tiles.saved)} not spent`"
        />
        <MetricTile
          label="Provider prompt cache"
          :value="tiles.prompt ? `${((tiles.providerCached / tiles.prompt) * 100).toFixed(1)}%` : '–'"
          hint="of prompt tokens"
        />
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="card p-4 lg:col-span-2">
          <h2 class="text-sm font-semibold">Spend by model</h2>
          <StackedBars :days="data.days" :series="spend" :format="money" />
        </section>
        <section class="card p-4">
          <h2 class="text-sm font-semibold">Requests by model</h2>
          <StackedBars :days="data.days" :series="requests" :format="count" />
        </section>
        <section class="card p-4">
          <h2 class="text-sm font-semibold">Token breakdown</h2>
          <StackedBars :days="data.days" :series="tokenBreakdown" :format="tokens" />
        </section>
        <section class="card p-4 lg:col-span-2">
          <h2 class="text-sm font-semibold">Local response cache</h2>
          <p class="text-xs text-ink-3">
            Replays and repeated runs are answered from the cache: free and offline.
          </p>
          <StackedBars :days="data.days" :series="caching" :format="count" />
        </section>
      </div>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="card overflow-x-auto">
          <h2 class="px-4 pt-4 text-sm font-semibold">By model</h2>
          <table class="data mt-2">
            <thead>
              <tr>
                <th>Model</th>
                <th class="text-right">Spend</th>
                <th class="text-right">Calls</th>
                <th class="text-right">Tokens in / out</th>
                <th class="text-right">Avg latency</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in data.by_model" :key="String(row.model)">
                <td class="font-medium">{{ shortModel(String(row.model)) }}</td>
                <td class="num text-right">{{ money(num(row, 'cost_usd')) }}</td>
                <td class="num text-right">{{ count(num(row, 'requests')) }}</td>
                <td class="num text-right">
                  {{ tokens(num(row, 'prompt_tokens')) }} /
                  {{ tokens(num(row, 'completion_tokens') + num(row, 'reasoning_tokens')) }}
                </td>
                <td class="num text-right">
                  {{ row.avg_latency_s != null ? `${Number(row.avg_latency_s).toFixed(1)} s` : '–' }}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="card overflow-x-auto">
          <h2 class="px-4 pt-4 text-sm font-semibold">By source</h2>
          <p class="px-4 text-xs text-ink-3">
            Run configs, the demo and pre-labelling; “history” is spend from before the call journal existed.
          </p>
          <table class="data mt-2">
            <thead>
              <tr>
                <th>Source</th>
                <th class="text-right">Spend</th>
                <th class="text-right">Paid calls</th>
                <th class="text-right">From cache</th>
                <th class="text-right">Saved</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in data.by_source" :key="String(row.source)">
                <td class="font-medium">{{ row.source }}</td>
                <td class="num text-right">{{ money(num(row, 'cost_usd')) }}</td>
                <td class="num text-right">{{ count(num(row, 'requests')) }}</td>
                <td class="num text-right">{{ count(num(row, 'cache_hits')) }}</td>
                <td class="num text-right">{{ money(num(row, 'saved_usd')) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>
  </div>
</template>
