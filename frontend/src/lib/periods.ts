import type { Granularity } from '../api/client'

export type Period = '1m' | '3m' | '6m' | 'ytd' | '1y' | 'max'

// Granularity is matched to the window so charts stay readable: short
// windows get daily points, long ones weekly/monthly.
export const PERIOD_OPTIONS: { value: Period; label: string; granularity: Granularity }[] = [
  { value: '1m', label: '1M', granularity: 'daily' },
  { value: '3m', label: '3M', granularity: 'daily' },
  { value: '6m', label: '6M', granularity: 'weekly' },
  { value: 'ytd', label: 'YTD', granularity: 'weekly' },
  { value: '1y', label: '1A', granularity: 'weekly' },
  { value: 'max', label: 'Máx', granularity: 'monthly' },
]

export function granularityFor(period: Period) {
  return PERIOD_OPTIONS.find((p) => p.value === period)?.granularity ?? 'monthly'
}

export function periodStart(period: Period, today = new Date()): Date | null {
  const start = new Date(today)
  switch (period) {
    case '1m':
      start.setMonth(start.getMonth() - 1)
      return start
    case '3m':
      start.setMonth(start.getMonth() - 3)
      return start
    case '6m':
      start.setMonth(start.getMonth() - 6)
      return start
    case 'ytd':
      return new Date(today.getFullYear(), 0, 1)
    case '1y':
      start.setFullYear(start.getFullYear() - 1)
      return start
    case 'max':
      return null
  }
}

export function filterByPeriod<T extends { date: string }>(
  points: T[],
  period: Period,
): T[] {
  const start = periodStart(period)
  if (start === null) return points
  const cutoff = start.toISOString().slice(0, 10)
  return points.filter((p) => p.date >= cutoff)
}
