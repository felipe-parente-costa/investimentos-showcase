import { useEffect, useMemo, useState } from 'react'
import {
  getCorrelation,
  getPortfolio,
  type CorrelationResponse,
  type GroupCorrelation,
  type RiskGroup,
  type RiskGroupBy,
} from '../api/client'
import { formatPercent } from '../lib/format'
import AllocationDonut from './AllocationDonut'
import CorrelationHeatmap from './CorrelationHeatmap'
import CorrelationLegend from './CorrelationLegend'
import { formatCoef, type HoveredCell } from '../lib/correlation'
import { SkeletonChart } from './Skeleton'

const GROUP_BY_OPTIONS: { value: RiskGroupBy; label: string }[] = [
  { value: 'sector', label: 'Setor' },
  { value: 'subsector', label: 'Sub-setor' },
]

const TOP_N = 10
// Compact cells so the two heatmaps sit side by side inside the card
// instead of each claiming the full width (the default 28px/72px sizing
// CorrelationHeatmap uses everywhere else).
const COMPACT_CELL = 20
const COMPACT_LABEL = 56

interface HeatmapPanelProps {
  title: string
  subtitle: string
  tickers: string[]
  valueAt: (a: string, b: string) => number | null
  emptyMessage: string
}

function HeatmapPanel({ title, subtitle, tickers, valueAt, emptyMessage }: HeatmapPanelProps) {
  const [hovered, setHovered] = useState<HoveredCell | null>(null)
  return (
    <div className="space-y-2">
      <div>
        <p className="text-sm font-semibold text-slate-300">{title}</p>
        <p className="text-xs text-slate-500">{subtitle}</p>
      </div>
      <CorrelationLegend hovered={hovered} />
      {tickers.length >= 2 ? (
        <CorrelationHeatmap
          tickers={tickers}
          valueAt={valueAt}
          showValues={false}
          onHover={setHovered}
          cellSize={COMPACT_CELL}
          labelWidth={COMPACT_LABEL}
        />
      ) : (
        <p className="text-sm text-slate-500">{emptyMessage}</p>
      )}
    </div>
  )
}

interface Props {
  groups: RiskGroup[] | null
  groupCorrelation: GroupCorrelation | null
  coveragePct: number | null
  groupBy: RiskGroupBy
  onGroupByChange: (value: RiskGroupBy) => void
  error: boolean
}

export default function RiskGroupsSection({
  groups,
  groupCorrelation,
  coveragePct,
  groupBy,
  onGroupByChange,
  error,
}: Props) {
  const donutSlices = useMemo(
    () =>
      (groups ?? []).map((g) => ({ label: g.label, value: Number(g.market_value_brl) })),
    [groups],
  )

  const groupLabels = useMemo(() => groupCorrelation?.labels ?? [], [groupCorrelation])
  const groupValueAt = useMemo(() => {
    const index = new Map(groupLabels.map((label, i) => [label, i]))
    return (a: string, b: string): number | null => {
      const i = index.get(a)
      const j = index.get(b)
      if (i == null || j == null || !groupCorrelation) return null
      return groupCorrelation.matrix[i][j]
    }
  }, [groupLabels, groupCorrelation])

  // Top-10-by-value asset correlation — fetched independently (same
  // /portfolio/correlation the old Correlação page used), so it sits right
  // next to the sector/sub-setor heatmap without waiting on /portfolio/risk.
  const [assetCorrelation, setAssetCorrelation] = useState<CorrelationResponse | null>(null)
  const [weights, setWeights] = useState<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false
    getCorrelation({ period: '1A', segment: '' })
      .then((data) => {
        if (!cancelled) setAssetCorrelation(data)
      })
      .catch(() => {
        if (!cancelled) setAssetCorrelation(null)
      })
    getPortfolio()
      .then((portfolio) => {
        if (cancelled) return
        const byTicker: Record<string, number> = {}
        for (const position of portfolio.positions) {
          if (position.market_value_brl == null) continue
          byTicker[position.ticker] =
            (byTicker[position.ticker] ?? 0) + Number(position.market_value_brl)
        }
        setWeights(byTicker)
      })
      .catch(() => {
        if (!cancelled) setWeights({})
      })
    return () => {
      cancelled = true
    }
  }, [])

  const topTickers = useMemo(() => {
    const tickers = assetCorrelation?.tickers ?? []
    return [...tickers]
      .sort((a, b) => (weights[b] ?? 0) - (weights[a] ?? 0))
      .slice(0, TOP_N)
  }, [assetCorrelation, weights])

  const assetValueAt = useMemo(() => {
    const tickers = assetCorrelation?.tickers ?? []
    const index = new Map(tickers.map((ticker, i) => [ticker, i]))
    return (a: string, b: string): number | null => {
      const i = index.get(a)
      const j = index.get(b)
      if (i == null || j == null || !assetCorrelation) return null
      return assetCorrelation.matrix[i][j]
    }
  }, [assetCorrelation])

  return (
    <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-section">Risco por {groupBy === 'sector' ? 'setor' : 'sub-setor'}</p>
          <p className="text-xs text-slate-500">
            Alocação, volatilidade da cesta ponderada e contribuição ao risco total da carteira.
          </p>
        </div>
        <div className="flex gap-1">
          {GROUP_BY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onGroupByChange(option.value)}
              className={`rounded-md px-2 py-1 text-xs ${
                groupBy === option.value
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-slate-500">Não foi possível carregar os grupos de risco.</p>}
      {!error && groups === null && <SkeletonChart />}

      {!error && groups !== null && (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <AllocationDonut title="Alocação" slices={donutSlices} maxSlices={8} />

            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                    <th className="py-2 pr-3 font-normal">
                      {groupBy === 'sector' ? 'Setor' : 'Sub-setor'}
                    </th>
                    <th className="py-2 pr-3 text-right font-normal">Peso</th>
                    <th className="py-2 pr-3 text-right font-normal">Vol. anual.</th>
                    <th className="py-2 pr-3 text-right font-normal">Contrib. risco</th>
                    <th className="py-2 pr-3 text-right font-normal">Corr. intra</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.key} className="border-b border-slate-800/60 last:border-0">
                      <td className="py-2 pr-3 text-slate-200">
                        {g.label}
                        <span className="ml-1.5 text-xs text-slate-500">
                          ({g.position_count})
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                        {formatPercent(g.weight_pct)}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                        {g.volatility_annual_pct != null ? formatPercent(g.volatility_annual_pct) : '—'}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                        {g.risk_contribution_pct != null ? formatPercent(g.risk_contribution_pct) : '—'}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                        {formatCoef(g.avg_intra_correlation)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {coveragePct != null && (
                <p className="mt-2 text-[11px] text-slate-500">
                  Volatilidade e contribuição de risco cobrem {formatPercent(coveragePct)} do
                  patrimônio (parcela com série de preços; renda fixa privada e ativos sem
                  cotação entram só na alocação).
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 pt-2 lg:grid-cols-2">
            <HeatmapPanel
              title={`Correlação entre ${groupBy === 'sector' ? 'setores' : 'sub-setores'}`}
              subtitle="Cestas ponderadas por valor, mesmo período acima."
              tickers={groupLabels}
              valueAt={groupValueAt}
              emptyMessage="Grupos insuficientes para correlacionar."
            />
            <HeatmapPanel
              title="10 maiores posições"
              subtitle="Por valor de mercado, retornos diários (1A)."
              tickers={topTickers}
              valueAt={assetValueAt}
              emptyMessage="Posições insuficientes para correlacionar."
            />
          </div>
        </>
      )}
    </div>
  )
}
