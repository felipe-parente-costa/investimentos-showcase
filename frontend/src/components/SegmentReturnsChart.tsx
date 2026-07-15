import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getReturns, type ReturnSeries, type ReturnsPeriod } from '../api/client'

const PERIODS: ReturnsPeriod[] = ['1M', '3M', '6M', 'YTD', '1A', 'MAX']
const PERIOD_LABELS: Record<ReturnsPeriod, string> = {
  '1M': '1M',
  '3M': '3M',
  '6M': '6M',
  YTD: 'YTD',
  '1A': '1A',
  MAX: 'Desde o início',
}

const monthFormatter = new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit' })
const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})
const pctFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

interface Benchmark {
  key: string
  label: string
  color: string
}

interface Props {
  segmentKey: string
  segmentLabel: string
  color: string
  benchmark?: Benchmark
  // 'USD' values the segment in dollars (EUA/Cripto); default BRL.
  currency?: 'BRL' | 'USD'
}

function mergeByDate(series: ReturnSeries[]): Record<string, number | string | null>[] {
  const rows = new Map<string, Record<string, number | string | null>>()
  for (const s of series) {
    for (const point of s.points) {
      const row = rows.get(point.date) ?? { date: point.date }
      row[s.key] = point.return_pct != null ? Number(point.return_pct) : null
      rows.set(point.date, row)
    }
  }
  return [...rows.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
}

export default function SegmentReturnsChart({
  segmentKey,
  segmentLabel,
  color,
  benchmark,
  currency = 'BRL',
}: Props) {
  const [period, setPeriod] = useState<ReturnsPeriod>('1A')
  const [series, setSeries] = useState<ReturnSeries[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    getReturns({
      segments: [segmentKey],
      benchmarks: benchmark ? [benchmark.key] : [],
      period,
      currency,
    })
      .then((data) => {
        if (!cancelled) {
          setSeries(data.series)
          setError(false)
        }
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [segmentKey, benchmark, period, currency])

  const data = useMemo(() => (series ? mergeByDate(series) : []), [series])
  const labels: Record<string, string> = {
    [segmentKey]: segmentLabel,
    ...(benchmark ? { [benchmark.key]: benchmark.label } : {}),
  }
  const colors: Record<string, string> = {
    [segmentKey]: color,
    ...(benchmark ? { [benchmark.key]: benchmark.color } : {}),
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-slate-400">
            Rentabilidade do segmento{' '}
            <span className="text-xs text-slate-500">
              (TWR acumulado no período{currency === 'USD' ? ', em US$' : ''}, %)
            </span>
          </p>
          <p className="mt-0.5 max-w-prose text-[11px] text-slate-500">
            TWR (time-weighted): retorno do ativo ao longo do tempo, sem peso do
            tamanho/data dos aportes. Pode divergir bastante do retorno simples da
            posição (card acima) quando os aportes foram concentrados.
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

      <div className="h-72">
        {error && (
          <p className="text-sm text-slate-500">
            Não foi possível carregar a rentabilidade.
          </p>
        )}
        {!error && series === null && (
          <p className="text-sm text-slate-500">Carregando rentabilidade…</p>
        )}
        {!error && series !== null && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value: string) =>
                  monthFormatter.format(new Date(`${value}T12:00:00`))
                }
                tick={{ fill: '#64748b', fontSize: 12 }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
                minTickGap={48}
              />
              <YAxis
                tickFormatter={(value: number) => `${value.toFixed(0)}%`}
                tick={{ fill: '#64748b', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={48}
              />
              <Tooltip
                formatter={(value, name) => [
                  value == null ? '—' : pctFormatter.format(Number(value)) + '%',
                  labels[String(name)] ?? String(name),
                ]}
                labelFormatter={(label) =>
                  dayFormatter.format(new Date(`${String(label)}T12:00:00`))
                }
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  color: '#e2e8f0',
                }}
              />
              <Legend
                formatter={(value: string) => (
                  <span className="text-xs text-slate-300">{labels[value] ?? value}</span>
                )}
              />
              <Line
                type="monotone"
                dataKey={segmentKey}
                name={segmentKey}
                stroke={colors[segmentKey]}
                strokeWidth={2.5}
                dot={false}
                connectNulls
              />
              {benchmark && (
                <Line
                  type="monotone"
                  dataKey={benchmark.key}
                  name={benchmark.key}
                  stroke={benchmark.color}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  dot={false}
                  connectNulls
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
