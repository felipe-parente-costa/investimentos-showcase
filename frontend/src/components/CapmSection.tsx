import { useEffect, useState } from 'react'
import {
  getCapm,
  type CapmPeriod,
  type CapmResponse,
  type CapmSegment,
} from '../api/client'
import { formatSignedPercent } from '../lib/format'

const PERIODS: CapmPeriod[] = ['6M', '1A', '2A', 'MAX']
const PERIOD_LABELS: Record<CapmPeriod, string> = {
  '6M': '6M',
  '1A': '1A',
  '2A': '2A',
  MAX: 'Máx',
}

const coefFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function alphaColor(value: number | null): string {
  if (value == null || value === 0) return 'text-slate-200'
  return value > 0 ? 'text-green-400' : 'text-red-400'
}

function Metric({
  label,
  children,
  hint,
}: {
  label: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{children}</p>
      {hint && <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p>}
    </div>
  )
}

function CapmCard({ metric }: { metric: CapmSegment }) {
  const hasCoefficients = metric.beta != null || metric.alpha_annual_pct != null
  // Every figure must be shown with its assumptions — a beta without
  // benchmark/risk-free/window/frequency is a misleading number.
  const assumptions = `Benchmark: ${metric.benchmark_label} · Risk-free: ${metric.risk_free_label} · Janela: ${metric.period_label} · Frequência: ${metric.frequency}`

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-sm font-semibold text-slate-200">{metric.label}</p>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Metric label="Beta (β)">
          {metric.beta != null ? coefFormatter.format(metric.beta) : '—'}
        </Metric>
        <Metric label="Alfa de Jensen" hint="anualizado">
          <span className={alphaColor(metric.alpha_annual_pct)}>
            {metric.alpha_annual_pct != null
              ? formatSignedPercent(metric.alpha_annual_pct / 100)
              : '—'}
          </span>
        </Metric>
        <Metric label="Correlação (ρ)">
          {metric.correlation != null ? coefFormatter.format(metric.correlation) : '—'}
        </Metric>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{assumptions}</p>
      {hasCoefficients && (
        <p className="mt-0.5 text-[11px] text-slate-500">
          {metric.observations} retornos pareados
        </p>
      )}

      {metric.note && (
        <p className="mt-2 rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-[11px] text-amber-300">
          {metric.note}
        </p>
      )}
      {metric.warnings.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-0.5 text-[11px] text-amber-300/80">
          {metric.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface Props {
  // Ordered CAPM segment keys to display (e.g. br_total, br_stock, br_fii).
  segmentKeys: string[]
}

export default function CapmSection({ segmentKeys }: Props) {
  const [period, setPeriod] = useState<CapmPeriod>('1A')
  const [data, setData] = useState<CapmResponse | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    getCapm(period)
      .then((result) => {
        if (!cancelled) {
          setData(result)
          setError(false)
        }
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [period])

  const cards = (data?.segments ?? [])
    .filter((s) => segmentKeys.includes(s.key))
    .sort((a, b) => segmentKeys.indexOf(a.key) - segmentKeys.indexOf(b.key))

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">
            Correlação, alfa e beta (CAPM)
          </h3>
          <p className="text-xs text-slate-500">
            Retornos diários, regressão dos excedentes sobre o risk-free.
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
        <p className="text-sm text-slate-500">Não foi possível carregar as métricas CAPM.</p>
      )}
      {!error && data === null && (
        <p className="text-sm text-slate-500">Carregando métricas…</p>
      )}
      {!error && data !== null && (
        <div className="grid grid-cols-1 gap-4">
          {cards.map((metric) => (
            <CapmCard key={metric.key} metric={metric} />
          ))}
        </div>
      )}
    </section>
  )
}
