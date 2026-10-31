<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, unwrap, type AnnotationStatus, type BBox, type MenuForEditor } from '@/api/client'
import BBoxEditor, { type DrawMode, type EditorBox } from '@/components/BBoxEditor.vue'
import {
  addItem,
  addPrice,
  History,
  nearestItem,
  nudge,
  problems,
  remove,
  type Draft,
  type Selection,
} from '@/lib/annotationDraft'

const props = defineProps<{ menuId: string }>()
const router = useRouter()

const menu = ref<MenuForEditor>()
const draft = ref<Draft>({ items: [], prices: [] })
const meta = ref({
  lang: 'ru',
  status: 'new' as AnnotationStatus,
  split: 'real-test',
  notes: '',
  source_url: '',
  tags: [] as string[],
})
// Slices the benchmark reports separately on real photos; one menu can have several.
const TAG_SUGGESTIONS = [
  'printed-pdf',
  'photo',
  'glare',
  'angled',
  'low-light',
  'chalkboard',
  'handwritten',
  'multi-column',
  'bilingual',
  'cyrillic',
  'latin',
  'mixed-script',
  'laminated',
  'sizes',
  'combo',
]
const customTag = ref('')
function toggleTag(tag: string) {
  const tags = meta.value.tags
  const i = tags.indexOf(tag)
  if (i >= 0) tags.splice(i, 1)
  else tags.push(tag)
}
function addCustomTag() {
  const tag = customTag.value.trim().toLowerCase().replace(/s+/g, '-')
  if (tag && !meta.value.tags.includes(tag)) meta.value.tags.push(tag)
  customTag.value = ''
}
const error = ref<string | null>(null)
const busy = ref<'save' | 'prelabel' | null>(null)
const saved = ref('')
const snapshot = () => JSON.stringify([draft.value, meta.value])
// Compared with what was last loaded or saved, so undoing an edit by hand clears the flag too.
const dirty = computed(() => !!menu.value && snapshot() !== saved.value)
const selection = ref<Selection>(null)
const mode = ref<DrawMode>('select')
const page = ref(0)
const zoom = ref(1)

function load(data: MenuForEditor) {
  menu.value = data
  draft.value = structuredClone({ items: data.annotation.items, prices: data.annotation.prices }) as Draft
  meta.value = {
    lang: data.annotation.lang,
    status: data.status,
    split: data.split,
    notes: data.notes,
    source_url: data.source_url ?? '',
    tags: [...(data.annotation.tags ?? [])],
  }
  saved.value = snapshot()
  history.reset(JSON.stringify(draft.value))
}

// Undo/redo over the boxes, links and fields of the draft. Edits are grouped by a short pause, so typing a name
// is one step, not one per letter.
const history = new History()
let restoring = false
let recordTimer: number | undefined
function flushRecord() {
  if (recordTimer === undefined) return
  window.clearTimeout(recordTimer)
  recordTimer = undefined
  history.record(JSON.stringify(draft.value))
}
watch(
  draft,
  () => {
    if (restoring) return
    window.clearTimeout(recordTimer)
    recordTimer = window.setTimeout(flushRecord, 300)
  },
  { deep: true },
)
function restore(snap: string | null) {
  if (snap === null) return
  restoring = true
  draft.value = JSON.parse(snap) as Draft
  void nextTick(() => (restoring = false))
}

async function fetchMenu() {
  try {
    load(
      await unwrap(api.GET('/api/annotate/menus/{menu_id}', { params: { path: { menu_id: props.menuId } } })),
    )
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}
watch(
  () => props.menuId,
  () => {
    page.value = 0
    selection.value = null
    mode.value = 'select'
    void fetchMenu()
  },
  { immediate: true },
)

// The menu list, for moving to the next menu without going back to the table.
const menuList = ref<{ menu_id: string; status: string }[]>([])
async function loadList() {
  try {
    menuList.value = await unwrap(api.GET('/api/annotate/menus'))
  } catch {
    menuList.value = []
  }
}
onMounted(loadList)
function neighbour(step: 1 | -1, unfinishedOnly = false): string | null {
  const list = menuList.value
  const at = list.findIndex((m) => m.menu_id === props.menuId)
  for (let k = 1; k < list.length; k++) {
    const m = list[(((at + step * k) % list.length) + list.length) % list.length]
    if (m && (!unfinishedOnly || m.status !== 'annotated')) return m.menu_id
  }
  return null
}
function go(menuId: string | null) {
  if (!menuId) return
  if (dirty.value && !window.confirm('Leave this menu without saving?')) return
  void router.push({ name: 'annotate-menu', params: { menuId } })
}
async function finishAndNext() {
  if (issues.value.length) {
    error.value = 'Fix the problems listed on the right first'
    return
  }
  await save('annotated')
  if (error.value) return
  await loadList()
  const next = neighbour(1, true)
  if (next) go(next)
  else error.value = null
}

async function save(status?: AnnotationStatus) {
  busy.value = 'save'
  error.value = null
  try {
    const saved = await unwrap(
      api.PUT('/api/annotate/menus/{menu_id}', {
        params: { path: { menu_id: props.menuId } },
        body: {
          ...meta.value,
          source_url: meta.value.source_url.trim() || null,
          status: status ?? meta.value.status,
          items: draft.value.items,
          catalog: menu.value?.annotation.catalog ?? [],
          prices: draft.value.prices,
        },
      }),
    )
    load(saved)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
  }
}

async function prelabel() {
  if (draft.value.prices.length && !window.confirm('Replace the current boxes with the pipeline proposal?'))
    return
  busy.value = 'prelabel'
  error.value = null
  try {
    load(
      await unwrap(
        api.POST('/api/annotate/menus/{menu_id}/prelabel', { params: { path: { menu_id: props.menuId } } }),
      ),
    )
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
  }
}

const itemName = computed(() => new Map(draft.value.items.map((i) => [i.id, i.name || i.id])))
const boxes = computed<EditorBox[]>(() => [
  ...draft.value.items
    .filter((i) => i.page === page.value)
    .map((i) => ({ id: `item:${i.id}`, bbox: i.bbox, color: 'var(--series-1)', label: i.name })),
  ...draft.value.prices
    .filter((p) => p.page === page.value)
    .map((p) => ({
      id: `price:${p.id}`,
      bbox: p.bbox,
      color: 'var(--series-2)',
      dashed: !p.item_ids?.length,
    })),
])

function onCreate(kind: 'price' | 'item', bbox: BBox) {
  const id =
    kind === 'price'
      ? addPrice(draft.value, page.value, bbox, selection.value)
      : addItem(draft.value, page.value, bbox, selection.value)
  selection.value = `${kind}:${id}`
  mode.value = 'select'
}
function onUpdate(key: string, bbox: BBox) {
  const [kind, id] = key.split(':') as ['price' | 'item', string]
  const list = kind === 'price' ? draft.value.prices : draft.value.items
  const entity = list.find((x) => x.id === id)
  if (entity) entity.bbox = bbox
}

const selectedPrice = computed(() =>
  selection.value?.startsWith('price:')
    ? draft.value.prices.find((p) => p.id === selection.value!.slice(6))
    : undefined,
)
const selectedItem = computed(() =>
  selection.value?.startsWith('item:')
    ? draft.value.items.find((i) => i.id === selection.value!.slice(5))
    : undefined,
)
const linkedItem = computed({
  get: () => selectedPrice.value?.item_ids?.[0] ?? '',
  set: (id: string) => {
    if (selectedPrice.value) selectedPrice.value.item_ids = id ? [id] : []
  },
})
const issues = computed(() => problems(draft.value))
function focusPrice(id: string, onPage: number) {
  selection.value = `price:${id}`
  page.value = onPage
}
function stepPrice(step: 1 | -1) {
  const prices = draft.value.prices
  if (!prices.length) return
  const at = selectedPrice.value ? prices.indexOf(selectedPrice.value) : step === 1 ? -1 : 0
  const next = prices[(at + step + prices.length) % prices.length]
  if (next) focusPrice(next.id, next.page)
}
function linkNearest() {
  const price = selectedPrice.value
  if (!price) return
  const id = nearestItem(draft.value, price.id)
  if (id) price.item_ids = [id]
}
function nudgeSelected(dxPx: number, dyPx: number, resize: boolean) {
  const entity = selectedPrice.value ?? selectedItem.value
  const size = menu.value?.annotation.pages[entity?.page ?? 0]
  if (!entity || !size) return
  entity.bbox = nudge(entity.bbox, dxPx / size.width, dyPx / size.height, resize)
}

const showKeys = ref(false)
const KEYS: [string, string][] = [
  ['I / P / Esc', 'draw an item / a price / back to select'],
  ['J / K', 'next / previous price'],
  ['L', 'link the selected price to the name on its row'],
  ['Enter', 'edit the selected price or name'],
  ['Arrows', 'move the selected box by a pixel (Shift: 10)'],
  ['Alt + arrows', 'resize it from the bottom-right corner'],
  ['Del', 'remove the selection'],
  ['Ctrl+Z / Ctrl+Shift+Z', 'undo / redo'],
  ['1 / 2 / 3', 'zoom 1× / 1.5× / 2×'],
  ['Ctrl+S', 'save'],
  ['Ctrl+Enter', 'finish and open the next unfinished menu'],
  ['Alt+→ / Alt+←', 'next / previous menu'],
  ['?', 'this list'],
]

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
}

function onKey(e: KeyboardEvent) {
  const typing =
    e.target instanceof HTMLInputElement ||
    e.target instanceof HTMLSelectElement ||
    e.target instanceof HTMLTextAreaElement
  const ctrl = e.ctrlKey || e.metaKey
  const key = e.key.toLowerCase()
  if (ctrl && key === 's') {
    e.preventDefault()
    void save()
    return
  }
  if (ctrl && e.key === 'Enter') {
    e.preventDefault()
    if (typing) (e.target as HTMLElement).blur()
    void finishAndNext()
    return
  }
  if (typing) {
    if (e.key === 'Escape') (e.target as HTMLElement).blur()
    return
  }
  if (ctrl && key === 'z') {
    e.preventDefault()
    flushRecord()
    restore(e.shiftKey ? history.redo() : history.undo())
    return
  }
  if (ctrl && key === 'y') {
    e.preventDefault()
    flushRecord()
    restore(history.redo())
    return
  }
  if (e.altKey && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
    e.preventDefault()
    go(neighbour(e.key === 'ArrowRight' ? 1 : -1))
    return
  }
  const arrow = ARROWS[e.key]
  if (arrow && selection.value) {
    e.preventDefault()
    const step = e.shiftKey ? 10 : 1
    nudgeSelected(arrow[0] * step, arrow[1] * step, e.altKey)
    return
  }
  if (ctrl || e.altKey) return
  if (key === 'p') mode.value = 'price'
  else if (key === 'i') mode.value = 'item'
  else if (key === 'j') stepPrice(1)
  else if (key === 'k') stepPrice(-1)
  else if (key === 'l') linkNearest()
  else if (e.key === '1' || e.key === '2' || e.key === '3') zoom.value = [1, 1.5, 2][Number(e.key) - 1]!
  else if (e.key === '?') showKeys.value = !showKeys.value
  else if (e.key === 'Enter' && selection.value) {
    e.preventDefault()
    document.querySelector<HTMLInputElement>('[data-hotkey-focus]')?.select()
  } else if (e.key === 'Escape') {
    if (showKeys.value) showKeys.value = false
    else {
      mode.value = 'select'
      selection.value = null
    }
  } else if ((e.key === 'Delete' || e.key === 'Backspace') && selection.value) {
    remove(draft.value, selection.value)
    selection.value = null
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

const imageUrl = computed(() => `/api/annotate/menus/${encodeURIComponent(props.menuId)}/pages/${page.value}`)
const MODES: { value: DrawMode; label: string; key: string }[] = [
  { value: 'select', label: 'Select', key: 'Esc' },
  { value: 'item', label: 'Draw item', key: 'I' },
  { value: 'price', label: 'Draw price', key: 'P' },
]
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3 text-sm">
      <RouterLink to="/annotate" class="text-ink-3 hover:text-ink-1">← Annotate</RouterLink>
      <h1 class="text-lg font-semibold">{{ menuId }}</h1>
      <span v-if="dirty" class="text-xs text-ink-3">unsaved changes</span>
      <span class="ml-auto flex flex-wrap items-center gap-2">
        <button
          class="rounded-md border border-line px-3 py-1.5 hover:bg-surface-2 disabled:opacity-50"
          :disabled="!!busy"
          @click="prelabel"
        >
          {{ busy === 'prelabel' ? 'Running pipeline…' : 'Pre-label with pipeline' }}
        </button>
        <button
          v-if="meta.status !== 'annotated'"
          class="rounded-md border border-line px-3 py-1.5 hover:bg-surface-2 disabled:opacity-50"
          :disabled="!!busy"
          @click="save()"
        >
          Save draft
        </button>
        <button
          class="rounded-md bg-[var(--accent)] px-3 py-1.5 font-medium text-white disabled:opacity-50"
          :disabled="!!busy || issues.length > 0"
          :title="
            issues.length
              ? 'Fix the problems listed on the right first'
              : 'Save and add to the real test split'
          "
          @click="save('annotated')"
        >
          {{ meta.status === 'annotated' ? 'Save' : 'Finish' }}
        </button>
      </span>
    </div>
    <p v-if="error" class="card p-3 text-sm text-critical">{{ error }}</p>

    <div v-if="menu" class="grid gap-4 lg:grid-cols-5">
      <section class="card p-3 lg:col-span-3">
        <div class="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <button
            v-for="m in MODES"
            :key="m.value"
            class="rounded-md border px-2 py-1"
            :class="
              mode === m.value ? 'border-[var(--accent)] bg-surface-2 text-ink-1' : 'border-line text-ink-2'
            "
            @click="mode = m.value"
          >
            {{ m.label }} <kbd class="ml-1 text-ink-3">{{ m.key }}</kbd>
          </button>
          <span class="text-ink-3">dashed price = no item yet</span>
          <button
            class="rounded-md border border-line px-2 py-1 text-ink-2 hover:text-ink-1"
            :aria-expanded="showKeys"
            @click="showKeys = !showKeys"
          >
            Shortcuts <kbd class="ml-1 text-ink-3">?</kbd>
          </button>
          <span class="ml-auto flex gap-1">
            <button
              v-for="z in [1, 1.5, 2]"
              :key="z"
              class="rounded px-2 py-0.5"
              :class="zoom === z ? 'bg-surface-2 text-ink-1' : 'text-ink-3'"
              @click="zoom = z"
            >
              {{ z }}×
            </button>
          </span>
        </div>
        <dl
          v-if="showKeys"
          class="mb-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-md border border-line bg-surface-2 p-3 text-xs"
        >
          <template v-for="[k, what] in KEYS" :key="k">
            <dt class="font-mono text-ink-1">{{ k }}</dt>
            <dd class="text-ink-2">{{ what }}</dd>
          </template>
        </dl>
        <div v-if="menu.annotation.pages.length > 1" class="mb-2 flex gap-1 text-xs">
          <button
            v-for="(_, i) in menu.annotation.pages"
            :key="i"
            class="rounded px-2 py-0.5"
            :class="page === i ? 'bg-surface-2' : 'text-ink-3'"
            @click="page = i"
          >
            Page {{ i + 1 }}
          </button>
        </div>
        <div class="max-h-[80vh] overflow-auto [scrollbar-gutter:stable] rounded-md border border-line">
          <BBoxEditor
            :src="imageUrl"
            :boxes="boxes"
            :selected="selection"
            :mode="mode"
            :zoom="zoom"
            @select="selection = $event as Selection"
            @create="onCreate"
            @update="onUpdate"
          />
        </div>
      </section>

      <section class="space-y-4 lg:col-span-2">
        <div class="card space-y-3 p-4 text-sm">
          <h2 class="font-semibold">
            Menu
            <span v-if="menu.group" class="ml-2 text-xs font-normal text-ink-3"
              >venue group: {{ menu.group }}</span
            >
          </h2>
          <div class="grid grid-cols-3 gap-2">
            <label class="text-xs text-ink-3">
              Language
              <select
                v-model="meta.lang"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              >
                <option value="ru">ru</option>
                <option value="en">en</option>
                <option value="sr">sr</option>
              </select>
            </label>
            <label class="text-xs text-ink-3">
              Split
              <select
                v-model="meta.split"
                :disabled="menu.split_locked"
                :title="menu.split_locked ? 'The split is fixed; test menus stay test' : undefined"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1 disabled:bg-surface-2"
              >
                <option v-if="meta.split === 'recheck'" value="recheck">recheck (blind)</option>
                <option value="real-test">real-test</option>
                <option value="real-dev">real-dev</option>
              </select>
            </label>
            <label class="text-xs text-ink-3">
              Status
              <input
                :value="meta.status"
                disabled
                class="mt-1 w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm"
              />
            </label>
          </div>
          <label class="block text-xs text-ink-3">
            Source link
            <input
              v-model="meta.source_url"
              type="url"
              inputmode="url"
              placeholder="https://… where the menu is published (online menus)"
              class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
            />
            <span
              v-if="meta.tags.includes('screenshot') && !meta.source_url.trim()"
              class="mt-1 block text-ink-2"
            >
              A screenshot without a link stays out of the public release.
            </span>
          </label>
          <div>
            <div class="text-xs text-ink-3">Tags (slices in reports)</div>
            <div class="mt-1 flex flex-wrap gap-1">
              <button
                v-for="tag in [...new Set([...TAG_SUGGESTIONS, ...meta.tags])]"
                :key="tag"
                type="button"
                class="rounded-full border px-2 py-0.5 text-xs"
                :class="
                  meta.tags.includes(tag)
                    ? 'border-[var(--accent)] bg-surface-2 text-ink-1'
                    : 'border-line text-ink-3'
                "
                :aria-pressed="meta.tags.includes(tag)"
                @click="toggleTag(tag)"
              >
                {{ tag }}
              </button>
            </div>
            <form class="mt-2 flex gap-2" @submit.prevent="addCustomTag">
              <input
                v-model="customTag"
                placeholder="own tag"
                class="w-40 rounded border border-line bg-surface-1 px-2 py-1 text-xs text-ink-1"
              />
              <button class="rounded border border-line px-2 py-1 text-xs hover:bg-surface-2">Add</button>
            </form>
          </div>
        </div>

        <div v-if="selectedPrice" class="card space-y-3 p-4 text-sm">
          <h2 class="font-semibold">Price {{ selectedPrice.id }}</h2>
          <div class="grid grid-cols-2 gap-2">
            <label class="text-xs text-ink-3">
              Value
              <input
                v-model="selectedPrice.value"
                data-hotkey-focus
                inputmode="decimal"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              />
            </label>
            <label class="text-xs text-ink-3">
              Kind
              <select
                v-model="selectedPrice.kind"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              >
                <option value="single">single</option>
                <option value="size_variant">size variant</option>
                <option value="range">range</option>
                <option value="from">from…</option>
                <option value="crossed">crossed out (old)</option>
              </select>
            </label>
            <label v-if="selectedPrice.kind === 'range'" class="text-xs text-ink-3">
              Upper bound
              <input
                v-model="selectedPrice.value_max"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              />
            </label>
            <label v-if="selectedPrice.kind === 'size_variant'" class="text-xs text-ink-3">
              Size label
              <input
                v-model="selectedPrice.size_label"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              />
            </label>
            <label class="text-xs text-ink-3">
              Currency
              <select
                v-model="selectedPrice.currency"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              >
                <option :value="null">not printed</option>
                <option value="RUB">RUB</option>
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
                <option value="KZT">KZT</option>
                <option value="RSD">RSD (din)</option>
                <option value="BAM">BAM (KM)</option>
                <option
                  v-if="
                    selectedPrice.currency &&
                    !['RUB', 'USD', 'EUR', 'KZT', 'RSD', 'BAM'].includes(selectedPrice.currency)
                  "
                  :value="selectedPrice.currency"
                >
                  {{ selectedPrice.currency }}
                </option>
              </select>
            </label>
            <label class="col-span-2 text-xs text-ink-3">
              Item
              <select
                v-model="linkedItem"
                class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
              >
                <option value="">— not linked —</option>
                <option v-for="i in draft.items" :key="i.id" :value="i.id">{{ i.name || i.id }}</option>
              </select>
            </label>
          </div>
        </div>

        <div v-if="selectedItem" class="card space-y-3 p-4 text-sm">
          <h2 class="font-semibold">Item {{ selectedItem.id }}</h2>
          <label class="block text-xs text-ink-3">
            Name, exactly as printed
            <input
              v-model="selectedItem.name"
              data-hotkey-focus
              class="mt-1 w-full rounded border border-line bg-surface-1 px-2 py-1 text-sm text-ink-1"
            />
          </label>
        </div>

        <div v-if="issues.length" class="card p-4 text-sm">
          <h2 class="mb-2 font-semibold">Before finishing ({{ issues.length }})</h2>
          <ul class="space-y-1 text-xs">
            <li v-for="(p, n) in issues.slice(0, 12)" :key="n">
              <button class="text-left text-ink-2 hover:text-ink-1" @click="selection = p.selection">
                {{ p.message }}
              </button>
            </li>
          </ul>
        </div>

        <div class="card overflow-x-auto">
          <h2 class="px-4 pt-4 text-sm font-semibold">Prices ({{ draft.prices.length }})</h2>
          <table class="data mt-2">
            <tbody>
              <tr
                v-for="p in draft.prices"
                :key="p.id"
                class="clickable"
                :class="selection === `price:${p.id}` ? 'bg-surface-2' : ''"
                @click="focusPrice(p.id, p.page)"
              >
                <td class="text-ink-3">{{ p.id }}</td>
                <td class="num">
                  {{ p.value }}
                  <span v-if="p.kind !== 'single'" class="ml-1.5 text-xs text-ink-3">
                    {{ p.kind.replace('_', ' ') }}{{ p.size_label ? ` · ${p.size_label}` : '' }}
                  </span>
                </td>
                <td :class="p.item_ids?.length ? '' : 'text-critical'">
                  {{ p.item_ids?.length ? itemName.get(p.item_ids[0]!) : 'no item' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>
