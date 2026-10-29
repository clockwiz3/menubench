import type { BBox, MenuItem, PriceAnnotation } from '@/api/client'

export interface Draft {
  items: MenuItem[]
  prices: PriceAnnotation[]
}

/** Selection key: `price:p3` or `item:i2`. */
export type Selection = `price:${string}` | `item:${string}` | null

export function nextId(prefix: 'p' | 'i', taken: { id: string }[]): string {
  const max = taken.reduce((m, x) => {
    const n = Number(x.id.slice(1))
    return x.id.startsWith(prefix) && Number.isFinite(n) ? Math.max(m, n) : m
  }, 0)
  return `${prefix}${max + 1}`
}

/**
 * Adds a price. If an item was selected just before, the price is linked to it:
 * draw the name, then its price, and they are connected without extra clicks.
 */
export function addPrice(draft: Draft, page: number, bbox: BBox, selection: Selection): string {
  const id = nextId('p', draft.prices)
  const itemId = selection?.startsWith('item:') ? selection.slice(5) : null
  draft.prices.push({
    id,
    page,
    value: '0',
    value_max: null,
    currency: null,
    kind: 'single',
    size_label: null,
    bbox,
    item_ids: itemId ? [itemId] : [],
  })
  return id
}

/** Adds an item; a selected price that has no item yet gets linked to it. */
export function addItem(draft: Draft, page: number, bbox: BBox, selection: Selection): string {
  const id = nextId('i', draft.items)
  draft.items.push({ id, page, name: '', bbox, section: null, description: null, catalog_id: null })
  if (selection?.startsWith('price:')) {
    const price = draft.prices.find((p) => p.id === selection.slice(6))
    if (price && !price.item_ids?.length) price.item_ids = [id]
  }
  return id
}

export function remove(draft: Draft, selection: Selection): void {
  if (!selection) return
  if (selection.startsWith('price:')) {
    draft.prices = draft.prices.filter((p) => p.id !== selection.slice(6))
  } else {
    const id = selection.slice(5)
    draft.items = draft.items.filter((i) => i.id !== id)
    for (const p of draft.prices) p.item_ids = (p.item_ids ?? []).filter((x) => x !== id)
  }
}

export interface Problem {
  selection: Selection
  message: string
}

/** Everything that blocks marking the menu as annotated. */
export function problems(draft: Draft): Problem[] {
  const out: Problem[] = []
  for (const p of draft.prices) {
    const value = Number(p.value)
    if (!Number.isFinite(value) || value <= 0)
      out.push({ selection: `price:${p.id}`, message: `${p.id}: price value is missing` })
    if (!p.item_ids?.length)
      out.push({ selection: `price:${p.id}`, message: `${p.id}: not linked to an item` })
    if (p.kind === 'range' && !(Number(p.value_max) > value))
      out.push({
        selection: `price:${p.id}`,
        message: `${p.id}: a range needs an upper bound above the price`,
      })
  }
  for (const i of draft.items) {
    if (!i.name.trim()) out.push({ selection: `item:${i.id}`, message: `${i.id}: item name is empty` })
  }
  return out
}
