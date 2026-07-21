import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getContributions, type ContributionMonth } from '../api/client'
import { formatMoney } from '../lib/format'
import { SkeletonChart } from './Skeleton'

const monthFormatter = new Intl.DateTimeFormat('pt-BR', {
  month: 'short',
  year: '2-digit',
})

const compactBRL = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 0,
})

function monthLabel(value: string): string {
  return monthFormatter.format(new Date(`${value}-15T12:00:00`))
}

type SeriesKey = 'aportes' | 'rendimentos'

export default function ContributionsChart() {
  const [months, setMonths] = useState<ContributionMonth[] | null>(null)
  const [error, setError] = useState(false)
  // Clicking a legend item toggles its series. A hidden Bar (hide) is
  // excluded from the Y-axis domain, so the scale re-fits what remains.
  const [hidden, setHidden] = useState<Record<SeriesKey, boolean>>({
    aportes: false,
    rendimentos: false,
  })

  function toggleSeries(key: unknown) {
    if (key !== 'aportes' && key !== 'rendimentos') return
    setHidden((current) => ({ ...current, [key]: !current[key] }))
  }

  useEffect(() => {
    let cancelled = false
    getContributions(24)
      .then((data) => {
        if (!cancelled) {
          setMonths(data.months)
          setError(false)
        }
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const data = (months ?? []).map((m) => ({
    month: m.month,
    aportes: Number(m.aportes),
    rendimentos: Number(m.rendimentos),
  }))

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <p className="mb-4 text-section">
        Aportes mensais vs. rendimentos{' '}
        <span className="text-caption font-normal text-slate-500">
          (últimos 24 meses)
        </span>
      </p>
      <div className="h-64">
        {error && (
          <p className="text-sm text-slate-500">Não foi possível carregar os aportes.</p>
        )}
        {!error && months === null && <SkeletonChart />}
        {!error && months !== null && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--color-slate-800)" vertical={false} />
              <XAxis
                dataKey="month"
                tickFormatter={monthLabel}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={{ stroke: 'var(--color-slate-700)' }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tickFormatter={(value: number) => compactBRL.format(value)}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={72}
              />
              <Tooltip
                formatter={(value, name) => [formatMoney(String(value)), String(name)]}
                labelFormatter={(label) => monthLabel(String(label))}
                cursor={{ fill: 'var(--color-slate-800)', opacity: 0.4 }}
                contentStyle={{
                  backgroundColor: 'var(--color-slate-900)',
                  border: '1px solid var(--color-slate-700)',
                  borderRadius: '0.5rem',
                  color: 'var(--color-slate-200)',
                }}
              />
              <Legend
                onClick={(item) => toggleSeries(item.dataKey)}
                wrapperStyle={{ cursor: 'pointer' }}
                formatter={(value: string, entry) => {
                  const key = (entry as { dataKey?: unknown }).dataKey
                  const off = key === 'aportes' || key === 'rendimentos'
                    ? hidden[key]
                    : false
                  return (
                    <span
                      title="Clique para exibir/ocultar a série"
                      className={`text-xs ${
                        off ? 'text-slate-600 line-through' : 'text-slate-300'
                      }`}
                    >
                      {value}
                    </span>
                  )
                }}
              />
              {/* Par de contraste LOCAL (aporte vs rendimento), não identidade
                  de seção nem categoria — usa dois neutros (cinza quente + teal
                  apagado) que não pertencem a nenhum mapa central, evitando
                  carregar significado de seção/categoria. */}
              <Bar
                dataKey="aportes"
                name="Aportes"
                stackId="mes"
                fill="var(--color-slate-400)"
                hide={hidden.aportes}
                radius={hidden.rendimentos ? [3, 3, 0, 0] : undefined}
              />
              <Bar
                dataKey="rendimentos"
                name="Rendimentos"
                stackId="mes"
                fill="var(--color-contrib-yield)"
                hide={hidden.rendimentos}
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
