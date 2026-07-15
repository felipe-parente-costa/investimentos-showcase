import { useCallback, useEffect, useState } from 'react'
import {
  getPortfolio,
  getPortfolioHistory,
  type PortfolioResponse,
} from '../api/client'
import type { Position } from '../api/client'
import AllocationDonut, { type DonutSlice } from '../components/AllocationDonut'
import ContributionsChart from '../components/ContributionsChart'
import PatrimonyChart from '../components/PatrimonyChart'
import WealthCompositionBar from '../components/WealthCompositionBar'
import ReturnsChart from '../components/ReturnsChart'
import PositionsSection from '../components/PositionsSection'
import { dashboardGroup, DASHBOARD_GROUPS } from '../lib/grouping'
import SegmentTabs, { type SegmentFilter } from '../components/SegmentTabs'
import SummaryCards, { type MonthChange } from '../components/SummaryCards'
import { ASSET_CLASS_LABELS } from '../lib/format'
import { classColor, CURRENCY_COLORS } from '../lib/colors'

const REFRESH_MS = 5 * 60 * 1000

// Separa Ações (BR) de Stocks (US) — ambas têm asset_class 'stock'; usa o campo
// `market` da posição. Só apresentação (nenhum dado tocado). A cor fixa por
// categoria vem de classColor (mesma cor no donut e no swatch da lista).
function classLabel(p: Position): string {
  if (p.asset_class === 'stock') return p.market === 'us' ? 'Stocks' : 'Ações'
  return ASSET_CLASS_LABELS[p.asset_class]
}

function sliceBy(
  positions: Position[],
  label: (p: Position) => string,
  color?: (p: Position) => string | undefined,
): DonutSlice[] {
  const groups = new Map<string, DonutSlice>()
  for (const position of positions) {
    if (position.market_value_brl == null) continue
    const key = label(position)
    const slice = groups.get(key) ?? { label: key, value: 0, color: color?.(position) }
    slice.value += Number(position.market_value_brl)
    groups.set(key, slice)
  }
  return [...groups.values()]
}

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null)
  const [twrIndex, setTwrIndex] = useState<string | null>(null)
  const [monthChange, setMonthChange] = useState<MonthChange | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [segment, setSegment] = useState<SegmentFilter>('all')

  const load = useCallback(() => {
    getPortfolioHistory('monthly')
      .then((data) => {
        const points = data.points
        const last = points[points.length - 1]
        setTwrIndex(last ? last.twr_index : null)
        // Variação no mês: total de hoje (último ponto mensal) vs fim do mês
        // anterior (ponto anterior). Derivado do histórico já carregado — só
        // apresentação, nenhum cálculo novo no backend.
        if (points.length >= 2) {
          const prev = Number(points[points.length - 2].total_brl)
          const current = Number(last.total_brl)
          setMonthChange({
            brl: current - prev,
            pct: prev > 0 ? (current - prev) / prev : null,
          })
        } else {
          setMonthChange(null)
        }
      })
      .catch(() => {
        setTwrIndex(null)
        setMonthChange(null)
      })
    return getPortfolio()
      .then((data) => {
        setPortfolio(data)
        setError(null)
      })
      .catch(() => setError('Não foi possível carregar o portfólio. A API está rodando?'))
      .finally(() => setLoading(false))
  }, [])

  function refresh() {
    setLoading(true)
    void load()
  }

  useEffect(() => {
    void load()
    const interval = setInterval(load, REFRESH_MS)
    return () => clearInterval(interval)
  }, [load])

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
        {error && (
          <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
            {error}
          </div>
        )}
        {!error && !portfolio && (
          <p className="text-slate-400">Carregando portfólio…</p>
        )}
        {portfolio && portfolio.positions.length === 0 && (
          <p className="text-slate-400">
            Nenhuma posição aberta. Importe suas transações para ver o patrimônio
            consolidado.
          </p>
        )}
        {portfolio && portfolio.positions.length > 0 && (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SegmentTabs
                segments={portfolio.segments}
                totalBrl={portfolio.total_market_value_brl}
                selected={segment}
                onSelect={setSegment}
              />
              <button
                type="button"
                onClick={refresh}
                disabled={loading}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
              >
                {loading ? 'Atualizando…' : 'Atualizar'}
              </button>
            </div>
            <SummaryCards
              portfolio={portfolio}
              twrIndex={twrIndex}
              monthChange={monthChange}
            />
            <PatrimonyChart />
            <WealthCompositionBar
              aportado={portfolio.segment_summaries.reduce(
                (sum, s) => sum + Number(s.cost_brl),
                0,
              )}
              total={Number(portfolio.total_market_value_brl)}
            />
            {(() => {
              const filtered = portfolio.positions.filter(
                (p) => segment === 'all' || p.market === segment,
              )
              return (
                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                  <AllocationDonut
                    title="Alocação por classe"
                    slices={sliceBy(
                      filtered,
                      classLabel,
                      (p) => classColor(p.asset_class, p.market),
                    )}
                  />
                  <AllocationDonut
                    title="Alocação por moeda"
                    slices={sliceBy(
                      filtered,
                      (p) => p.currency,
                      (p) => CURRENCY_COLORS[p.currency],
                    )}
                  />
                  <AllocationDonut
                    title="Distribuição por país"
                    slices={sliceBy(filtered, (p) => p.country ?? 'Sem país')}
                  />
                </div>
              )
            })()}
            <ReturnsChart />
            <ContributionsChart />
            <PositionsSection
              positions={portfolio.positions.filter(
                (p) => segment === 'all' || p.market === segment,
              )}
              groupOf={dashboardGroup}
              groupMeta={DASHBOARD_GROUPS}
            />
            {portfolio.warnings.length > 0 && (
              <div className="rounded-xl border border-amber-900/60 bg-amber-950/30 p-4 text-xs text-amber-300">
                <p className="mb-2 font-medium">
                  Avisos do cálculo de posições ({portfolio.warnings.length})
                </p>
                <ul className="list-inside list-disc space-y-1">
                  {portfolio.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
    </main>
  )
}
