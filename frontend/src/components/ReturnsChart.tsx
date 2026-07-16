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
import {
  getReturns,
  type ReturnSeries,
  type ReturnsPeriod,
} from '../api/client'
import { BENCHMARK_COLORS, SECTION_COLORS } from '../lib/colors'

const PERIODS: ReturnsPeriod[] = ['1M', '3M', '6M', 'YTD', '1A', 'MAX']
const PERIOD_LABELS: Record<ReturnsPeriod, string> = {
  '1M': '1M',
  '3M': '3M',
  '6M': '6M',
  YTD: 'YTD',
  '1A': '1A',
  MAX: 'Desde o início',
}

interface LineDef {
  key: string
  label: string
  color: string
  kind: 'segment' | 'benchmark'
}

const SEGMENTS: LineDef[] = [
  { key: 'total', label: 'Carteira Total', color: SECTION_COLORS.total, kind: 'segment' },
  { key: 'br', label: 'Brasil (B3)', color: SECTION_COLORS.br, kind: 'segment' },
  { key: 'us', label: 'EUA (Avenue)', color: SECTION_COLORS.us, kind: 'segment' },
  { key: 'crypto', label: 'Cripto', color: SECTION_COLORS.crypto, kind: 'segment' },
  { key: 'rf', label: 'Renda Fixa', color: SECTION_COLORS.rf, kind: 'segment' },
]

const BENCHMARKS: LineDef[] = [
  { key: 'cdi', label: 'CDI', color: BENCHMARK_COLORS.cdi, kind: 'benchmark' },
  { key: 'ibov', label: 'IBOV', color: BENCHMARK_COLORS.ibov, kind: 'benchmark' },
  { key: 'sp500', label: 'S&P 500', color: BENCHMARK_COLORS.sp500, kind: 'benchmark' },
  { key: 'btc', label: 'BTC', color: BENCHMARK_COLORS.btc, kind: 'benchmark' },
]

const ALL_LINES = [...SEGMENTS, ...BENCHMARKS]
const COLOR = Object.fromEntries(ALL_LINES.map((l) => [l.key, l.color]))
const LABEL = Object.fromEntries(ALL_LINES.map((l) => [l.key, l.label]))

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
})
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

function mergeByDate(series: ReturnSeries[]): Record<string, number | string | null>[] {
  const rows = new Map<string, Record<string, number | string | null>>()
  for (const s of series) {
    for (const point of s.points) {
      const row = rows.get(point.date) ?? { date: point.date }
      row[s.key] = point.return_pct != null ? Number(point.return_pct) : null
      rows.set(point.date, row)
    }
  }
  return [...rows.values()].sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  )
}

export default function ReturnsChart() {
  const [period, setPeriod] = useState<ReturnsPeriod>('1A')
  const [selected, setSelected] = useState<Record<string, boolean>>({
    total: true,
    br: true,
    us: true,
    crypto: true,
  })
  const [series, setSeries] = useState<ReturnSeries[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    // Fetch every segment and benchmark for the period; checkboxes toggle
    // line visibility client-side without refetching.
    getReturns({
      segments: SEGMENTS.map((s) => s.key),
      benchmarks: BENCHMARKS.map((b) => b.key),
      period,
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
  }, [period])

  const data = useMemo(() => (series ? mergeByDate(series) : []), [series])
  const activeKeys = ALL_LINES.filter((l) => selected[l.key]).map((l) => l.key)

  function toggle(key: string) {
    setSelected((current) => ({ ...current, [key]: !current[key] }))
  }

  function Checkbox({ line }: { line: LineDef }) {
    const on = !!selected[line.key]
    return (
      <button
        type="button"
        onClick={() => toggle(line.key)}
        className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ${
          on ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:bg-slate-800/60'
        }`}
      >
        <span
          className="h-2.5 w-2.5 rounded-sm"
          style={{ backgroundColor: on ? line.color : 'transparent', border: `1.5px solid ${line.color}` }}
        />
        {line.label}
      </button>
    )
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-section">
          Rentabilidade por segmento{' '}
          <span className="text-caption font-normal text-slate-500">
            (acumulada no período, %)
          </span>
        </p>
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

      <div className="mb-3 space-y-1.5">
        <div className="flex flex-wrap gap-1">
          {SEGMENTS.map((line) => (
            <Checkbox key={line.key} line={line} />
          ))}
        </div>
        <div className="flex flex-wrap gap-1">
          <span className="px-2 py-1 text-xs text-slate-600">Benchmarks:</span>
          {BENCHMARKS.map((line) => (
            <Checkbox key={line.key} line={line} />
          ))}
        </div>
      </div>

      <div className="h-80">
        {error && (
          <p className="text-sm text-slate-500">Não foi possível carregar as rentabilidades.</p>
        )}
        {!error && series === null && (
          <p className="text-sm text-slate-500">Carregando rentabilidades…</p>
        )}
        {!error && series !== null && activeKeys.length === 0 && (
          <p className="text-sm text-slate-500">Selecione ao menos um segmento ou benchmark.</p>
        )}
        {!error && series !== null && activeKeys.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#322d27" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value: string) =>
                  monthFormatter.format(new Date(`${value}T12:00:00`))
                }
                tick={{ fill: '#6e675c', fontSize: 12 }}
                axisLine={{ stroke: '#453f36' }}
                tickLine={false}
                minTickGap={48}
              />
              <YAxis
                tickFormatter={(value: number) => `${value.toFixed(0)}%`}
                tick={{ fill: '#6e675c', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={48}
              />
              <Tooltip
                formatter={(value, name) => [
                  value == null ? '—' : pctFormatter.format(Number(value)) + '%',
                  LABEL[String(name)] ?? String(name),
                ]}
                labelFormatter={(label) =>
                  dayFormatter.format(new Date(`${String(label)}T12:00:00`))
                }
                contentStyle={{
                  backgroundColor: '#1b1917',
                  border: '1px solid #453f36',
                  borderRadius: '0.5rem',
                  color: '#ddd7ca',
                }}
              />
              <Legend
                formatter={(value: string) => (
                  <span className="text-xs text-slate-300">{LABEL[value] ?? value}</span>
                )}
              />
              {activeKeys.map((key) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={key}
                  stroke={COLOR[key]}
                  strokeWidth={key === 'total' ? 2.5 : 1.5}
                  strokeDasharray={
                    ALL_LINES.find((l) => l.key === key)?.kind === 'benchmark'
                      ? '4 3'
                      : undefined
                  }
                  dot={false}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
