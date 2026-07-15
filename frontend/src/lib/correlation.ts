export interface HoveredCell {
  a: string
  b: string
  value: number | null
}

// -1 → red, 0 → neutral slate, +1 → green. Alpha scales with magnitude.
export function cellColor(value: number | null): string {
  if (value == null) return '#0f172a'
  if (value >= 0) return `rgba(34, 197, 94, ${Math.min(value, 1)})`
  return `rgba(239, 68, 68, ${Math.min(-value, 1)})`
}

export function formatCoef(value: number | null): string {
  return value == null ? '—' : (value >= 0 ? '+' : '') + value.toFixed(2)
}
