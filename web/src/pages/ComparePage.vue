<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api, unwrap } from '@/api/client'
import RiskCoverageChart, { type Curve } from '@/components/RiskCoverageChart.vue'
import { num, pct, usd } from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

const route = useRoute()
const ids = computed(() =>
  String(route.query.runs ?? '')
    .split(',')
    .filter(Boolean)
    .slice(0, 3),
)

const { data: runs, error } = useAsync(
  () => ids.value.join(','),
  () =>
    Promise.all(
      ids.value.map((id) => unwrap(api.GET('/api/runs/{run_id}', { params: { path: { run_id: id } } }))),
    ),
)

// Order follows the selection, so each run keeps its color however the list is filtered.
const curves = computed<Curve[]>(() =>
  (runs.value ?? []).map((r) => ({
    name: r.summary.config_name,
    points: (r.metrics as { selective?: { curve?: Curve['points'] } }).selective?.curve ?? [],
  })),
)
</script>

<template>
  <div class="space-y-6">
    <RouterLink to="/" class="text-sm text-ink-3 hover:text-ink-1">← Runs</RouterLink>
    <h1 class="text-2xl font-semibold tracking-tight">Compare risk–coverage</h1>
    <p v-if="error" class="card p-4 text-sm text-critical">{{ error }}</p>
    <template v-if="runs">
      <section class="card p-4">
        <p class="text-xs text-ink-3">
          Lower is better. A curve that stays flat near zero for longer lets more prices go on screens without
          review.
        </p>
        <RiskCoverageChart :curves="curves" />
      </section>
      <section class="card overflow-x-auto">
        <table class="data">
          <thead>
            <tr>
              <th>Config</th>
              <th>Split</th>
              <th class="text-right">Pair F1</th>
              <th class="text-right">AURC</th>
              <th class="text-right">ECE</th>
              <th class="text-right">Auto-placed</th>
              <th class="text-right">Wrong among auto</th>
              <th class="text-right">Wrong links</th>
              <th class="text-right">$/menu</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs" :key="r.summary.run_id">
              <td class="font-medium">
                <RouterLink
                  :to="{ name: 'run', params: { runId: r.summary.run_id } }"
                  class="hover:underline"
                >
                  {{ r.summary.config_name }}
                </RouterLink>
              </td>
              <td class="text-ink-2">{{ r.summary.split }}</td>
              <td class="num text-right">{{ pct(r.summary.pair_f1) }}</td>
              <td class="num text-right">{{ num(r.summary.aurc, 3) }}</td>
              <td class="num text-right">{{ num(r.summary.ece, 3) }}</td>
              <td class="num text-right">{{ pct(r.summary.auto_recall) }}</td>
              <td class="num text-right">{{ pct(r.summary.auto_risk) }}</td>
              <td class="num text-right">{{ pct(r.summary.wrong_link_rate) }}</td>
              <td class="num text-right">{{ usd(r.summary.per_menu_usd) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
