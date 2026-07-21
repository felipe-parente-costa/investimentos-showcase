export interface HoveredCell {
  a: string
  b: string
  value: number | null
}

// -1 → red, 0 → neutral, +1 → green. Alpha (via color-mix, não rgba com RGB
// fixo) escala com a magnitude — assim os pólos seguem as variáveis de
// ganho/perda do tema atual (--color-green-400/--color-red-400) em vez de um
// RGB congelado no valor do escuro, e o mesmo código funciona claro/escuro.
export function cellColor(value: number | null): string {
  if (value == null) return 'var(--color-slate-900)'
  const pct = Math.round(Math.min(Math.abs(value), 1) * 100)
  const pole = value >= 0 ? 'var(--color-green-400)' : 'var(--color-red-400)'
  return `color-mix(in srgb, ${pole} ${pct}%, transparent)`
}

export function formatCoef(value: number | null): string {
  return value == null ? '—' : (value >= 0 ? '+' : '') + value.toFixed(2)
}
