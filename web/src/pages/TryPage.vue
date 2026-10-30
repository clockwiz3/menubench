<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { api, unwrap } from '@/api/client'
import type { components } from '@/api/schema'
import BBoxCanvas, { type CanvasBox } from '@/components/BBoxCanvas.vue'
import { num, seconds, usd, when } from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

type TryJob = components['schemas']['TryJob']
interface StageEvent {
  stage: string
  t?: number
  lines?: number
  candidates?: number
  decided?: number
  rejected?: number
  done?: number
  total?: number
  item?: string | null
  prices?: number
  cost_usd?: number
  message?: string
  agreed?: number
  reader_only?: number
  verifier_prices?: number
}

const { data: limits, error: limitsError } = useAsync(
  () => 0,
  () => unwrap(api.GET('/api/try/limits')),
)
const { data: gallery } = useAsync(
  () => 0,
  () => unwrap(api.GET('/api/try/gallery')),
)

const job = ref<TryJob>()
const events = ref<StageEvent[]>([])
const running = ref(false)
const failure = ref<string | null>(null)
const selected = ref<string | null>(null)
let source: EventSource | undefined
onBeforeUnmount(() => source?.close())

async function upload(files: FileList | null) {
  const file = files?.[0]
  if (!file) return
  failure.value = null
  events.value = []
  job.value = undefined
  running.value = true
  const form = new FormData()
  form.append('file', file)
  try {
    const res = await fetch('/api/try/jobs', { method: 'POST', body: form })
    const body = await res.json()
    if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : res.statusText)
    job.value = body as TryJob
    listen(job.value.job_id)
  } catch (e) {
    failure.value = e instanceof Error ? e.message : String(e)
    running.value = false
  }
}

function listen(jobId: string) {
  source?.close()
  source = new EventSource(`/api/try/jobs/${jobId}/events`)
  source.addEventListener('stage', async (msg) => {
    const event = JSON.parse((msg as MessageEvent<string>).data) as StageEvent
    events.value.push(event)
    if (event.stage === 'done' || event.stage === 'failed') {
      source?.close()
      running.value = false
      if (event.stage === 'failed') failure.value = event.message ?? 'the pipeline failed'
      job.value = await unwrap(api.GET('/api/try/jobs/{job_id}', { params: { path: { job_id: jobId } } }))
      historyTick.value++
    }
  })
  source.onerror = () => {
    if (running.value) failure.value = 'lost connection to the server'
    running.value = false
    source?.close()
  }
}

// Recent live runs; the server answers only on a local install, the public demo keeps uploads private.
const historyTick = ref(0)
const { data: history } = useAsync(
  () => historyTick.value,
  async () => {
    const res = await fetch('/api/try/history')
    return res.ok ? ((await res.json()) as components['schemas']['TryHistoryRow'][]) : []
  },
)
async function openRun(jobId: string) {
  source?.close()
  running.value = false
  failure.value = null
  events.value = []
  job.value = await unwrap(api.GET('/api/try/jobs/{job_id}', { params: { path: { job_id: jobId } } }))
}

function showExample(example: { job: TryJob }) {
  source?.close()
  running.value = false
  failure.value = null
  events.value = []
  job.value = example.job
}

// Live steps, derived from the event stream.
const steps = computed(() => {
  const by = (s: string) => events.value.filter((e) => e.stage === s)
  const read = by('e2e').at(-1)
  const ocr = by('ocr').at(-1)
  const detect = by('detect').at(-1)
  const price = by('price').at(-1)
  const compared = by('second_opinion').at(-1)
  const finished = events.value.some((e) => e.stage === 'done')
  return [
    {
      label: 'A strong model reads the whole menu',
      detail: read ? `${read.prices} prices` : '',
      done: !!read,
    },
    { label: 'Second opinion: reading the text (OCR)', detail: ocr ? `${ocr.lines} lines` : '', done: !!ocr },
    {
      label: 'Second opinion: finding prices',
      detail: detect ? `${detect.candidates} candidates` : '',
      done: !!detect,
    },
    {
      label: 'Second opinion: naming the item of each price',
      detail: price ? `${price.done} of ${price.total}${price.item ? ` · ${price.item}` : ''}` : '',
      done: !!compared || finished,
      progress: price && price.total ? (price.done ?? 0) / price.total : undefined,
    },
    {
      label: 'Comparing the two opinions',
      detail: compared ? `agree on ${compared.agreed} prices` : '',
      done: !!compared,
    },
    { label: 'Deciding what is safe to show', detail: finished ? 'done' : '', done: finished },
  ]
})

const prices = computed(() => job.value?.prediction?.prices ?? [])
const autoCount = computed(() => prices.value.filter((p) => p.auto).length)
const boxes = computed<CanvasBox[]>(() =>
  prices.value
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => p.bbox && p.page === 0)
    .map(({ p, i }) => ({
      id: `p${i}`,
      bbox: p.bbox!,
      color: p.auto ? 'var(--good)' : p.auto === false ? 'var(--warning)' : 'var(--accent)',
      label: `${p.name ?? '—'} — ${p.value} · ${p.auto ? 'auto-placed' : 'needs review'} (${num(p.confidence)})`,
    })),
)
const page = computed(() => job.value?.pages[0])
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">Try it</h1>
      <p class="mt-1 max-w-3xl text-sm text-ink-3">
        Upload a menu photo. A strong model reads it; an independent pipeline reads it again its own way.
        Where both agree with enough confidence, a price is safe to put on a screen without a person checking
        it. Everything else goes to review: a wrong price on a screen is worse than an empty slot.
      </p>
    </div>

    <div class="grid gap-4 lg:grid-cols-3">
      <label
        class="card flex flex-col items-center justify-center gap-2 border-2 border-dashed p-6 text-center lg:col-span-1"
        :class="limits?.enabled && !running ? 'cursor-pointer hover:bg-surface-2' : 'opacity-60'"
      >
        <input
          type="file"
          accept="image/*,.pdf"
          class="sr-only"
          :disabled="!limits?.enabled || running"
          @change="upload(($event.target as HTMLInputElement).files)"
        />
        <span class="text-sm font-medium">{{ running ? 'Working…' : 'Upload a menu photo or PDF' }}</span>
        <span v-if="limits?.enabled" class="text-xs text-ink-3">
          up to 10 MB · {{ limits.uploads_left_today }} uploads left today · deleted after 24 hours
        </span>
        <span v-else-if="limits" class="text-xs text-ink-2">{{ limits.reason }}</span>
        <span v-if="limitsError" class="text-xs text-critical">{{ limitsError }}</span>
      </label>

      <div class="card p-4 lg:col-span-2">
        <h2 class="text-sm font-semibold">Or open an example</h2>
        <div class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <button
            v-for="g in gallery ?? []"
            :key="g.id"
            class="overflow-hidden rounded-lg border border-line text-left hover:border-[var(--accent)]"
            @click="showExample(g)"
          >
            <img
              :src="g.job.pages[0]?.url"
              :alt="g.title"
              class="h-24 w-full object-cover object-top"
              loading="lazy"
            />
            <div class="p-2 text-xs">
              <div class="font-medium text-ink-1">{{ g.title }}</div>
              <div class="text-ink-3">{{ g.note }}</div>
            </div>
          </button>
        </div>
        <p v-if="gallery && !gallery.length" class="mt-2 text-xs text-ink-3">No examples on this server.</p>
      </div>
    </div>

    <section v-if="history?.length" class="card p-4">
      <h2 class="text-sm font-semibold">Recent runs on this machine</h2>
      <p class="text-xs text-ink-3">Kept for 24 hours with their photo; only visible on a local install.</p>
      <div class="mt-3 flex gap-3 overflow-x-auto pb-1">
        <button
          v-for="h in history"
          :key="h.job_id"
          class="w-32 shrink-0 overflow-hidden rounded-lg border border-line text-left hover:border-[var(--accent)]"
          :class="job?.job_id === h.job_id ? 'border-[var(--accent)]' : ''"
          @click="openRun(h.job_id)"
        >
          <img
            v-if="h.thumbnail"
            :src="h.thumbnail"
            alt=""
            class="h-20 w-full object-cover object-top"
            loading="lazy"
          />
          <div class="p-1.5 text-[11px] leading-tight">
            <div class="text-ink-1">{{ h.auto_placed }} / {{ h.prices }} auto</div>
            <div class="text-ink-3">{{ when(h.created_at) }}</div>
          </div>
        </button>
      </div>
    </section>

    <section v-if="running || events.length" class="card p-4">
      <ol class="space-y-2 text-sm">
        <li v-for="s in steps" :key="s.label" class="flex items-center gap-3">
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold"
            :class="s.done ? 'bg-[var(--good)] text-white' : 'border border-line text-ink-3'"
            aria-hidden="true"
            >{{ s.done ? '✓' : '' }}</span
          >
          <span :class="s.done ? 'text-ink-1' : 'text-ink-2'">{{ s.label }}</span>
          <span class="text-xs text-ink-3">{{ s.detail }}</span>
          <span
            v-if="s.progress !== undefined && !s.done"
            class="ml-auto h-1.5 w-40 overflow-hidden rounded bg-surface-2"
          >
            <span
              class="block h-full bg-[var(--accent)]"
              :style="{ width: `${Math.round(s.progress * 100)}%` }"
            />
          </span>
        </li>
      </ol>
    </section>
    <p v-if="failure" class="card p-3 text-sm text-critical">{{ failure }}</p>

    <div v-if="job?.prediction && page" class="grid gap-4 lg:grid-cols-5">
      <section class="card p-3 lg:col-span-3">
        <div class="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
          <span class="flex items-center gap-1.5"
            ><span class="h-3 w-3 rounded-sm border-2 border-[var(--good)]" />Auto-placed</span
          >
          <span class="flex items-center gap-1.5"
            ><span class="h-3 w-3 rounded-sm border-2 border-[var(--warning)]" />Needs review</span
          >
        </div>
        <div class="max-h-[78vh] overflow-auto [scrollbar-gutter:stable] rounded-md border border-line">
          <BBoxCanvas :src="page.url" :boxes="boxes" :selected="selected" @select="selected = $event" />
        </div>
      </section>
      <section class="space-y-4 lg:col-span-2">
        <div class="card grid grid-cols-3 gap-2 p-4 text-center">
          <div>
            <div class="num text-2xl font-semibold">{{ prices.length }}</div>
            <div class="text-xs text-ink-3">prices found</div>
          </div>
          <div>
            <div class="num text-2xl font-semibold">{{ autoCount }}</div>
            <div class="text-xs text-ink-3">safe to auto-place</div>
          </div>
          <div>
            <div class="num text-2xl font-semibold">{{ usd(job.prediction.cost_usd, 4) }}</div>
            <div class="text-xs text-ink-3">{{ seconds(job.prediction.latency_s) }}</div>
          </div>
        </div>
        <div class="card overflow-x-auto">
          <table class="data">
            <thead>
              <tr>
                <th>Item</th>
                <th class="text-right">Price</th>
                <th class="text-right">Confidence</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(p, i) in prices"
                :key="i"
                class="clickable"
                :class="selected === `p${i}` ? 'bg-surface-2' : ''"
                @click="selected = selected === `p${i}` ? null : `p${i}`"
              >
                <td>{{ p.name ?? '—' }}</td>
                <td class="num text-right">{{ p.value }}</td>
                <td class="num text-right">{{ num(p.confidence) }}</td>
                <td class="text-xs" :class="p.auto ? 'text-good' : 'text-ink-2'">
                  {{ p.auto ? 'auto-placed' : 'review' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>
