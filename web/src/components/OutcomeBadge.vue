<script setup lang="ts">
import { computed } from 'vue'
import type { Outcome } from '@/api/client'
import { MISSED, OUTCOMES } from '@/lib/outcomes'

const props = defineProps<{ outcome: Outcome | 'missed' }>()
const style = computed(() => (props.outcome === 'missed' ? MISSED : OUTCOMES[props.outcome]))
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-ink-2">
    <span
      class="inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white"
      :style="{ background: style.color }"
      aria-hidden="true"
      >{{ style.glyph }}</span
    >
    {{ style.label }}
  </span>
</template>
