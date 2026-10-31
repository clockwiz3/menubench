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

function center(b: BBox): [number, number] {
  return [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2]
}

/**
 * The item a price most likely belongs to: on the same page, the name on the price's row to its left,
 * else the nearest name above. Rows are compared by vertical distance in box heights.
 */
export function nearestItem(draft: Draft, priceId: string): string | null {
  const price = draft.prices.find((p) => p.id === priceId)
  if (!price) return null
  const [px, py] = center(price.bbox)
  const h = Math.max(price.bbox.y1 - price.bbox.y0, 0.005)
  let best: { id: string; score: number } | null = null
  for (const item of draft.items) {
    if (item.page !== price.page) continue
    const [ix, iy] = center(item.bbox)
    const dy = (py - iy) / h // positive: the name sits above the price
    if (dy < -1) continue // names below the price belong to the next one
    const score = Math.abs(dy) * 1 + Math.abs(px - ix) * 2 + (item.bbox.x0 > price.bbox.x1 ? 5 : 0)
    if (!best || score < best.score) best = { id: item.id, score }
  }
  return best?.id ?? null
}

/** Moves (dx, dy) or, with `resize`, grows the right and bottom edges; page-relative, clamped to the page. */
export function nudge(b: BBox, dx: number, dy: number, resize: boolean): BBox {
  const clamp = (v: number) => Math.min(1, Math.max(0, v))
  if (resize) {
    return {
      ...b,
      x1: clamp(Math.max(b.x0 + 0.002, b.x1 + dx)),
      y1: clamp(Math.max(b.y0 + 0.002, b.y1 + dy)),
    }
  }
  const w = b.x1 - b.x0
  const h = b.y1 - b.y0
  const x0 = Math.min(1 - w, Math.max(0, b.x0 + dx))
  const y0 = Math.min(1 - h, Math.max(0, b.y0 + dy))
  return { x0, y0, x1: x0 + w, y1: y0 + h }
}

/** Undo history over JSON snapshots of the draft; consecutive equal snapshots are one step. */
export class History {
  private steps: string[] = []
  private at = -1
  constructor(private readonly limit = 200) {}

  reset(snapshot: string): void {
    this.steps = [snapshot]
    this.at = 0
  }
  record(snapshot: string): void {
    if (this.steps[this.at] === snapshot) return
    this.steps = this.steps.slice(0, this.at + 1)
    this.steps.push(snapshot)
    if (this.steps.length > this.limit) this.steps.shift()
    this.at = this.steps.length - 1
  }
  undo(): string | null {
    if (this.at <= 0) return null
    return this.steps[--this.at] ?? null
  }
  redo(): string | null {
    if (this.at >= this.steps.length - 1) return null
    return this.steps[++this.at] ?? null
  }
}
