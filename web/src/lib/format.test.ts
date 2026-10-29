import { describe, expect, it } from 'vitest'
import { num, pct, shortModel, usd } from './format'

describe('format', () => {
  it('renders missing values as a dash', () => {
    expect(pct(null)).toBe('–')
    expect(usd(undefined)).toBe('–')
    expect(num(null)).toBe('–')
  })
  it('formats numbers', () => {
    expect(pct(0.9876)).toBe('98.8%')
    expect(usd(0.00061)).toBe('$0.0006')
    expect(shortModel('google/gemini-2.5-flash-lite')).toBe('gemini-2.5-flash-lite')
  })
})
