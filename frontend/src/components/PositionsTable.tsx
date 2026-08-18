import { STATIC_DEMO } from '../api/staticDemo'
import { useMemo, useState } from 'react'
import type { Position } from '../api/client'
import {
  ASSET_CLASS_LABELS,
  CUSTODY_LABELS,
  CUSTODY_SHORT_LABELS,
  INDEXER_LABELS,
  formatMoney,
  formatPercent,
  formatQuantity,
  formatSignedPercent,
  prettifyInstitution,
} from '../lib/format'
import { classColor } from '../lib/colors'

// First two letters of the ticker, uppercased (non-letters stripped so a BR
// suffix digit like PETR4 doesn't shift the pick — "PE", not "P4").
function initials(ticker: string): string {
  const letters = ticker.replace(/[^A-Za-zÀ-ÿ]/g, '')
  return (letters.slice(0, 2) || ticker.slice(0, 2)).toUpperCase()
}

type SortKey =
  | 'ticker'
  | 'asset_class'
  | 'indexer'
  | 'institution'
  | 'quantity'
  | 'average_price'
  | 'quote_price'
  | 'market_value_brl'
  | 'weight'
  | 'dy_12m'
  | 'unrealized_pnl'

type SortDirection = 'asc' | 'desc'

interface Column {
  key: SortKey
  label: string
  numeric: boolean
}

const COLUMNS: Column[] = [
  { key: 'ticker', label: 'Ativo', numeric: false },
  { key: 'asset_class', label: 'Classe', numeric: false },
  { key: 'indexer', label: 'Indexador', numeric: false },
  { key: 'institution', label: 'Corretora', numeric: false },
  { key: 'quantity', label: 'Quantidade', numeric: true },
  { key: 'average_price', label: 'Preço médio', numeric: true },
  { key: 'quote_price', label: 'Cotação', numeric: true },
  { key: 'market_value_brl', label: 'Valor (R$)', numeric: true },
  { key: 'weight', label: 'Peso', numeric: true },
  { key: 'dy_12m', label: 'DY 12m', numeric: true },
  { key: 'unrealized_pnl', label: 'P&L aberto', numeric: true },
]

function textValue(p: Position, key: SortKey): string {
  switch (key) {
    case 'ticker':
      return `${p.ticker} ${p.asset_name ?? ''}`
    case 'asset_class':
      return ASSET_CLASS_LABELS[p.asset_class]
    case 'indexer':
      return p.indexer ? INDEXER_LABELS[p.indexer] : ''
    case 'institution':
      return prettifyInstitution(p.institution)
    default:
      return ''
  }
}

function numberValue(p: Position, key: SortKey, total: number): number | null {
  switch (key) {
    case 'quantity':
      return Number(p.quantity)
    case 'average_price':
      return Number(p.average_price)
    case 'quote_price':
      return p.quote_price != null ? Number(p.quote_price) : null
    case 'market_value_brl':
      return p.market_value_brl != null ? Number(p.market_value_brl) : null
    case 'weight':
      // Compared in percent so the user can type ">5" meaning >5%.
      return p.market_value_brl != null && total > 0
        ? (Number(p.market_value_brl) / total) * 100
        : null
    case 'dy_12m':
      // Compared in percent so the user can type ">5" meaning >5%.
      return p.dy_12m_pct != null ? Number(p.dy_12m_pct) * 100 : null
    case 'unrealized_pnl':
      return p.unrealized_pnl != null ? Number(p.unrealized_pnl) : null
    default:
      return null
  }
}

function sortValue(p: Position, key: SortKey, total: number): string | number {
  const column = COLUMNS.find((c) => c.key === key)!
  if (!column.numeric) return textValue(p, key)
  const value = numberValue(p, key, total)
  return value == null ? Number.NEGATIVE_INFINITY : value
}

// A display-only aggregate of the same ticker held across custodies. The
// quantity/cost/value are summed and the average price recomputed, so the
// consolidated row answers "how much BTC do I have" while the per-custody
// rows below it show the hot/cold split. Never counted in totals.
function consolidate(leaves: Position[]): Position {
  const sum = (pick: (p: Position) => string | null) =>
    leaves.reduce((acc, p) => {
      const v = pick(p)
      return v == null ? acc : acc + Number(v)
    }, 0)
  const quantity = sum((p) => p.quantity)
  const totalCost = sum((p) => p.total_cost)
  const anyMv = leaves.some((p) => p.market_value_brl != null)
  const anyPnl = leaves.some((p) => p.unrealized_pnl != null)
  // DY of the aggregate = value-weighted mean of the custody DYs (same
  // result as income over summed market value, without re-deriving income).
  const dyLeaves = leaves.filter(
    (p) => p.dy_12m_pct != null && p.market_value_brl != null,
  )
  const dyValue = dyLeaves.reduce((acc, p) => acc + Number(p.market_value_brl), 0)
  const dy =
    dyLeaves.length > 0 && dyValue > 0
      ? dyLeaves.reduce(
          (acc, p) => acc + Number(p.dy_12m_pct) * Number(p.market_value_brl),
          0,
        ) / dyValue
      : null
  const head = leaves[0]
  return {
    ...head,
    custody: null,
    institution: null,
    quantity: String(quantity),
    total_cost: String(totalCost),
    average_price: quantity !== 0 ? String(totalCost / quantity) : '0',
    market_value_brl: anyMv ? String(sum((p) => p.market_value_brl)) : null,
    unrealized_pnl: anyPnl ? String(sum((p) => p.unrealized_pnl)) : null,
    income_12m: String(sum((p) => p.income_12m)),
    dy_12m_pct: dy != null ? String(dy) : null,
  }
}

type DisplayKind = 'single' | 'parent' | 'child'
interface DisplayRow {
  pos: Position
  kind: DisplayKind
}

function parseNumber(raw: string): number {
  const trimmed = raw.trim()
  // pt-BR "1.234,56" -> 1234.56; plain "10.5" or "10,5" -> 10.5.
  const normalized =
    trimmed.includes('.') && trimmed.includes(',')
      ? trimmed.replace(/\./g, '').replace(',', '.')
      : trimmed.replace(',', '.')
  return Number(normalized)
}

function matchesColumn(
  p: Position,
  key: SortKey,
  numeric: boolean,
  raw: string,
  total: number,
): boolean {
  const needle = raw.trim().toLowerCase()
  if (!needle) return true
  if (!numeric) {
    return textValue(p, key).toLowerCase().includes(needle)
  }
  const value = numberValue(p, key, total)
  // Comparison operators for numeric columns: ">100", "<=0", "= 12".
  const op = needle.match(/^(>=|<=|>|<|=)\s*(-?[\d.,]+)$/)
  if (op) {
    if (value == null) return false
    const target = parseNumber(op[2])
    if (Number.isNaN(target)) return true
    switch (op[1]) {
      case '>':
        return value > target
      case '<':
        return value < target
      case '>=':
        return value >= target
      case '<=':
        return value <= target
      default:
        return value === target
    }
  }
  // Plain text: substring on the raw numeric value.
  return value != null && String(value).toLowerCase().includes(needle)
}

interface Props {
  positions: Position[]
  // Show the fixed-income indexer column (used in the Renda Fixa view).
  showIndexer?: boolean
  // Currency of the "Valor" column (BRL by default; USD for EUA/Cripto).
  valueCurrency?: string
  // Hide the "Classe" column when rendered inside a class/indexer group card
  // (redundant with the group header).
  hideClass?: boolean
  // Hide the DY column where it never applies (the Renda Fixa view).
  showDy?: boolean
  // Pin the header (labels + filters) to the top of the viewport while
  // scrolling — only makes sense for the standalone flat list; the nested
  // table inside a collapsible group stays static (it would stick to the
  // viewport top detached from its own short, already-visible card).
  stickyHeader?: boolean
}

export default function PositionsTable({
  positions,
  showIndexer = false,
  valueCurrency = 'BRL',
  hideClass = false,
  showDy = true,
  stickyHeader = false,
}: Props) {
  const valueLabel = valueCurrency === 'USD' ? 'Valor (US$)' : 'Valor (R$)'
  const [sortKey, setSortKey] = useState<SortKey>('market_value_brl')
  const [direction, setDirection] = useState<SortDirection>('desc')
  const [filters, setFilters] = useState<Partial<Record<SortKey, string>>>({})

  const columns = useMemo(
    () =>
      COLUMNS.filter(
        (c) =>
          (showIndexer || c.key !== 'indexer') &&
          (!hideClass || c.key !== 'asset_class') &&
          (showDy || c.key !== 'dy_12m'),
      ).map((c) =>
        c.key === 'market_value_brl' ? { ...c, label: valueLabel } : c,
      ),
    [showIndexer, valueLabel, hideClass, showDy],
  )

  const visibleTotal = useMemo(
    () =>
      positions.reduce(
        (sum, p) => sum + (p.market_value_brl != null ? Number(p.market_value_brl) : 0),
        0,
      ),
    [positions],
  )

  const hasFilters = Object.values(filters).some((v) => v && v.trim())

  const { rows, filteredCount } = useMemo(() => {
    const sign = direction === 'asc' ? 1 : -1
    const active = columns.filter((c) => (filters[c.key] ?? '').trim())
    const filtered = positions.filter((p) =>
      active.every((c) =>
        matchesColumn(p, c.key, c.numeric, filters[c.key] ?? '', visibleTotal),
      ),
    )

    // Group by ticker so multi-custody holdings get a consolidated row.
    const byTicker = new Map<string, Position[]>()
    for (const p of filtered) {
      const arr = byTicker.get(p.ticker) ?? []
      arr.push(p)
      byTicker.set(p.ticker, arr)
    }

    const compare = (a: Position, b: Position) => {
      const left = sortValue(a, sortKey, visibleTotal)
      const right = sortValue(b, sortKey, visibleTotal)
      if (typeof left === 'string' && typeof right === 'string') {
        return sign * left.localeCompare(right, 'pt-BR')
      }
      return sign * (Number(left) - Number(right))
    }

    const groups = [...byTicker.values()].map((leaves) => ({
      leaves,
      agg: leaves.length > 1 ? consolidate(leaves) : leaves[0],
    }))
    groups.sort((a, b) => compare(a.agg, b.agg))

    const display: DisplayRow[] = []
    for (const { leaves, agg } of groups) {
      if (leaves.length > 1) {
        display.push({ pos: agg, kind: 'parent' })
        for (const leaf of [...leaves].sort((a, b) =>
          (a.custody ?? '').localeCompare(b.custody ?? ''),
        )) {
          display.push({ pos: leaf, kind: 'child' })
        }
      } else {
        display.push({ pos: leaves[0], kind: 'single' })
      }
    }
    return { rows: display, filteredCount: filtered.length }
  }, [positions, sortKey, direction, filters, visibleTotal, columns])

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDirection(direction === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setDirection(COLUMNS.find((c) => c.key === key)?.numeric ? 'desc' : 'asc')
    }
  }

  function setFilter(key: SortKey, value: string) {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900">
      <div className="flex items-center justify-between gap-4 px-4 pt-4">
        <p className="text-sm text-slate-400">
          Posições{' '}
          <span className="text-xs text-slate-500">
            ({filteredCount}
            {filteredCount !== positions.length && ` de ${positions.length}`})
          </span>
        </p>
        {hasFilters && (
          <button
            type="button"
            onClick={() => setFilters({})}
            className="text-xs text-sky-400 hover:underline"
          >
            Limpar filtros
          </button>
        )}
      </div>
      <div className={`overflow-x-auto ${stickyHeader ? 'max-h-[70vh] overflow-y-auto' : ''}`}>
        <table className="w-full text-sm">
          <thead>
            <tr
              className={`border-b border-slate-800/60 text-left text-xs uppercase tracking-wide text-slate-400 ${
                stickyHeader ? 'sticky top-0 z-10 bg-slate-900' : ''
              }`}
            >
              {columns.map((column) => (
                <th key={column.key} className={column.numeric ? 'text-right' : ''}>
                  <button
                    type="button"
                    onClick={() => toggleSort(column.key)}
                    className={`w-full px-4 pt-3 font-medium hover:text-slate-200 ${
                      column.numeric ? 'text-right' : 'text-left'
                    }`}
                  >
                    {column.label}
                    {sortKey === column.key && (direction === 'asc' ? ' ▲' : ' ▼')}
                  </button>
                </th>
              ))}
            </tr>
            <tr className="border-b border-slate-800">
              {columns.map((column) => (
                <th key={column.key} className="px-2 pb-2 pt-1">
                  <input
                    type="search"
                    value={filters[column.key] ?? ''}
                    onChange={(event) => setFilter(column.key, event.target.value)}
                    placeholder={column.numeric ? '>100, <0…' : 'filtrar…'}
                    className={`w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs font-normal normal-case text-slate-200 placeholder:text-slate-600 focus:border-sky-600 focus:outline-none ${
                      column.numeric ? 'text-right' : ''
                    }`}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ pos: position, kind }) => {
              const pnl =
                position.unrealized_pnl != null ? Number(position.unrealized_pnl) : null
              const cost = Number(position.total_cost)
              const pnlColor =
                pnl == null || pnl === 0
                  ? 'text-slate-400'
                  : pnl > 0
                    ? 'text-green-400'
                    : 'text-red-400'
              return (
                <tr
                  key={`${position.ticker}-${kind === 'parent' ? 'total' : position.custody ?? ''}`}
                  className={`border-b border-slate-800/60 last:border-b-0 hover:bg-slate-800/40 ${
                    kind === 'parent' ? 'bg-slate-800/30 font-medium' : ''
                  } ${kind === 'child' ? 'text-slate-400' : ''}`}
                >
                  <td className={`px-4 py-3 ${kind === 'child' ? 'pl-8' : ''}`}>
                    <div className="flex items-center gap-2.5">
                      <span
                        aria-hidden="true"
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
                        style={{
                          backgroundColor: `${classColor(position.asset_class, position.market)}26`,
                          color: classColor(position.asset_class, position.market),
                        }}
                      >
                        {initials(position.ticker)}
                      </span>
                      <div className="min-w-0">
                        <span className="font-medium">{position.ticker}</span>
                        {kind === 'parent' && (
                          <span
                            title="Soma de todas as custódias"
                            className="ml-2 rounded bg-slate-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300"
                          >
                            Total
                          </span>
                        )}
                        {position.custody && (
                          <span
                            title={CUSTODY_LABELS[position.custody]}
                            className={`ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                              position.custody === 'cold_wallet'
                                ? 'bg-sky-500/15 text-sky-300'
                                : 'bg-amber-500/15 text-amber-300'
                            }`}
                          >
                            {CUSTODY_SHORT_LABELS[position.custody]}
                          </span>
                        )}
                        {kind !== 'child' && position.asset_name && (
                          <span className="mt-0.5 block max-w-56 truncate text-xs text-slate-500">
                            {position.asset_name}
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  {!hideClass && (
                    <td className="px-4 py-3 text-slate-300">
                      {ASSET_CLASS_LABELS[position.asset_class]}
                    </td>
                  )}
                  {showIndexer && (
                    <td className="px-4 py-3 text-slate-300">
                      {position.indexer ? INDEXER_LABELS[position.indexer] : '—'}
                    </td>
                  )}
                  <td className="px-4 py-3 text-slate-300">
                    {prettifyInstitution(position.institution)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatQuantity(position.quantity)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {formatMoney(position.average_price, position.currency)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {position.priced ? (
                      <>
                        {formatMoney(position.quote_price, position.quote_currency ?? 'BRL')}
                        {position.quote_stale && !STATIC_DEMO && (
                          <span title="Cotação desatualizada" className="ml-1 text-amber-400">
                            •
                          </span>
                        )}
                      </>
                    ) : (
                      <span
                        className="text-slate-500"
                        title="Sem fonte de cotação; valorado a custo"
                      >
                        a custo
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-medium tabular-nums">
                    {formatMoney(position.market_value_brl, valueCurrency)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                    {position.market_value_brl != null && visibleTotal > 0
                      ? formatPercent(Number(position.market_value_brl) / visibleTotal)
                      : '—'}
                  </td>
                  {showDy && (
                    <td
                      className="px-4 py-3 text-right tabular-nums text-slate-300"
                      title="Renda dos últimos 12 meses ÷ valor de mercado atual"
                    >
                      {position.dy_12m_pct != null
                        ? formatPercent(Number(position.dy_12m_pct))
                        : '—'}
                    </td>
                  )}
                  <td className={`px-4 py-3 text-right tabular-nums ${pnlColor}`}>
                    {pnl == null ? (
                      '—'
                    ) : (
                      <>
                        {formatMoney(position.unrealized_pnl, position.currency)}
                        <span className="ml-1 text-xs">
                          {cost > 0 && `(${formatSignedPercent(pnl / cost)})`}
                        </span>
                      </>
                    )}
                  </td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-6 text-center text-slate-500">
                  Nenhuma posição corresponde aos filtros.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
