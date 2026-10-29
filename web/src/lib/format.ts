export function pct(value: number | null | undefined, digits = 1): string {
  return value == null ? '–' : `${(value * 100).toFixed(digits)}%`
}

export function usd(value: number | null | undefined, digits = 4): string {
  return value == null ? '–' : `$${value.toFixed(digits)}`
}

export function num(value: number | null | undefined, digits = 2): string {
  return value == null ? '–' : value.toFixed(digits)
}

export function seconds(value: number | null | undefined): string {
  return value == null ? '–' : `${value.toFixed(1)} s`
}

export function shortModel(id: string): string {
  return id.split('/').pop() ?? id
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
