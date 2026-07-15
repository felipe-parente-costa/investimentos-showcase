import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getPortfolioHistory, type HistoryPoint } from '../api/client'
import { formatMoney } from '../lib/format'
import { SECTION_COLORS } from '../lib/colors'
import {
  PERIOD_OPTIONS,
  filterByPeriod,
  granularityFor,
  type Period,
} from '../lib/periods'

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
})

const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

const compactBRL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 0,
})

function axisDate(value: string): string {
  return monthFormatter.format(new Date(`${value}T12:00:00`))
}

function tooltipDate(value: string): string {
  return dayFormatter.format(new Date(`${value}T12:00:00`))
}

export default function PatrimonyChart() {
  const [period, setPeriod] = useState<Period>('max')
  const [points, setPoints] = useState<HistoryPoint[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    getPortfolioHistory(granularityFor(period))
      .then((data) => {
        if (!cancelled) {
          setPoints(data.points)
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

  const visible = points !== null ? filterByPeriod(points, period) : null
  const data = (visible ?? []).map((p) => ({
    date: p.date,
    total: Number(p.total_brl),
  }))

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-section">Evolução patrimonial</p>
        <div className="flex gap-1">
          {PERIOD_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setPeriod(option.value)}
              className={`rounded-md px-2 py-1 text-xs ${
                period === option.value
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="h-72">
        {error && (
          <p className="text-sm text-slate-500">
            Não foi possível carregar o histórico.
          </p>
        )}
        {!error && points === null && (
          <p className="text-sm text-slate-500">Carregando histórico…</p>
        )}
        {!error && points !== null && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <defs>
                <linearGradient id="patrimony" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={SECTION_COLORS.total}
                    stopOpacity={0.25}
                  />
                  <stop
                    offset="100%"
                    stopColor={SECTION_COLORS.total}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={axisDate}
                tick={{ fill: '#64748b', fontSize: 12 }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
                minTickGap={48}
              />
              <YAxis
                tickFormatter={(value: number) => compactBRL.format(value)}
                tick={{ fill: '#64748b', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={72}
              />
              <Tooltip
                formatter={(value) => [formatMoney(String(value)), 'Patrimônio']}
                labelFormatter={(label) => tooltipDate(String(label))}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  color: '#e2e8f0',
                }}
              />
              <Area
                type="monotone"
                dataKey="total"
                stroke={SECTION_COLORS.total}
                strokeWidth={2}
                fill="url(#patrimony)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
