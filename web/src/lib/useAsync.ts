import { ref, watch, type Ref, type WatchSource } from 'vue'

/** Loads data when the source changes; exposes loading and error state for the template. */
export function useAsync<T>(source: WatchSource, load: () => Promise<T>) {
  const data = ref<T>() as Ref<T | undefined>
  const error = ref<string | null>(null)
  const loading = ref(false)
  watch(
    source,
    async () => {
      loading.value = true
      error.value = null
      try {
        data.value = await load()
      } catch (e) {
        error.value = e instanceof Error ? e.message : String(e)
      } finally {
        loading.value = false
      }
    },
    { immediate: true },
  )
  return { data, error, loading }
}
