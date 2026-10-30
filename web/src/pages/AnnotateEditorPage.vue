<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, unwrap, type AnnotationStatus, type BBox, type MenuForEditor } from '@/api/client'
import BBoxEditor, { type DrawMode, type EditorBox } from '@/components/BBoxEditor.vue'
import { addItem, addPrice, problems, remove, type Draft, type Selection } from '@/lib/annotationDraft'

const props = defineProps<{ menuId: string }>()

const menu = ref<MenuForEditor>()
const draft = ref<Draft>({ items: [], prices: [] })
const meta = ref({
  lang: 'ru',
  status: 'new' as AnnotationStatus,
  split: 'real-test',
  notes: '',
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
    tags: [...(data.annotation.tags ?? [])],
  }
  saved.value = snapshot()
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
watch(() => props.menuId, fetchMenu, { immediate: true })

async function save(status?: AnnotationStatus) {
  busy.value = 'save'
  error.value = null
  try {
    const saved = await unwrap(
      api.PUT('/api/annotate/menus/{menu_id}', {
        params: { path: { menu_id: props.menuId } },
        body: {
          ...meta.value,
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

function onKey(e: KeyboardEvent) {
  const typing =
    e.target instanceof HTMLInputElement ||
    e.target instanceof HTMLSelectElement ||
    e.target instanceof HTMLTextAreaElement
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    void save()
    return
  }
  if (typing) return
  if (e.key === 'p') mode.value = 'price'
  else if (e.key === 'i') mode.value = 'item'
  else if (e.key === 'Escape') {
    mode.value = 'select'
    selection.value = null
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
          @click="save(meta.status === 'annotated' ? 'reviewed' : 'annotated')"
        >
          {{ meta.status === 'annotated' ? 'Mark reviewed' : 'Finish' }}
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
          <span class="text-ink-3"
            >Del removes the selection · Ctrl+S saves · dashed price = no item yet</span
          >
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
                  {{ p.value
                  }}<span v-if="p.kind !== 'single'" class="text-xs text-ink-3"> {{ p.kind }}</span>
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
