import { describe, expect, it } from 'vitest'
import {
  addItem,
  addPrice,
  History,
  nearestItem,
  nextId,
  nudge,
  problems,
  remove,
  type Draft,
} from './annotationDraft'

const box = { x0: 0.1, y0: 0.1, x1: 0.2, y1: 0.12 }

describe('annotation draft', () => {
  it('numbers ids after the largest existing one', () => {
    expect(nextId('p', [{ id: 'p2' }, { id: 'p10' }, { id: 'i40' }])).toBe('p11')
  })

  it('links a new price to the item selected just before', () => {
    const draft: Draft = { items: [], prices: [] }
    const item = addItem(draft, 0, box, null)
    const price = addPrice(draft, 0, box, `item:${item}`)
    expect(draft.prices.find((p) => p.id === price)?.item_ids).toEqual([item])
  })

  it('links a new item to a selected unlinked price', () => {
    const draft: Draft = { items: [], prices: [] }
    const price = addPrice(draft, 0, box, null)
    const item = addItem(draft, 0, box, `price:${price}`)
    expect(draft.prices[0]?.item_ids).toEqual([item])
  })

  it('removing an item unlinks its prices and reports them', () => {
    const draft: Draft = { items: [], prices: [] }
    const item = addItem(draft, 0, box, null)
    addPrice(draft, 0, box, `item:${item}`)
    draft.items[0]!.name = 'Борщ'
    draft.prices[0]!.value = '350'
    expect(problems(draft)).toEqual([])
    remove(draft, `item:${item}`)
    expect(draft.prices[0]?.item_ids).toEqual([])
    expect(problems(draft).map((p) => p.message)).toEqual(['p1: not linked to an item'])
  })
})

describe('editing helpers', () => {
  const draftWith = (): Draft => ({
    items: [
      {
        id: 'i1',
        page: 0,
        name: 'Supa',
        bbox: { x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.12 },
        section: null,
        description: null,
        catalog_id: null,
      },
      {
        id: 'i2',
        page: 0,
        name: 'Salata',
        bbox: { x0: 0.1, y0: 0.2, x1: 0.3, y1: 0.22 },
        section: null,
        description: null,
        catalog_id: null,
      },
    ],
    prices: [
      {
        id: 'p1',
        page: 0,
        value: '450',
        value_max: null,
        currency: null,
        kind: 'single',
        size_label: null,
        bbox: { x0: 0.8, y0: 0.201, x1: 0.9, y1: 0.221 },
        item_ids: [],
      },
    ],
  })

  it('links a price to the name on its row', () => {
    expect(nearestItem(draftWith(), 'p1')).toBe('i2')
  })

  it('nudges a box inside the page and grows it from the bottom-right corner', () => {
    const b = { x0: 0.95, y0: 0.5, x1: 0.99, y1: 0.52 }
    expect(nudge(b, 0.1, 0, false).x1).toBe(1)
    expect(nudge(b, 0, 0.01, true)).toEqual({ ...b, y1: 0.53 })
  })

  it('undoes and redoes snapshots', () => {
    const h = new History()
    h.reset('a')
    h.record('b')
    h.record('b')
    h.record('c')
    expect(h.undo()).toBe('b')
    expect(h.undo()).toBe('a')
    expect(h.undo()).toBeNull()
    expect(h.redo()).toBe('b')
    h.record('d') // a new edit drops the redo branch
    expect(h.redo()).toBeNull()
  })
})
