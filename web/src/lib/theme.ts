import { ref, watch } from 'vue'

export type Theme = 'system' | 'light' | 'dark'

function stored(): Theme {
  try {
    const v = localStorage.getItem('menubench.theme')
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export const theme = ref<Theme>(stored())

watch(
  theme,
  (value) => {
    const root = document.documentElement
    if (value === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', value)
    try {
      localStorage.setItem('menubench.theme', value)
    } catch {
      /* storage unavailable: the choice lasts for this page view */
    }
  },
  { immediate: true },
)
