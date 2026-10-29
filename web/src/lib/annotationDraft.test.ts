import { describe, expect, it } from 'vitest'
import { addItem, addPrice, nextId, problems, remove, type Draft } from './annotationDraft'

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
