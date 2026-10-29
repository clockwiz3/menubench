<script setup lang="ts">
import type Konva from 'konva'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BBox } from '@/api/client'

export interface CanvasBox {
  id: string
  bbox: BBox
  /** A CSS color or a `var(--token)`; tokens are resolved because the canvas cannot read CSS. */
  color: string
  label?: string
  dashed?: boolean
  thin?: boolean
}

const props = withDefaults(
  defineProps<{ src: string; boxes: CanvasBox[]; selected?: string | null; zoom?: number }>(),
  { selected: null, zoom: 1 },
)
const emit = defineEmits<{ select: [id: string | null]; hover: [id: string | null] }>()

const container = ref<HTMLDivElement>()
const image = ref<HTMLImageElement>()
const width = ref(0)
const hovered = ref<string | null>(null)
const pointer = ref({ x: 0, y: 0 })
const themeTick = ref(0)
let resize: ResizeObserver | undefined
let media: MediaQueryList | undefined
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
  resize = new ResizeObserver(([entry]) => (width.value = entry?.contentRect.width ?? 0))
  if (container.value) resize.observe(container.value)
  media = window.matchMedia('(prefers-color-scheme: dark)')
  media.addEventListener('change', bump)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})
onBeforeUnmount(() => {
  resize?.disconnect()
  media?.removeEventListener('change', bump)
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

function geometry(box: CanvasBox) {
  const { width: w, height: h } = stage.value
  return {
    x: box.bbox.x0 * w - 2,
    y: box.bbox.y0 * h - 2,
    width: (box.bbox.x1 - box.bbox.x0) * w + 4,
    height: (box.bbox.y1 - box.bbox.y0) * h + 4,
    cornerRadius: 3,
  }
}

const shapes = computed(() =>
  props.boxes.map((box) => {
    const color = resolve.value(box.color)
    const active = box.id === props.selected || box.id === hovered.value
    return {
      box,
      active,
      outline: {
        ...geometry(box),
        stroke: color,
        strokeWidth: active ? 3 : box.thin ? 1 : 2,
        dash: box.dashed ? [5, 4] : undefined,
        fill: 'rgba(0,0,0,0.001)', // makes the whole box hoverable, not just its border
      },
      wash: { ...geometry(box), fill: color, opacity: 0.22, listening: false },
    }
  }),
)

const hoveredBox = computed(() => props.boxes.find((b) => b.id === hovered.value))

function onEnter(box: CanvasBox, event: Konva.KonvaEventObject<MouseEvent>) {
  hovered.value = box.id
  pointer.value = { x: event.evt.offsetX, y: event.evt.offsetY }
  emit('hover', box.id)
}
function onLeave() {
  hovered.value = null
  emit('hover', null)
}
</script>

<template>
  <div ref="container" class="relative w-full overflow-auto">
    <v-stage v-if="image && width" :config="stage">
      <v-layer>
        <v-image :config="{ image, width: stage.width, height: stage.height }" />
        <template v-for="s in shapes" :key="s.box.id">
          <v-rect v-if="s.active" :config="s.wash" />
          <v-rect
            :config="s.outline"
            @mouseenter="onEnter(s.box, $event)"
            @mouseleave="onLeave"
            @click="emit('select', s.box.id === selected ? null : s.box.id)"
          />
        </template>
      </v-layer>
    </v-stage>
    <div v-else class="flex h-64 items-center justify-center text-sm text-ink-3">Loading image…</div>
    <div
      v-if="hoveredBox?.label"
      class="pointer-events-none absolute z-10 max-w-xs rounded-md border border-line bg-surface-1 px-2 py-1 text-xs text-ink-1 shadow-lg"
      :style="{ left: `${pointer.x + 14}px`, top: `${pointer.y + 14}px` }"
    >
      {{ hoveredBox.label }}
    </div>
  </div>
</template>
