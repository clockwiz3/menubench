import type { Outcome } from '@/api/client'

/** Outcome styling: status colors always ship with a label and a glyph, never color alone. */
export const OUTCOMES: Record<Outcome, { label: string; glyph: string; color: string }> = {
  correct: { label: 'Correct', glyph: '✓', color: 'var(--good)' },
  wrong_name: { label: 'Wrong item', glyph: '≠', color: 'var(--warning)' },
  crossed: { label: 'Old price', glyph: '⨯', color: 'var(--serious)' },
  spurious: { label: 'Not on menu', glyph: '!', color: 'var(--critical)' },
}

export const MISSED = { label: 'Missed', glyph: '○', color: 'var(--critical)' }
