<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, unwrap, type MenuRow } from '@/api/client'
import MetricTile from '@/components/MetricTile.vue'
import RiskCoverageChart, { type Curve } from '@/components/RiskCoverageChart.vue'
import { num, pct, seconds, shortModel, usd } from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

const props = defineProps<{ runId: string }>()
const router = useRouter()

const { data: run, error } = useAsync(
  () => props.runId,
  () => unwrap(api.GET('/api/runs/{run_id}', { params: { path: { run_id: props.runId } } })),
)

type Metrics = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
const m = computed<Metrics>(() => run.value?.metrics ?? {})
const s = computed(() => run.value?.summary)
const curves = computed<Curve[]>(() =>
  m.value.selective?.curve?.length
    ? [{ name: s.value?.config_name ?? '', points: m.value.selective.curve }]
    : [],
)

const sortKey = ref<keyof MenuRow>('errors')
const menus = computed(() =>
  [...(run.value?.menus ?? [])].sort((a, b) => {
    const k = sortKey.value
    const av = a[k] ?? 0
    const bv = b[k] ?? 0
    return typeof av === 'number' && typeof bv === 'number' ? bv - av : String(av).localeCompare(String(bv))
  }),
)
const slices = computed(() =>
  Object.entries((m.value.slices ?? {}) as Record<string, Record<string, Metrics>>),
)

function open(menu: MenuRow) {
  router.push({ name: 'review', params: { runId: props.runId, menuId: menu.menu_id } })
}
</script>

<template>
  <div class="space-y-6">
    <RouterLink to="/" class="text-sm text-ink-3 hover:text-ink-1">← Runs</RouterLink>
    <p v-if="error" class="card p-4 text-sm text-critical">{{ error }}</p>

    <template v-if="run && s">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">{{ s.config_name }}</h1>
        <p class="mt-1 text-sm text-ink-3">
          {{ s.pipeline }} ·
          {{
            Object.entries(s.models)
              .map(([r, id]) => `${r}: ${shortModel(id)}`)
              .join(' · ')
          }}
          · {{ s.split }} split · {{ s.menus }} menus · {{ s.run_id }}
        </p>
      </div>

      <div v-if="s.has_prices" class="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        <MetricTile
          label="Price F1"
          :value="pct(m.price?.f1)"
          :hint="`${m.price?.tp} of ${m.gt_prices} found`"
        />
        <MetricTile label="Pair F1" :value="pct(m.pair?.f1)" hint="price with the right item" />
        <MetricTile label="Names" :value="pct(m.name_accuracy)" hint="of found prices" />
        <MetricTile label="AURC" :value="num(m.selective?.aurc, 3)" hint="lower is better" />
        <MetricTile
          label="Safe @1%"
          :value="pct(m.selective?.safe_recall?.['0.01'])"
          hint="auto-placed, ≤1% wrong"
        />
        <MetricTile label="Cost" :value="usd(m.cost?.per_menu_usd)" hint="per menu" />
        <MetricTile
          label="Latency p50"
          :value="seconds(m.latency_s?.p50)"
          :hint="`p95 ${seconds(m.latency_s?.p95)}`"
        />
      </div>
      <div v-if="m.operating_point || m.linking" class="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <template v-if="m.operating_point">
          <MetricTile
            label="Auto-placed"
            :value="pct(m.operating_point.recall)"
            :hint="`of all prices, at the threshold frozen on dev`"
          />
          <MetricTile label="Wrong among auto" :value="pct(m.operating_point.risk)" hint="target ≤ 1%" />
        </template>
        <MetricTile
          label="Calibration error"
          :value="num(m.calibration?.ece, 3)"
          hint="ECE, lower is better"
        />
        <template v-if="m.linking">
          <MetricTile
            label="Wrong links"
            :value="pct(m.linking.wrong_link_rate)"
            :hint="`of ${m.linking.links} links`"
          />
          <MetricTile
            label="Linked automatically"
            :value="pct(m.linking.auto_link_recall)"
            hint="of linkable prices"
          />
          <MetricTile
            label="Hint has the answer"
            :value="pct(m.linking.hint_top3)"
            hint="right item in top 3"
          />
        </template>
      </div>
      <div v-if="m.ocr" class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricTile
          label="OCR text found"
          :value="pct(m.ocr.text_recall)"
          :hint="`${m.ocr.gt_lines} lines`"
        />
        <MetricTile
          label="OCR located"
          :value="pct(m.ocr.line_recall)"
          :hint="`prices ${pct(m.ocr.price_line_recall)}`"
        />
        <MetricTile label="Box IoU" :value="num(m.ocr.iou_mean)" />
        <MetricTile label="CER" :value="num(m.ocr.cer_mean, 3)" hint="on located lines" />
      </div>

      <section v-if="curves.length" class="card p-4">
        <h2 class="text-sm font-semibold">Risk–coverage</h2>
        <p class="text-xs text-ink-3">
          Keep the most confident predictions first; the line shows the error rate among what is kept.
        </p>
        <RiskCoverageChart :curves="curves" />
      </section>

      <section v-if="s.has_prices && slices.length" class="grid gap-4 md:grid-cols-2">
        <div v-for="[dim, groups] in slices" :key="dim" class="card overflow-x-auto">
          <h2 class="px-4 pt-4 text-sm font-semibold">By {{ dim }}</h2>
          <table class="data mt-2">
            <thead>
              <tr>
                <th>{{ dim }}</th>
                <th class="text-right">Menus</th>
                <th class="text-right">Prices</th>
                <th class="text-right">Price F1</th>
                <th class="text-right">Pair F1</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(g, key) in groups" :key="key">
                <td>{{ key }}</td>
                <td class="num text-right">{{ g.menus }}</td>
                <td class="num text-right">{{ g.gt_prices }}</td>
                <td class="num text-right">{{ pct(g.price?.f1) }}</td>
                <td class="num text-right">{{ pct(g.pair?.f1) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card overflow-x-auto">
        <div class="flex items-center justify-between px-4 pt-4">
          <h2 class="text-sm font-semibold">Menus</h2>
          <label class="text-xs text-ink-3">
            Sort by
            <select v-model="sortKey" class="ml-1 rounded border border-line bg-surface-1 px-1 py-0.5">
              <option value="errors">errors</option>
              <option value="cost_usd">cost</option>
              <option value="latency_s">latency</option>
              <option value="menu_id">id</option>
            </select>
          </label>
        </div>
        <table class="data mt-2">
          <thead>
            <tr>
              <th>Menu</th>
              <th>Template</th>
              <th>Lang</th>
              <th class="text-right">GT prices</th>
              <th class="text-right">Predicted</th>
              <th class="text-right">Correct pairs</th>
              <th class="text-right">Errors</th>
              <th class="text-right">Cost</th>
              <th class="text-right">Latency</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in menus" :key="row.menu_id" class="clickable" @click="open(row)">
              <td class="font-medium">{{ row.menu_id }}</td>
              <td class="text-ink-2">{{ row.template }}</td>
              <td class="text-ink-2">{{ row.lang }}</td>
              <td class="num text-right">{{ row.gt }}</td>
              <td class="num text-right">{{ row.pred }}</td>
              <td class="num text-right">{{ row.pair_tp }}</td>
              <td class="num text-right" :class="row.errors ? 'font-semibold text-critical' : 'text-ink-3'">
                {{ row.errors }}
              </td>
              <td class="num text-right">{{ usd(row.cost_usd) }}</td>
              <td class="num text-right">{{ seconds(row.latency_s) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
