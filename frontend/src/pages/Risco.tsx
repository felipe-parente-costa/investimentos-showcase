import { useEffect, useState } from 'react'
import { getRisk, type RiskGroupBy, type RiskPeriod, type RiskResponse } from '../api/client'
import RiskSummaryCards from '../components/RiskSummaryCards'
import DrawdownChart from '../components/DrawdownChart'
import RollingVolatilityChart from '../components/RollingVolatilityChart'
import ReturnHistogram from '../components/ReturnHistogram'
import StressScenarios from '../components/StressScenarios'
import RiskGroupsSection from '../components/RiskGroupsSection'
import FixedIncomeRiskCard from '../components/FixedIncomeRiskCard'
import CorrelationExplorer from '../components/CorrelationExplorer'
import { SkeletonChart } from '../components/Skeleton'

const PERIODS: RiskPeriod[] = ['3M', '6M', '1A', '2A', 'MAX']
const PERIOD_LABELS: Record<RiskPeriod, string> = {
  '3M': '3M',
  '6M': '6M',
  '1A': '1A',
  '2A': '2A',
  MAX: 'Desde o início',
}

export default function Risco() {
  const [period, setPeriod] = useState<RiskPeriod>('1A')
  const [groupBy, setGroupBy] = useState<RiskGroupBy>('sector')
  const [data, setData] = useState<RiskResponse | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    getRisk({ period, groupBy })
      .then((response) => {
        if (!cancelled) {
          setData(response)
          setError(false)
        }
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [period, groupBy])

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Risco</h2>
          <p className="mt-1 text-sm text-slate-400">
            Terminal de risco da carteira consolidada: volatilidade, perdas extremas,
            concentração e exposição por setor e sub-setor.
          </p>
        </div>
        <div className="flex gap-1">
          {PERIODS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setPeriod(option)}
              className={`rounded-md px-2 py-1 text-xs ${
                period === option
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {PERIOD_LABELS[option]}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          Não foi possível carregar as métricas de risco.
        </div>
      )}

      {!error && data === null && (
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <SkeletonChart />
          </div>
        </div>
      )}

      {!error && data !== null && (
        <>
          <RiskSummaryCards overall={data.overall} periodLabel={data.period_label} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <DrawdownChart points={data.drawdown_series} error={false} />
            <RollingVolatilityChart
              points21d={data.rolling_volatility_21d}
              points63d={data.rolling_volatility_63d}
              error={false}
            />
          </div>

          <ReturnHistogram
            returns={data.daily_returns}
            error={false}
            skewness={data.overall.skewness}
            kurtosisExcess={data.overall.kurtosis_excess}
          />

          <StressScenarios scenarios={data.stress_scenarios} />

          <RiskGroupsSection
            groups={data.groups}
            groupCorrelation={data.group_correlation}
            coveragePct={data.risk_universe_coverage_pct}
            groupBy={groupBy}
            onGroupByChange={setGroupBy}
            error={false}
          />

          <FixedIncomeRiskCard data={data.fixed_income ?? undefined} />

          <CorrelationExplorer groupCorrelation={data.group_correlation} groupBy={groupBy} />

          {data.warnings.length > 0 && (
            <details className="rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-xs text-amber-300">
              <summary className="cursor-pointer font-medium">
                {data.warnings.length} aviso(s) no cálculo de risco
              </summary>
              <ul className="mt-2 list-inside list-disc space-y-1">
                {data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </main>
  )
}
