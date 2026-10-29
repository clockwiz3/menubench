<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { theme, type Theme } from '@/lib/theme'

const nav = [
  { to: '/', label: 'Runs' },
  { to: '/annotate', label: 'Annotate' },
  { to: '/try', label: 'Try it' },
]
const themes: { value: Theme; label: string }[] = [
  { value: 'system', label: 'Auto' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]
</script>

<template>
  <div class="min-h-screen">
    <header class="sticky top-0 z-20 border-b border-line bg-surface-1/90 backdrop-blur">
      <div class="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4">
        <RouterLink to="/" class="flex items-center gap-2 font-semibold tracking-tight">
          <img src="/favicon.svg" alt="" class="h-6 w-6" />
          MenuBench
        </RouterLink>
        <nav class="flex gap-1 text-sm">
          <RouterLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="rounded-md px-3 py-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink-1"
            active-class="!bg-surface-2 !text-ink-1"
            :exact-active-class="item.to === '/' ? '!bg-surface-2 !text-ink-1' : undefined"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
        <div
          class="ml-auto flex rounded-md border border-line p-0.5 text-xs"
          role="radiogroup"
          aria-label="Theme"
        >
          <button
            v-for="t in themes"
            :key="t.value"
            role="radio"
            :aria-checked="theme === t.value"
            class="rounded px-2 py-1"
            :class="theme === t.value ? 'bg-surface-2 text-ink-1' : 'text-ink-3 hover:text-ink-1'"
            @click="theme = t.value"
          >
            {{ t.label }}
          </button>
        </div>
      </div>
    </header>
    <main class="mx-auto max-w-7xl px-4 py-6">
      <RouterView />
    </main>
  </div>
</template>
