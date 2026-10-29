<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, unwrap, type RunSummary } from '@/api/client'
import { num, pct, seconds, shortModel, usd, when } from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

const router = useRouter()
const {
  data: runs,
  error,
  loading,
} = useAsync(
  () => 0,
  () => unwrap(api.GET('/api/runs')),
)

const latestOnly = ref(true)
const visible = computed(() => {
  const all = runs.value ?? []
  if (!latestOnly.value) return all
  const seen = new Set<string>()
  return all.filter((r) => !seen.has(r.config_name) && seen.add(r.config_name))
})

const extraction = computed(() =>
  visible.value.filter((r) => r.has_prices || r.errors).sort((a, b) => (b.pair_f1 ?? -1) - (a.pair_f1 ?? -1)),
)
const ocr = computed(() =>
  visible.value
    .filter((r) => !r.has_prices && r.ocr_line_recall != null)
    .sort((a, b) => (b.ocr_line_recall ?? -1) - (a.ocr_line_recall ?? -1)),
)

function models(run: RunSummary): string {
  return Object.values(run.models).map(shortModel).join(' + ')
}
function open(run: RunSummary) {
  router.push({ name: 'run', params: { runId: run.run_id } })
}
</script>

<template>
  <div class="space-y-8">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Runs</h1>
        <p class="mt-1 text-sm text-ink-3">
          Every pipeline configuration scored on the same split. Sorted by pair F1 — a price counts only with
          the right item.
        </p>
      </div>
      <label class="flex items-center gap-2 text-sm text-ink-2">
        <input v-model="latestOnly" type="checkbox" class="accent-[var(--accent)]" />
        Latest run per config
      </label>
    </div>

    <p v-if="error" class="card p-4 text-sm text-critical">{{ error }}</p>
    <p v-else-if="loading && !runs" class="text-sm text-ink-3">Loading…</p>
    <p v-else-if="runs && !runs.length" class="card p-6 text-sm text-ink-3">
      No evaluated runs yet. Start one with <code>uv run menubench run configs/…</code>.
    </p>

    <section v-if="extraction.length" class="card overflow-x-auto">
      <h2 class="px-4 pt-4 text-sm font-semibold">Price extraction</h2>
      <table class="data mt-2">
        <thead>
          <tr>
            <th>Config</th>
            <th>Models</th>
            <th class="text-right">Price F1</th>
            <th class="text-right">Pair F1</th>
            <th class="text-right">Names</th>
            <th class="text-right" title="Area under the risk–coverage curve; lower is better">AURC</th>
            <th class="text-right" title="Share of all prices placed automatically with at most 1% errors">
              Safe @1%
            </th>
            <th class="text-right">$/menu</th>
            <th class="text-right">p50</th>
            <th class="text-right">Menus</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in extraction" :key="r.run_id" class="clickable" @click="open(r)">
            <td class="font-medium">{{ r.config_name }}</td>
            <td class="text-ink-2">{{ models(r) }}</td>
            <td class="num text-right">{{ pct(r.price_f1) }}</td>
            <td class="num text-right font-semibold">{{ pct(r.pair_f1) }}</td>
            <td class="num text-right">{{ pct(r.name_accuracy) }}</td>
            <td class="num text-right">{{ num(r.aurc, 3) }}</td>
            <td class="num text-right">{{ pct(r.safe_recall_1) }}</td>
            <td class="num text-right">{{ usd(r.per_menu_usd) }}</td>
            <td class="num text-right">{{ seconds(r.latency_p50) }}</td>
            <td class="num text-right">
              {{ r.menus }}<span v-if="r.errors" class="text-critical"> ({{ r.errors }} failed)</span>
            </td>
            <td class="whitespace-nowrap text-ink-3">{{ when(r.started_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="ocr.length" class="card overflow-x-auto">
      <h2 class="px-4 pt-4 text-sm font-semibold">OCR only</h2>
      <p class="px-4 text-xs text-ink-3">
        “Found” — the text is recognized somewhere on the page; “located” — recognized and boxed in the right
        place.
      </p>
      <table class="data mt-2">
        <thead>
          <tr>
            <th>Model</th>
            <th class="text-right">Text found</th>
            <th class="text-right">Located</th>
            <th class="text-right">$/menu</th>
            <th class="text-right">p50</th>
            <th class="text-right">Menus</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in ocr" :key="r.run_id" class="clickable" @click="open(r)">
            <td class="font-medium">{{ models(r) }}</td>
            <td class="num text-right">{{ pct(r.ocr_text_recall) }}</td>
            <td class="num text-right font-semibold">{{ pct(r.ocr_line_recall) }}</td>
            <td class="num text-right">{{ usd(r.per_menu_usd) }}</td>
            <td class="num text-right">{{ seconds(r.latency_p50) }}</td>
            <td class="num text-right">{{ r.menus }}</td>
            <td class="whitespace-nowrap text-ink-3">{{ when(r.started_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
