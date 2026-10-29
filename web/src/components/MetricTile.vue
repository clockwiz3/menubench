<script setup lang="ts">
defineProps<{ label: string; value: string; hint?: string }>()
</script>

<template>
  <div class="card px-4 py-3">
    <div class="text-xs text-ink-3">{{ label }}</div>
    <div class="num mt-1 text-2xl font-semibold tracking-tight text-ink-1">{{ value }}</div>
    <div v-if="hint" class="mt-0.5 text-xs text-ink-3">{{ hint }}</div>
  </div>
</template>
