export interface HoveredCell {
  a: string
  b: string
  value: number | null
}

// -1 → red, 0 → neutral, +1 → green. Alpha scales with magnitude.
// Pólos alinhados aos tons de ganho/perda do tema Ledger (#3fb968/#e5484d).
export function cellColor(value: number | null): string {
  if (value == null) return '#1b1917'
  if (value >= 0) return `rgba(63, 185, 104, ${Math.min(value, 1)})`
  return `rgba(229, 72, 77, ${Math.min(-value, 1)})`
}

export function formatCoef(value: number | null): string {
  return value == null ? '—' : (value >= 0 ? '+' : '') + value.toFixed(2)
}
