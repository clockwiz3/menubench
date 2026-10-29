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
  resize = new ResizeObserver(([e]) => (width.value = e?.contentRect.width ?? 0))
  if (container.value) resize.observe(container.value)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})
onBeforeUnmount(() => {
  resize?.disconnect()
  themeObserver.disconnect()
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
      draggable: b.id === props.selected && props.mode === 'select',
      strokeScaleEnabled: false,
    },
  })),
)

// The transformer follows the selected box.
watch(
  () => [props.selected, props.boxes.length, stage.value.width] as const,
  async () => {
    await nextTick()
    const tr = trRef.value?.getNode()
    const st = stageRef.value?.getNode()
    if (!tr || !st) return
    const node =
      props.selected && props.mode === 'select' ? st.findOne(`#${CSS.escape(props.selected)}`) : null
    tr.nodes(node ? [node] : [])
  },
)

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
  <div
    ref="container"
    class="relative w-full overflow-auto"
    :class="mode === 'select' ? '' : 'cursor-crosshair'"
  >
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
          @mousedown="mode === 'select' && emit('select', r.box.id)"
          @dragend="commit(r.box.id, $event)"
          @transformend="commit(r.box.id, $event)"
        />
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
  </div>
</template>
