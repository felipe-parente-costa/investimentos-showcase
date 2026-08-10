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
import type { RiskPoint } from '../api/client'
import { formatPercent } from '../lib/format'
import { SECTION_COLORS } from '../lib/colors'
import { SkeletonChart } from './Skeleton'

const monthFormatter = new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit' })
const dayFormatter = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })

interface Props {
  points21d: RiskPoint[] | null
  points63d: RiskPoint[] | null
  error: boolean
}

export default function RollingVolatilityChart({ points21d, points63d, error }: Props) {
  const byDate = new Map<string, { date: string; d21?: number; d63?: number }>()
  for (const p of points21d ?? []) {
    byDate.set(p.date, { ...(byDate.get(p.date) ?? { date: p.date }), d21: p.value })
  }
  for (const p of points63d ?? []) {
    byDate.set(p.date, { ...(byDate.get(p.date) ?? { date: p.date }), d63: p.value })
  }
  const data = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date))

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <p className="text-section">Volatilidade móvel anualizada</p>
      <p className="mb-3 text-xs text-slate-500">
        Desvio-padrão dos retornos diários da carteira, em janelas móveis de 21 e 63 dias.
      </p>
      <div className="h-56">
        {error && <p className="text-sm text-slate-500">Não foi possível carregar a volatilidade móvel.</p>}
        {!error && (points21d === null || points63d === null) && <SkeletonChart />}
        {!error && points21d !== null && points63d !== null && data.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--color-slate-800)" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value: string) =>
                  monthFormatter.format(new Date(`${value}T12:00:00`))
                }
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={{ stroke: 'var(--color-slate-700)' }}
                tickLine={false}
                minTickGap={48}
              />
              <YAxis
                tickFormatter={(value: number) => formatPercent(value)}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip
                formatter={(value, name) => [
                  value == null ? '—' : formatPercent(Number(value)),
                  name === 'd21' ? '21 dias' : '63 dias',
                ]}
                labelFormatter={(label) =>
                  dayFormatter.format(new Date(`${String(label)}T12:00:00`))
                }
                contentStyle={{
                  backgroundColor: 'var(--color-slate-900)',
                  border: '1px solid var(--color-slate-700)',
                  borderRadius: '0.5rem',
                  color: 'var(--color-slate-200)',
                }}
              />
              <Legend
                formatter={(value: string) => (
                  <span className="text-xs text-slate-300">
                    {value === 'd21' ? '21 dias' : '63 dias'}
                  </span>
                )}
              />
              <Line
                type="monotone"
                dataKey="d21"
                name="d21"
                stroke={SECTION_COLORS.total}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="d63"
                name="d63"
                stroke="var(--color-slate-400)"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        )}
        {!error && points21d !== null && points63d !== null && data.length === 0 && (
          <p className="text-sm text-slate-500">Histórico insuficiente para volatilidade móvel.</p>
        )}
      </div>
    </div>
  )
}
