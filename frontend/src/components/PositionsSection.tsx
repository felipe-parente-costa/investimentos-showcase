import { useEffect, useMemo, useState } from 'react'
import { getMonthlyReport, getMonthlyReports, type Position } from '../api/client'
import type { GroupDef, Groupable } from '../lib/grouping'
import { formatMoney, formatPercent } from '../lib/format'
import PositionsTable from './PositionsTable'
import Sparkline from './Sparkline'

// How many of the most recent monthly snapshots feed the group trend line.
// The app only has a few months of real history today; fewer points than
// this just means a shorter (still honest) line, not a bug.
const SPARKLINE_MONTHS = 6

interface Props {
  positions: Position[]
  // Maps a position to its group id; groupMeta provides label/color per id.
  // Takes the narrow Groupable shape (not the full live Position) so the
  // same function also groups historical SnapshotPosition rows for the
  // sparkline below.
  groupOf: (p: Groupable) => string
  groupMeta: Record<string, GroupDef>
  // Currency of the value column / headers (BRL default; USD for EUA).
  valueCurrency?: string
  // Show the indexer column in the FLAT view (Renda Fixa).
  showIndexer?: boolean
  // Hide the DY column where it never applies (Renda Fixa).
  showDy?: boolean
}

interface Group {
  id: string
  meta: GroupDef
  positions: Position[]
  total: number
  // Value-weighted DY of the group; null where DY never applies (fixed
  // income has none by definition, crypto is excluded by product decision),
  // so those headers show nothing instead of a misleading 0%.
  dy: number | null
}

function groupDy(positions: Position[]): number | null {
  const eligible = positions.filter(
    (p) =>
      p.market !== 'crypto' &&
      p.dy_12m_pct != null &&
      p.market_value_brl != null,
  )
  const value = eligible.reduce((sum, p) => sum + Number(p.market_value_brl), 0)
  if (value <= 0) return null
  return (
    eligible.reduce(
      (sum, p) => sum + Number(p.dy_12m_pct) * Number(p.market_value_brl),
      0,
    ) / value
  )
}

function valueOf(p: Position): number {
  return p.market_value_brl != null ? Number(p.market_value_brl) : 0
}

export default function PositionsSection({
  positions,
  groupOf,
  groupMeta,
  valueCurrency = 'BRL',
  showIndexer = false,
  showDy = true,
}: Props) {
  const [grouped, setGrouped] = useState(true)
  const [sparklines, setSparklines] = useState<Record<string, number[]>>({})

  // Group value trend over the last few monthly snapshots — fetched once
  // per mount, independent of the live `positions` prop. Historical
  // SnapshotPosition rows carry the same asset_class/market/indexer fields
  // groupOf needs, so the exact same grouping used for the live view also
  // buckets the past months (Groupable is the common subset).
  useEffect(() => {
    let cancelled = false
    getMonthlyReports()
      .then((list) => {
        const months = list.items.slice(-SPARKLINE_MONTHS).map((s) => s.year_month)
        return Promise.all(months.map((ym) => getMonthlyReport(ym)))
      })
      .then((details) => {
        if (cancelled) return
        const ids = new Set<string>()
        const perMonth = details.map((detail) => {
          const totals: Record<string, number> = {}
          for (const p of detail.positions) {
            const id = groupOf(p)
            totals[id] = (totals[id] ?? 0) + Number(p.market_value_brl)
            ids.add(id)
          }
          return totals
        })
        const byGroup: Record<string, number[]> = {}
        for (const id of ids) {
          byGroup[id] = perMonth.map((totals) => totals[id] ?? 0)
        }
        setSparklines(byGroup)
      })
      .catch(() => {
        if (!cancelled) setSparklines({})
      })
    return () => {
      cancelled = true
    }
  }, [groupOf])

  const sectionTotal = useMemo(
    () => positions.reduce((sum, p) => sum + valueOf(p), 0),
    [positions],
  )

  // Build groups, ordered by total value descending.
  const groups = useMemo<Group[]>(() => {
    const byId = new Map<string, Position[]>()
    for (const p of positions) {
      const id = groupOf(p)
      const arr = byId.get(id) ?? []
      arr.push(p)
      byId.set(id, arr)
    }
    return [...byId.entries()]
      .map(([id, ps]) => ({
        id,
        meta: groupMeta[id] ?? { label: id, color: 'var(--color-slate-500)' },
        positions: ps,
        total: ps.reduce((sum, p) => sum + valueOf(p), 0),
        dy: groupDy(ps),
      }))
      .sort((a, b) => b.total - a.total)
  }, [positions, groupOf, groupMeta])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-slate-400">
          Posições <span className="text-xs text-slate-500">({positions.length})</span>
        </p>
        <div className="flex gap-1 rounded-lg border border-slate-700 bg-slate-950 p-1 text-xs">
          {(
            [
              ['grouped', 'Agrupado'],
              ['flat', 'Lista plana'],
            ] as [string, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setGrouped(value === 'grouped')}
              className={`rounded-md px-3 py-1 font-medium ${
                (value === 'grouped') === grouped
                  ? 'bg-sky-600 text-inkbrass'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {grouped ? (
        <div className="space-y-2">
          {groups.map((group) => (
            <CollapsibleGroup
              key={group.id}
              group={group}
              sectionTotal={sectionTotal}
              valueCurrency={valueCurrency}
              showDy={showDy}
              sparkline={sparklines[group.id]}
            />
          ))}
        </div>
      ) : (
        <PositionsTable
          positions={positions}
          showIndexer={showIndexer}
          valueCurrency={valueCurrency}
          showDy={showDy}
          stickyHeader
        />
      )}
    </div>
  )
}

function CollapsibleGroup({
  group,
  sectionTotal,
  valueCurrency,
  showDy,
  sparkline,
}: {
  group: Group
  sectionTotal: number
  valueCurrency: string
  showDy: boolean
  sparkline?: number[]
}) {
  const [open, setOpen] = useState(false)
  const share = sectionTotal > 0 ? group.total / sectionTotal : 0

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-800/40"
      >
        <span className="text-slate-500">{open ? '▾' : '▸'}</span>
        <span
          className="h-3 w-3 shrink-0 rounded-sm"
          style={{ backgroundColor: group.meta.color }}
        />
        <span className="font-medium text-slate-200">{group.meta.label}</span>
        <span className="text-xs text-slate-500">
          {group.positions.length} {group.positions.length === 1 ? 'ativo' : 'ativos'}
        </span>
        <span className="ml-auto flex items-center gap-3">
          {sparkline && sparkline.length >= 2 && (
            <span
              className="hidden sm:block"
              title={`Patrimônio do grupo nos últimos ${sparkline.length} meses`}
            >
              <Sparkline values={sparkline} color={group.meta.color} />
            </span>
          )}
          <span className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-slate-800 sm:block">
            <span
              className="block h-full rounded-full"
              style={{ width: `${share * 100}%`, backgroundColor: group.meta.color }}
            />
          </span>
          <span className="text-xs text-slate-500">{formatPercent(share)}</span>
          <span className="tabular-nums font-medium text-slate-100">
            {formatMoney(String(group.total), valueCurrency)}
          </span>
          {/* Fixed-width slot so the values stay column-aligned between
              groups with and without DY (RF/Cripto render it empty). */}
          {showDy && (
            <span
              className="w-16 text-right text-xs tabular-nums text-slate-500"
              title="DY 12m do grupo (média ponderada pelo valor)"
            >
              {group.dy != null && `DY ${formatPercent(group.dy)}`}
            </span>
          )}
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800">
          <PositionsTable
            positions={group.positions}
            valueCurrency={valueCurrency}
            hideClass
            showDy={showDy}
          />
        </div>
      )}
    </div>
  )
}
