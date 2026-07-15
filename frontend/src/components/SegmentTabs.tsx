import type { Market, Segment } from '../api/client'
import { MARKET_LABELS, formatMoney } from '../lib/format'

export type SegmentFilter = 'all' | Market

interface Props {
  segments: Segment[]
  totalBrl: string
  selected: SegmentFilter
  onSelect: (segment: SegmentFilter) => void
}

export default function SegmentTabs({ segments, totalBrl, selected, onSelect }: Props) {
  const tabs: { value: SegmentFilter; label: string; total: string; count: number }[] = [
    {
      value: 'all',
      label: 'Tudo',
      total: totalBrl,
      count: segments.reduce((sum, s) => sum + s.position_count, 0),
    },
    ...segments.map((segment) => ({
      value: segment.market as SegmentFilter,
      label: MARKET_LABELS[segment.market],
      total: segment.total_brl,
      count: segment.position_count,
    })),
  ]

  return (
    <div className="flex flex-wrap gap-2">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          onClick={() => onSelect(tab.value)}
          className={`rounded-lg border px-4 py-2 text-left transition-colors ${
            selected === tab.value
              ? 'border-sky-500 bg-sky-500/10'
              : 'border-slate-800 bg-slate-900 hover:border-slate-600'
          }`}
        >
          <span className="block text-xs text-slate-400">
            {tab.label} · {tab.count} {tab.count === 1 ? 'posição' : 'posições'}
          </span>
          <span className="block text-sm font-medium tabular-nums">
            {formatMoney(tab.total)}
          </span>
        </button>
      ))}
    </div>
  )
}
