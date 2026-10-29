<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, unwrap, type MenuForEditor } from '@/api/client'
import { when } from '@/lib/format'
import { useAsync } from '@/lib/useAsync'

const router = useRouter()
const reload = ref(0)
const { data: menus, error } = useAsync(
  () => reload.value,
  () => unwrap(api.GET('/api/annotate/menus')),
)

const lang = ref<'ru' | 'en'>('ru')
const uploading = ref(false)
const uploadError = ref<string | null>(null)
const dragging = ref(false)

async function upload(files: FileList | null) {
  if (!files?.length) return
  uploading.value = true
  uploadError.value = null
  const form = new FormData()
  for (const f of Array.from(files)) form.append('files', f)
  try {
    // Multipart goes through plain fetch; the typed client is JSON-only.
    const res = await fetch(`/api/annotate/menus?lang=${lang.value}`, { method: 'POST', body: form })
    const body = await res.json()
    if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : res.statusText)
    const menu = body as MenuForEditor
    router.push({ name: 'annotate-menu', params: { menuId: menu.annotation.menu_id } })
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    uploading.value = false
    dragging.value = false
  }
}

const STATUS_LABEL = {
  new: 'New',
  prelabeled: 'Pre-labelled',
  annotated: 'Annotated',
  reviewed: 'Reviewed',
} as const
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight">Annotate real menus</h1>
      <p class="mt-1 text-sm text-ink-3">
        Upload photos or PDFs, let the pipeline propose boxes, fix them. Only menus marked annotated or
        reviewed enter the real test split.
      </p>
    </div>

    <label
      class="card flex cursor-pointer flex-col items-center justify-center gap-2 border-2 border-dashed p-8 text-center"
      :class="dragging ? 'border-[var(--accent)] bg-surface-2' : ''"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="upload($event.dataTransfer?.files ?? null)"
    >
      <input
        type="file"
        class="sr-only"
        accept="image/*,.pdf"
        multiple
        @change="upload(($event.target as HTMLInputElement).files)"
      />
      <span class="text-sm font-medium">{{
        uploading ? 'Uploading…' : 'Drop menu photos or a PDF here, or click to choose'
      }}</span>
      <span class="text-xs text-ink-3">Several photos become pages of one menu. Up to 15 MB.</span>
      <span class="mt-1 flex items-center gap-2 text-xs text-ink-2" @click.stop>
        Menu language
        <select v-model="lang" class="rounded border border-line bg-surface-1 px-1 py-0.5">
          <option value="ru">Russian</option>
          <option value="en">English</option>
        </select>
      </span>
    </label>
    <p v-if="uploadError" class="card p-3 text-sm text-critical">{{ uploadError }}</p>
    <p v-if="error" class="card p-3 text-sm text-critical">{{ error }}</p>

    <section v-if="menus?.length" class="card overflow-x-auto">
      <table class="data">
        <thead>
          <tr>
            <th>Menu</th>
            <th>Status</th>
            <th>Split</th>
            <th class="text-right">Pages</th>
            <th class="text-right">Prices</th>
            <th class="text-right">Items</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="m in menus"
            :key="m.menu_id"
            class="clickable"
            @click="router.push({ name: 'annotate-menu', params: { menuId: m.menu_id } })"
          >
            <td class="font-medium">
              <RouterLink :to="{ name: 'annotate-menu', params: { menuId: m.menu_id } }" @click.stop>{{
                m.menu_id
              }}</RouterLink>
            </td>
            <td>{{ STATUS_LABEL[m.status] }}</td>
            <td class="text-ink-2">{{ m.split }}</td>
            <td class="num text-right">{{ m.pages }}</td>
            <td class="num text-right">{{ m.prices }}</td>
            <td class="num text-right">{{ m.items }}</td>
            <td class="whitespace-nowrap text-ink-3">{{ when(m.updated_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <p v-else-if="menus" class="text-sm text-ink-3">No menus uploaded yet.</p>
  </div>
</template>
