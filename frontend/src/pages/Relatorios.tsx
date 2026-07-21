import { useCallback, useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  generateMonthlyReport,
  getMonthlyReport,
  getMonthlyReports,
  type SnapshotDetail,
  type SnapshotSummary,
} from '../api/client'
import AllocationDonut, { type DonutSlice } from '../components/AllocationDonut'
import {
  ASSET_CLASS_LABELS,
  formatMoney,
  formatQuantity,
  formatSignedPercent,
  prettifyInstitution,
} from '../lib/format'
import { classColor, CURRENCY_COLORS, SECTION_COLORS } from '../lib/colors'

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: 'numeric',
})

function monthLabel(yearMonth: string): string {
  return monthFormatter.format(new Date(`${yearMonth}-15T12:00:00`))
}

const compactBRL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 0,
})

function pctColor(value: string | null): string {
  if (value == null) return 'text-slate-400'
  const n = Number(value)
  return n > 0 ? 'text-green-400' : n < 0 ? 'text-red-400' : 'text-slate-300'
}

function pct(value: string | null): string {
  return value == null ? '—' : formatSignedPercent(Number(value) / 100)
}

// Y-axis fitted to the data: the wealth series moves a few thousand on a
// six-digit base, so a 0-anchored axis flattens every month into the same
// value. Bounds and ticks snap to round thousands (the compact "R$ x mil"
// tick label has no decimals, so a sub-1000 step would repeat labels),
// doubling the step until it fits in a few ticks.
function niceScale(values: number[]): { domain: [number, number]; ticks: number[] } {
  if (values.length === 0) return { domain: [0, 1], ticks: [] }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(max - min, max / 100, 1)
  let step = Math.max(1000, 10 ** Math.floor(Math.log10(span)) / 2)
  const lo = () => Math.max(0, Math.floor((min - step / 2) / step) * step)
  const hi = () => Math.ceil((max + step / 2) / step) * step
  while ((hi() - lo()) / step > 8) step *= 2
  const ticks: number[] = []
  for (let tick = lo(); tick <= hi(); tick += step) ticks.push(tick)
  return { domain: [lo(), hi()], ticks }
}

// One-sentence recap of the month, derived entirely from data already on
// screen (the evolution series + the selected snapshot's own fields) — no
// new fetch, no new number that isn't independently displayed elsewhere.
function narrative(detail: SnapshotDetail, items: SnapshotSummary[]): string {
  const label = monthLabel(detail.year_month)
  const capitalized = label.charAt(0).toUpperCase() + label.slice(1)
  const idx = items.findIndex((i) => i.year_month === detail.year_month)
  const previous = idx > 0 ? items[idx - 1] : null

  if (!previous) {
    return `${capitalized}: primeiro relatório registrado — patrimônio de ${formatMoney(detail.total_brl)}.`
  }

  const deltaBrl = Number(detail.total_brl) - Number(previous.total_brl)
  const direction = deltaBrl > 0 ? 'subiu' : deltaBrl < 0 ? 'caiu' : 'ficou estável'
  const deltaText =
    deltaBrl === 0 ? '' : ` ${formatMoney(String(Math.abs(deltaBrl)))} (${pct(detail.month_return_pct)})`
  const income = Number(detail.income_month_brl)
  const incomeClause =
    income > 0 ? `, incluindo ${formatMoney(detail.income_month_brl)} em dividendos` : ''

  return `${capitalized}: patrimônio ${direction}${deltaText} em relação a ${monthLabel(previous.year_month)}${incomeClause}.`
}

function dictToSlices(
  dict: Record<string, string>,
  label: (key: string) => string,
  color?: (key: string) => string | undefined,
): DonutSlice[] {
  return Object.entries(dict).map(([key, value]) => ({
    label: label(key),
    value: Number(value),
    color: color?.(key),
  }))
}

export default function Relatorios() {
  const [items, setItems] = useState<SnapshotSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<SnapshotDetail | null>(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadList = useCallback(() => {
    return getMonthlyReports()
      .then((data) => {
        setItems(data.items)
        setSelected((current) => current ?? data.items.at(-1)?.year_month ?? null)
        setError(null)
      })
      .catch(() => setError('Não foi possível carregar os relatórios.'))
  }, [])

  useEffect(() => {
    loadList()
  }, [loadList])

  useEffect(() => {
    if (!selected) return
    let cancelled = false
    getMonthlyReport(selected)
      .then((data) => !cancelled && setDetail(data))
      .catch(() => !cancelled && setError('Não foi possível carregar o relatório.'))
    return () => {
      cancelled = true
    }
  }, [selected])

  async function generate() {
    setGenerating(true)
    setError(null)
    try {
      const created = await generateMonthlyReport()
      await loadList()
      setSelected(created.year_month)
      setDetail(created)
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Erro ao gerar o relatório.')
    } finally {
      setGenerating(false)
    }
  }

  const evolution = items.map((s) => ({
    month: s.year_month,
    total: Number(s.total_brl),
  }))
  const evolutionScale = niceScale(evolution.map((e) => e.total))

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Relatórios mensais</h2>
          <p className="mt-1 text-sm text-slate-400">
            Snapshots congelados da carteira no fim de cada mês.
          </p>
        </div>
        <button
          type="button"
          onClick={generate}
          disabled={generating}
          className="rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-inkbrass hover:bg-sky-500 disabled:opacity-50"
        >
          {generating ? 'Gerando…' : 'Gerar relatório do mês atual'}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {items.length === 0 && !error && (
        <p className="text-sm text-slate-400">
          Nenhum relatório ainda. Gere o snapshot do mês atual para começar.
        </p>
      )}

      {items.length > 0 && (
        <>
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <p className="mb-4 text-sm text-slate-400">Evolução do patrimônio (mês a mês)</p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={evolution} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid stroke="var(--color-slate-800)" vertical={false} />
                  <XAxis
                    dataKey="month"
                    tickFormatter={monthLabel}
                    tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                    axisLine={{ stroke: 'var(--color-slate-700)' }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={evolutionScale.domain}
                    ticks={evolutionScale.ticks}
                    tickFormatter={(v: number) => compactBRL.format(v)}
                    tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                    width={72}
                  />
                  <Tooltip
                    formatter={(v) => [formatMoney(String(v)), 'Patrimônio']}
                    labelFormatter={(l) => monthLabel(String(l))}
                    cursor={{ stroke: 'var(--color-slate-700)' }}
                    contentStyle={{
                      backgroundColor: 'var(--color-slate-900)',
                      border: '1px solid var(--color-slate-700)',
                      borderRadius: '0.5rem',
                      color: 'var(--color-slate-200)',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="total"
                    stroke={SECTION_COLORS.total}
                    strokeWidth={2}
                    dot={{ r: 3, fill: SECTION_COLORS.total, strokeWidth: 0 }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="flex gap-2 overflow-x-auto pb-1">
            {items.map((s) => (
              <button
                key={s.year_month}
                type="button"
                onClick={() => setSelected(s.year_month)}
                className={`shrink-0 rounded-lg border px-3 py-1.5 text-sm ${
                  selected === s.year_month
                    ? 'border-sky-500 bg-sky-500/10 text-slate-100'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-600'
                }`}
              >
                {monthLabel(s.year_month)}
              </button>
            ))}
          </div>
        </>
      )}

      {detail && (
        <div className="space-y-6">
          <p className="text-sm text-slate-300">{narrative(detail, items)}</p>

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <SummaryStat label="Patrimônio (fim do mês)" value={formatMoney(detail.total_brl)} />
            <SummaryStat
              label="Rentabilidade do mês"
              value={pct(detail.month_return_pct)}
              color={pctColor(detail.month_return_pct)}
            />
            <SummaryStat
              label="Rentabilidade acumulada"
              value={pct(detail.cumulative_return_pct)}
              color={pctColor(detail.cumulative_return_pct)}
            />
            <SummaryStat
              label="Dividendos do mês"
              value={formatMoney(detail.income_month_brl)}
              color="text-green-400"
            />
          </div>

          {detail.last_recomputed_at && (
            <p className="text-xs text-gray-500">
              Recalculado em{' '}
              {new Date(
                detail.last_recomputed_at.endsWith('Z')
                  ? detail.last_recomputed_at
                  : detail.last_recomputed_at + 'Z',
              ).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })}
              {detail.recompute_reason ? ` — ${detail.recompute_reason}` : ''}
            </p>
          )}

          <div className="grid gap-6 lg:grid-cols-3">
            <AllocationDonut
              title="Por classe"
              slices={dictToSlices(
                detail.allocation_class,
                (k) => ASSET_CLASS_LABELS[k as keyof typeof ASSET_CLASS_LABELS] ?? k,
                (k) => classColor(k),
              )}
            />
            <AllocationDonut
              title="Por moeda"
              slices={dictToSlices(
                detail.allocation_currency,
                (k) => k,
                (k) => CURRENCY_COLORS[k],
              )}
            />
            <AllocationDonut
              title="Por corretora"
              slices={dictToSlices(detail.allocation_broker, (k) =>
                k === 'Sem corretora' ? k : prettifyInstitution(k),
              )}
            />
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3">Ativo</th>
                  <th className="px-4 py-3">Classe</th>
                  <th className="px-4 py-3">Corretora</th>
                  <th className="px-4 py-3 text-right">Quantidade</th>
                  <th className="px-4 py-3 text-right">Preço médio</th>
                  <th className="px-4 py-3 text-right">Valor (R$)</th>
                  <th className="px-4 py-3 text-right">P&L (R$)</th>
                </tr>
              </thead>
              <tbody>
                {detail.positions.map((p) => {
                  const pnl = p.unrealized_pnl_brl != null ? Number(p.unrealized_pnl_brl) : null
                  return (
                    <tr
                      key={`${p.ticker}-${p.custody ?? ''}`}
                      className="border-b border-slate-800/60 last:border-b-0"
                    >
                      <td className="px-4 py-2 font-medium">{p.ticker}</td>
                      <td className="px-4 py-2 text-slate-300">
                        {ASSET_CLASS_LABELS[p.asset_class] ?? p.asset_class}
                      </td>
                      <td className="px-4 py-2 text-slate-300">
                        {prettifyInstitution(p.institution)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatQuantity(p.quantity)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatMoney(p.average_price, p.currency)}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatMoney(p.market_value_brl)}
                      </td>
                      <td
                        className={`px-4 py-2 text-right tabular-nums ${
                          pnl == null
                            ? 'text-slate-400'
                            : pnl >= 0
                              ? 'text-green-400'
                              : 'text-red-400'
                        }`}
                      >
                        {pnl == null ? '—' : formatMoney(p.unrealized_pnl_brl)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </main>
  )
}

function SummaryStat({
  label,
  value,
  color = 'text-slate-100',
}: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-xs text-slate-400">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
    </div>
  )
}
