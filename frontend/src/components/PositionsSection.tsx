import { useMemo, useState } from 'react'
import type { Position } from '../api/client'
import type { GroupDef } from '../lib/grouping'
import { formatMoney, formatPercent } from '../lib/format'
import PositionsTable from './PositionsTable'

interface Props {
  positions: Position[]
  // Maps a position to its group id; groupMeta provides label/color per id.
  groupOf: (p: Position) => string
  groupMeta: Record<string, GroupDef>
  // Currency of the value column / headers (BRL default; USD for EUA).
  valueCurrency?: string
  // Show the indexer column in the FLAT view (Renda Fixa).
  showIndexer?: boolean
}

interface Group {
  id: string
  meta: GroupDef
  positions: Position[]
  total: number
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
}: Props) {
  const [grouped, setGrouped] = useState(true)

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
        meta: groupMeta[id] ?? { label: id, color: '#64748b' },
        positions: ps,
        total: ps.reduce((sum, p) => sum + valueOf(p), 0),
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
                  ? 'bg-sky-600 text-white'
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
            />
          ))}
        </div>
      ) : (
        <PositionsTable
          positions={positions}
          showIndexer={showIndexer}
          valueCurrency={valueCurrency}
        />
      )}
    </div>
  )
}

function CollapsibleGroup({
  group,
  sectionTotal,
  valueCurrency,
}: {
  group: Group
  sectionTotal: number
  valueCurrency: string
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
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800">
          <PositionsTable
            positions={group.positions}
            valueCurrency={valueCurrency}
            hideClass
          />
        </div>
      )}
    </div>
  )
}
