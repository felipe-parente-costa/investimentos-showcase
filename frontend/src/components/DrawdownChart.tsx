import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { RiskPoint } from '../api/client'
import { formatPercent } from '../lib/format'
import { SkeletonChart } from './Skeleton'

const monthFormatter = new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit' })
const dayFormatter = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })

interface Props {
  points: RiskPoint[] | null
  error: boolean
}

export default function DrawdownChart({ points, error }: Props) {
  const data = (points ?? []).map((p) => ({ date: p.date, value: p.value }))

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <p className="text-section">Curva de drawdown</p>
      <p className="mb-3 text-xs text-slate-500">
        Queda em relação ao pico do patrimônio (TWR) até cada data, no período selecionado.
      </p>
      <div className="h-56">
        {error && <p className="text-sm text-slate-500">Não foi possível carregar o drawdown.</p>}
        {!error && points === null && <SkeletonChart />}
        {!error && points !== null && data.length > 1 && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <defs>
                <linearGradient id="drawdown" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-red-400)" stopOpacity={0.05} />
                  <stop offset="100%" stopColor="var(--color-red-400)" stopOpacity={0.35} />
                </linearGradient>
              </defs>
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
                domain={['dataMin', 0]}
                tickFormatter={(value: number) => formatPercent(value)}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={56}
              />
              <Tooltip
                formatter={(value) => [formatPercent(Number(value)), 'Drawdown']}
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
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--color-red-400)"
                strokeWidth={1.5}
                fill="url(#drawdown)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
        {!error && points !== null && data.length <= 1 && (
          <p className="text-sm text-slate-500">Histórico insuficiente para a curva de drawdown.</p>
        )}
      </div>
    </div>
  )
}
