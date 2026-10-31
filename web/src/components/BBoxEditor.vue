<script setup lang="ts">
import type Konva from 'konva'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BBox } from '@/api/client'

export interface EditorBox {
  id: string
  bbox: BBox
  color: string
  label?: string
  dashed?: boolean
}
export type DrawMode = 'select' | 'price' | 'item'

const props = withDefaults(
  defineProps<{
    src: string
    boxes: EditorBox[]
    selected?: string | null
    mode?: DrawMode
    zoom?: number
  }>(),
  { selected: null, mode: 'select', zoom: 1 },
)
const emit = defineEmits<{
  select: [id: string | null]
  update: [id: string, bbox: BBox]
  create: [kind: 'price' | 'item', bbox: BBox]
}>()

const container = ref<HTMLDivElement>()
const stageRef = ref<{ getNode: () => Konva.Stage }>()
const trRef = ref<{ getNode: () => Konva.Transformer }>()
const image = ref<HTMLImageElement>()
const width = ref(0)
const themeTick = ref(0)
let resize: ResizeObserver | undefined
const bump = () => themeTick.value++
const themeObserver = new MutationObserver(bump)

watch(
  () => props.src,
  (src) => {
    image.value = undefined
    const img = new window.Image()
    img.onload = () => (image.value = img)
    img.src = src
  },
  { immediate: true },
)
onMounted(() => {
  // Whole pixels and a dead band: a scrollbar appearing or disappearing must not start a resize loop.
  resize = new ResizeObserver(([entry]) => {
    const next = Math.floor(entry?.contentRect.width ?? 0)
    if (Math.abs(next - width.value) > 2) width.value = next
  })
  if (container.value) resize.observe(container.value)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})
onBeforeUnmount(() => {
  resize?.disconnect()
  themeObserver.disconnect()
  cancelAnimationFrame(raf)
})

const resolve = computed(() => {
  void themeTick.value
  const css = getComputedStyle(document.documentElement)
  return (color: string) => {
    const m = /^var\((--[\w-]+)\)$/.exec(color)
    return m ? css.getPropertyValue(m[1]!).trim() || '#888' : color
  }
})

const scale = computed(() => (image.value ? (width.value / image.value.naturalWidth) * props.zoom : 1))
const stage = computed(() => ({
  width: image.value ? image.value.naturalWidth * scale.value : 0,
  height: image.value ? image.value.naturalHeight * scale.value : 0,
}))

function toPixels(b: BBox) {
  const { width: w, height: h } = stage.value
  return { x: b.x0 * w, y: b.y0 * h, width: (b.x1 - b.x0) * w, height: (b.y1 - b.y0) * h }
}
function toBox(x: number, y: number, w: number, h: number): BBox {
  const { width: W, height: H } = stage.value
  const clamp = (v: number) => Math.min(1, Math.max(0, v))
  const x0 = clamp(Math.min(x, x + w) / W)
  const y0 = clamp(Math.min(y, y + h) / H)
  const x1 = clamp(Math.max(x, x + w) / W)
  const y1 = clamp(Math.max(y, y + h) / H)
  return { x0, y0, x1: Math.max(x1, x0 + 0.001), y1: Math.max(y1, y0 + 0.001) }
}

const rects = computed(() =>
  props.boxes.map((b) => ({
    box: b,
    config: {
      id: b.id,
      ...toPixels(b.bbox),
      stroke: resolve.value(b.color),
      strokeWidth: b.id === props.selected ? 3 : 2,
      dash: b.dashed ? [6, 4] : undefined,
      fill: 'rgba(0,0,0,0.001)',
      // Every box drags in select mode, so press-and-drag works on the first press, not only once selected.
      draggable: props.mode === 'select',
      dragDistance: 3, // a click that wobbles a pixel is still a click
      strokeScaleEnabled: false,
    },
  })),
)

// The transformer follows the selected box.
watch(
  () => [props.selected, props.mode, props.boxes.length, stage.value.width] as const,
  async () => {
    await nextTick()
    const tr = trRef.value?.getNode()
    const st = stageRef.value?.getNode()
    if (!tr || !st) return
    // Ids look like `price:p3`; Konva's `#id` selector does not understand the colon, so match the id directly.
    const node =
      props.selected && props.mode === 'select'
        ? st.findOne((n: Konva.Node) => n.id() === props.selected)
        : undefined
    tr.nodes(node ? [node] : [])
  },
)

// A selected box sends out two fading rings, so the eye finds it on a busy page.
const RIPPLE_MS = 700
const RIPPLE_GAP_MS = 160
const RIPPLE_GROW = 28
interface Ripple {
  key: number
  id: string
  start: number
}
const ripples = ref<Ripple[]>([])
const now = ref(0)
let raf = 0
let rippleKey = 0
let pending: string | null = null
// A box picked on the canvas is already in view: scrolling to it would yank it from under the cursor mid-drag.
let pickedOnCanvas = false
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
function tick() {
  now.value = performance.now()
  ripples.value = ripples.value.filter((r) => now.value - r.start < RIPPLE_MS)
  raf = ripples.value.length ? requestAnimationFrame(tick) : 0
}
// Selecting from the price table can point at a box outside the visible part of the canvas.
const marker = ref<HTMLDivElement>()
const markerStyle = computed(() => {
  const box = props.boxes.find((b) => b.id === props.selected)
  if (!box) return { display: 'none' }
  const px = toPixels(box.bbox)
  const pad = RIPPLE_GROW
  return {
    left: `${px.x - pad}px`,
    top: `${px.y - pad}px`,
    width: `${px.width + 2 * pad}px`,
    height: `${px.height + 2 * pad}px`,
  }
})
function inView(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect()
  const frame = container.value?.parentElement?.getBoundingClientRect()
  const top = Math.max(0, frame?.top ?? 0)
  const bottom = Math.min(window.innerHeight, frame?.bottom ?? window.innerHeight)
  const left = Math.max(0, frame?.left ?? 0)
  const right = Math.min(window.innerWidth, frame?.right ?? window.innerWidth)
  return r.top >= top && r.bottom <= bottom && r.left >= left && r.right <= right
}
const SCROLL_MS = 300
async function ripple(id: string, scroll: boolean) {
  await nextTick()
  let delay = 0
  if (scroll && marker.value && !inView(marker.value)) {
    marker.value.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
    delay = SCROLL_MS
  }
  const start = performance.now() + delay
  ripples.value = [0, 1].map((i) => ({ key: rippleKey++, id, start: start + i * RIPPLE_GAP_MS }))
  if (!raf) raf = requestAnimationFrame(tick)
}
// The box may not be on screen yet (another page is loading), so the ripple waits for it.
watch(
  () => props.selected,
  (id) => (pending = id && !reducedMotion.matches ? id : null),
)
watch(
  () => [props.selected, stage.value.width, rects.value.some((r) => r.box.id === props.selected)] as const,
  ([id, w, present]) => {
    if (pending && id === pending && w && present) {
      pending = null
      void ripple(id, !pickedOnCanvas)
      pickedOnCanvas = false
    }
  },
)
const rippleConfigs = computed(() =>
  ripples.value.flatMap((r) => {
    const t = (now.value - r.start) / RIPPLE_MS
    const box = props.boxes.find((b) => b.id === r.id)
    if (!box || t < 0 || t >= 1) return []
    const ease = 1 - (1 - t) ** 3
    const grow = ease * RIPPLE_GROW
    const px = toPixels(box.bbox)
    return [
      {
        key: r.key,
        x: px.x - grow,
        y: px.y - grow,
        width: px.width + 2 * grow,
        height: px.height + 2 * grow,
        cornerRadius: grow * 0.35,
        stroke: resolve.value(box.color),
        strokeWidth: 3 - 2 * ease,
        opacity: 0.9 * (1 - t),
        listening: false,
      },
    ]
  }),
)

function pick(id: string) {
  if (props.mode !== 'select') return
  pickedOnCanvas = id !== props.selected
  emit('select', id)
}
// Dragging takes over: the rings would stay behind at the old spot.
function onDragStart(id: string) {
  ripples.value = []
  pending = null
  if (id !== props.selected) emit('select', id)
}

function commit(id: string, event: Konva.KonvaEventObject<Event>) {
  const node = event.target
  const w = node.width() * node.scaleX()
  const h = node.height() * node.scaleY()
  node.scaleX(1)
  node.scaleY(1)
  emit('update', id, toBox(node.x(), node.y(), w, h))
}

// Drawing a new box in price/item mode.
const drawing = ref<{ x: number; y: number; w: number; h: number } | null>(null)
function pointer() {
  return stageRef.value?.getNode().getPointerPosition() ?? { x: 0, y: 0 }
}
function onDown(event: Konva.KonvaEventObject<MouseEvent>) {
  if (props.mode === 'select') {
    if (event.target.getClassName() === 'Image' || event.target === event.target.getStage())
      emit('select', null)
    return
  }
  const p = pointer()
  drawing.value = { x: p.x, y: p.y, w: 0, h: 0 }
}
function onMove() {
  if (!drawing.value) return
  const p = pointer()
  drawing.value = { ...drawing.value, w: p.x - drawing.value.x, h: p.y - drawing.value.y }
}
function onUp() {
  const d = drawing.value
  drawing.value = null
  if (!d || props.mode === 'select' || Math.abs(d.w) < 4 || Math.abs(d.h) < 4) return
  emit('create', props.mode, toBox(d.x, d.y, d.w, d.h))
}
const draftConfig = computed(() =>
  drawing.value
    ? {
        x: drawing.value.x,
        y: drawing.value.y,
        width: drawing.value.w,
        height: drawing.value.h,
        stroke: resolve.value(props.mode === 'price' ? 'var(--series-2)' : 'var(--series-1)'),
        strokeWidth: 2,
        dash: [4, 3],
        listening: false,
      }
    : null,
)
</script>

<template>
  <div ref="container" class="relative w-full" :class="mode === 'select' ? '' : 'cursor-crosshair'">
    <v-stage
      v-if="image && width"
      ref="stageRef"
      :config="stage"
      @mousedown="onDown"
      @mousemove="onMove"
      @mouseup="onUp"
    >
      <v-layer>
        <v-image :config="{ image, width: stage.width, height: stage.height }" />
        <v-rect
          v-for="r in rects"
          :key="r.box.id"
          :config="r.config"
          @mousedown="pick(r.box.id)"
          @dragstart="onDragStart(r.box.id)"
          @dragend="commit(r.box.id, $event)"
          @transformend="commit(r.box.id, $event)"
        />
        <v-rect v-for="r in rippleConfigs" :key="r.key" :config="r" />
        <v-rect v-if="draftConfig" :config="draftConfig" />
        <v-transformer
          ref="trRef"
          :config="{
            rotateEnabled: false,
            keepRatio: false,
            ignoreStroke: true,
            anchorSize: 7,
            borderDash: [3, 3],
          }"
        />
      </v-layer>
    </v-stage>
    <div v-else class="flex h-64 items-center justify-center text-sm text-ink-3">Loading image…</div>
    <div ref="marker" class="pointer-events-none absolute" :style="markerStyle" aria-hidden="true" />
  </div>
</template>
