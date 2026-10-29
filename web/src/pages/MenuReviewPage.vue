<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, unwrap } from '@/api/client'
import BBoxCanvas, { type CanvasBox } from '@/components/BBoxCanvas.vue'
import OutcomeBadge from '@/components/OutcomeBadge.vue'
import { num, seconds, usd } from '@/lib/format'
import { MISSED, OUTCOMES } from '@/lib/outcomes'
import { useAsync } from '@/lib/useAsync'

const props = defineProps<{ runId: string; menuId: string }>()

const { data: review, error } = useAsync(
  () => [props.runId, props.menuId],
  () =>
    unwrap(
      api.GET('/api/runs/{run_id}/menus/{menu_id}', {
        params: { path: { run_id: props.runId, menu_id: props.menuId } },
      }),
    ),
)

const page = ref(0)
const zoom = ref(1)
const selected = ref<string | null>(null)
const layers = reactive({ predictions: true, missed: true, groundTruth: false, ocr: false })

const imageUrl = computed(
  () =>
    `/api/runs/${encodeURIComponent(props.runId)}/menus/${encodeURIComponent(props.menuId)}/pages/${page.value}`,
)
const gtPrices = computed(() => new Map((review.value?.annotation.prices ?? []).map((p) => [p.id, p])))
const itemNames = computed(() => new Map((review.value?.annotation.items ?? []).map((i) => [i.id, i.name])))

function gtLabel(id: string): string {
  const p = gtPrices.value.get(id)
  if (!p) return id
  const names = p.item_ids.map((i) => itemNames.value.get(i)).join(', ')
  return `${names}${p.size_label ? ` (${p.size_label})` : ''} — ${p.value}${p.kind === 'crossed' ? ' (crossed out)' : ''}`
}

const rows = computed(() => {
  const r = review.value
  if (!r?.prediction) return []
  return r.outcomes.map((o) => ({
    ...o,
    pred: r.prediction!.prices[o.index]!,
    link: r.prediction!.links[o.index] ?? null,
  }))
})

const boxes = computed<CanvasBox[]>(() => {
  const r = review.value
  if (!r) return []
  const out: CanvasBox[] = []
  if (layers.ocr) {
    r.prediction?.lines
      .filter((l) => l.page === page.value)
      .forEach((l, i) =>
        out.push({ id: `ocr-${i}`, bbox: l.bbox, color: 'var(--ocr)', label: l.text, thin: true }),
      )
  }
  if (layers.groundTruth) {
    r.annotation.prices
      .filter((p) => p.page === page.value)
      .forEach((p) =>
        out.push({ id: `gt-${p.id}`, bbox: p.bbox, color: 'var(--gt)', label: gtLabel(p.id), thin: true }),
      )
  }
  if (layers.missed) {
    r.missed
      .map((id) => gtPrices.value.get(id))
      .filter((p) => p && p.page === page.value)
      .forEach((p) =>
        out.push({
          id: `missed-${p!.id}`,
          bbox: p!.bbox,
          color: MISSED.color,
          dashed: true,
          label: `Missed: ${gtLabel(p!.id)}`,
        }),
      )
  }
  if (layers.predictions) {
    for (const row of rows.value) {
      if (!row.pred.bbox || row.pred.page !== page.value) continue
      const style = OUTCOMES[row.outcome]
      out.push({
        id: `pred-${row.index}`,
        bbox: row.pred.bbox,
        color: style.color,
        label: `${style.label}: ${row.pred.name ?? '—'} — ${row.pred.value} (confidence ${num(row.pred.confidence)})`,
      })
    }
  }
  return out
})

const hasLinks = computed(() => !!review.value?.prediction?.links.length)
const catalog = computed(() => new Map((review.value?.annotation.catalog ?? []).map((c) => [c.id, c.name])))
const catalogName = (id: string | null | undefined) => (id ? (catalog.value.get(id) ?? id) : '—')
const LINK_LABEL = { link: 'Linked', hint: 'Hint', abstain: 'Abstain' } as const
const stages = computed(() => (review.value?.trace?.stages as Record<string, unknown>[] | undefined) ?? [])
const layerList = [
  { key: 'predictions', label: 'Predictions' },
  { key: 'missed', label: 'Missed' },
  { key: 'groundTruth', label: 'Ground truth' },
  { key: 'ocr', label: 'OCR lines' },
] as const
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3 text-sm">
      <RouterLink :to="{ name: 'run', params: { runId } }" class="text-ink-3 hover:text-ink-1"
        >← {{ runId }}</RouterLink
      >
      <span class="ml-auto flex gap-2">
        <RouterLink
          v-if="review?.prev_menu"
          :to="{ name: 'review', params: { runId, menuId: review.prev_menu } }"
          class="rounded-md border border-line px-2 py-1 hover:bg-surface-2"
          >← Previous</RouterLink
        >
        <RouterLink
          v-if="review?.next_menu"
          :to="{ name: 'review', params: { runId, menuId: review.next_menu } }"
          class="rounded-md border border-line px-2 py-1 hover:bg-surface-2"
          >Next →</RouterLink
        >
      </span>
    </div>
    <p v-if="error" class="card p-4 text-sm text-critical">{{ error }}</p>

    <template v-if="review">
      <div>
        <h1 class="text-xl font-semibold tracking-tight">{{ menuId }}</h1>
        <p class="text-sm text-ink-3">
          {{ review.annotation.template }} · {{ review.annotation.lang }} ·
          {{ review.annotation.prices.length }} prices on the menu · {{ usd(review.prediction?.cost_usd) }} ·
          {{ seconds(review.prediction?.latency_s) }}
          <span v-if="review.prediction?.error" class="text-critical">
            · failed: {{ review.prediction.error }}</span
          >
        </p>
      </div>

      <div class="grid gap-4 lg:grid-cols-5">
        <section class="card p-3 lg:col-span-3">
          <div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-2">
            <label v-for="l in layerList" :key="l.key" class="flex items-center gap-1.5">
              <input v-model="layers[l.key]" type="checkbox" class="accent-[var(--accent)]" />
              {{ l.label }}
            </label>
            <span class="ml-auto flex items-center gap-1">
              <button
                v-for="z in [1, 1.5, 2]"
                :key="z"
                class="rounded px-2 py-0.5"
                :class="zoom === z ? 'bg-surface-2 text-ink-1' : 'text-ink-3 hover:text-ink-1'"
                @click="zoom = z"
              >
                {{ z }}×
              </button>
            </span>
          </div>
          <div class="mb-3 flex flex-wrap gap-3">
            <OutcomeBadge v-for="(_, key) in OUTCOMES" :key="key" :outcome="key" />
            <OutcomeBadge outcome="missed" />
          </div>
          <div v-if="review.annotation.pages.length > 1" class="mb-2 flex gap-1 text-xs">
            <button
              v-for="(_, i) in review.annotation.pages"
              :key="i"
              class="rounded px-2 py-0.5"
              :class="page === i ? 'bg-surface-2' : 'text-ink-3'"
              @click="page = i"
            >
              Page {{ i + 1 }}
            </button>
          </div>
          <div class="max-h-[78vh] overflow-auto rounded-md border border-line">
            <BBoxCanvas
              :src="imageUrl"
              :boxes="boxes"
              :selected="selected"
              :zoom="zoom"
              @select="selected = $event"
            />
          </div>
        </section>

        <section class="space-y-4 lg:col-span-2">
          <div class="card overflow-x-auto">
            <h2 class="px-4 pt-4 text-sm font-semibold">Predictions ({{ rows.length }})</h2>
            <table class="data mt-2">
              <thead>
                <tr>
                  <th>Outcome</th>
                  <th>Item</th>
                  <th class="text-right">Price</th>
                  <th class="text-right">Conf.</th>
                  <th v-if="hasLinks">Catalog</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in rows"
                  :key="row.index"
                  class="clickable"
                  :class="selected === `pred-${row.index}` ? 'bg-surface-2' : ''"
                  @click="selected = selected === `pred-${row.index}` ? null : `pred-${row.index}`"
                >
                  <td><OutcomeBadge :outcome="row.outcome" /></td>
                  <td>
                    {{ row.pred.name ?? '—' }}
                    <div v-if="row.outcome === 'wrong_name' && row.gt_name" class="text-xs text-ink-3">
                      should be: {{ row.gt_name }}
                    </div>
                  </td>
                  <td class="num text-right">{{ row.pred.value }}</td>
                  <td class="num text-right">
                    {{ num(row.pred.confidence) }}
                    <div
                      v-if="row.pred.auto != null"
                      class="text-xs"
                      :class="row.pred.auto ? 'text-good' : 'text-ink-3'"
                    >
                      {{ row.pred.auto ? 'auto' : 'review' }}
                    </div>
                  </td>
                  <td v-if="hasLinks" class="text-xs">
                    <template v-if="row.link">
                      <span class="font-medium">{{ LINK_LABEL[row.link.action] }}</span>
                      <span v-if="row.link.action === 'link'" class="text-ink-2">
                        → {{ catalogName(row.link.catalog_id) }}</span
                      >
                      <ol v-else-if="row.link.candidates.length" class="mt-0.5 list-decimal pl-4 text-ink-2">
                        <li v-for="c in row.link.candidates" :key="c.catalog_id">
                          {{ catalogName(c.catalog_id) }}
                        </li>
                      </ol>
                      <div v-if="row.link.reason" class="mt-0.5 text-ink-3">{{ row.link.reason }}</div>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="review.missed.length" class="card overflow-x-auto">
            <h2 class="px-4 pt-4 text-sm font-semibold">Missed ({{ review.missed.length }})</h2>
            <ul class="px-4 py-2 text-sm">
              <li
                v-for="id in review.missed"
                :key="id"
                class="cursor-pointer border-b border-line py-1.5 last:border-0 hover:text-ink-1"
                :class="selected === `missed-${id}` ? 'text-ink-1' : 'text-ink-2'"
                @click="selected = `missed-${id}`"
              >
                {{ gtLabel(id) }}
              </li>
            </ul>
          </div>

          <div v-if="stages.length" class="card">
            <h2 class="px-4 pt-4 text-sm font-semibold">Pipeline stages</h2>
            <details
              v-for="(st, i) in stages"
              :key="i"
              class="border-t border-line px-4 py-2 first:border-t-0"
            >
              <summary class="cursor-pointer text-sm">
                <span class="font-medium">{{ st.stage }}</span>
                <span class="ml-2 text-xs text-ink-3">t={{ st.t }}s</span>
              </summary>
              <pre
                class="mt-2 max-h-80 overflow-auto rounded bg-surface-2 p-2 font-mono text-[11px] leading-snug"
                >{{ JSON.stringify(st, null, 1) }}</pre>
            </details>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
