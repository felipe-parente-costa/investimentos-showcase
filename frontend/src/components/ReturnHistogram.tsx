import { useMemo } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { RiskPoint } from '../api/client'
import { formatPercent } from '../lib/format'
import { SkeletonChart } from './Skeleton'

const BINS = 24

const pctFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

interface Bin {
  mid: number
  from: number
  to: number
  count: number
}

function histogram(values: number[], bins: number): Bin[] {
  if (values.length === 0) return []
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) return [{ mid: min, from: min, to: max, count: values.length }]
  const width = (max - min) / bins
  const buckets: Bin[] = Array.from({ length: bins }, (_, i) => ({
    from: min + i * width,
    to: min + (i + 1) * width,
    mid: min + (i + 0.5) * width,
    count: 0,
  }))
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.floor((v - min) / width))
    buckets[idx].count += 1
  }
  return buckets
}

interface Props {
  returns: RiskPoint[] | null
  error: boolean
  skewness: number | null
  kurtosisExcess: number | null
}

export default function ReturnHistogram({ returns, error, skewness, kurtosisExcess }: Props) {
  // Dias de negociação apenas: é a grade em que assimetria e curtose (no
  // canto deste mesmo card) são calculadas, e um monte de sábados parados
  // desenharia uma barra falsa no zero.
  const bins = useMemo(
    () =>
      histogram(
        (returns ?? [])
          .filter((p) => new Date(`${p.date}T12:00:00`).getDay() % 6 !== 0)
          .map((p) => p.value),
        BINS,
      ),
    [returns],
  )

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="text-section">Distribuição dos retornos diários</p>
          <p className="text-xs text-slate-500">
            Verde = dias de alta, vermelho = dias de baixa. Só dias de negociação — a mesma grade da assimetria e da curtose ao lado.
          </p>
        </div>
        <div className="flex gap-4 text-xs text-slate-400">
          <span>
            Assimetria:{' '}
            <span className="tabular-nums text-slate-200">
              {skewness != null ? pctFormatter.format(skewness) : '—'}
            </span>
          </span>
          <span>
            Curtose (excesso):{' '}
            <span className="tabular-nums text-slate-200">
              {kurtosisExcess != null ? pctFormatter.format(kurtosisExcess) : '—'}
            </span>
          </span>
        </div>
      </div>
      <div className="h-56">
        {error && <p className="text-sm text-slate-500">Não foi possível carregar a distribuição.</p>}
        {!error && returns === null && <SkeletonChart />}
        {!error && returns !== null && bins.length > 1 && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bins} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <XAxis
                dataKey="mid"
                tickFormatter={(value: number) => formatPercent(value)}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 11 }}
                axisLine={{ stroke: 'var(--color-slate-700)' }}
                tickLine={false}
                minTickGap={32}
              />
              <YAxis
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={32}
                allowDecimals={false}
              />
              <Tooltip
                formatter={(value, _name, item) => [
                  `${value} dia(s)`,
                  `${formatPercent(item.payload.from)} a ${formatPercent(item.payload.to)}`,
                ]}
                contentStyle={{
                  backgroundColor: 'var(--color-slate-900)',
                  border: '1px solid var(--color-slate-700)',
                  borderRadius: '0.5rem',
                  color: 'var(--color-slate-200)',
                }}
              />
              <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                {bins.map((bin, i) => (
                  <Cell
                    key={i}
                    fill={bin.mid >= 0 ? 'var(--color-green-400)' : 'var(--color-red-400)'}
                    fillOpacity={0.75}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
        {!error && returns !== null && bins.length <= 1 && (
          <p className="text-sm text-slate-500">Histórico insuficiente para a distribuição.</p>
        )}
      </div>
    </div>
  )
}
