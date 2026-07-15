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

export default function ContributionsChart() {
  const [months, setMonths] = useState<ContributionMonth[] | null>(null)
  const [error, setError] = useState(false)

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
        {!error && months === null && (
          <p className="text-sm text-slate-500">Carregando aportes…</p>
        )}
        {!error && months !== null && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="month"
                tickFormatter={monthLabel}
                tick={{ fill: '#64748b', fontSize: 12 }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tickFormatter={(value: number) => compactBRL.format(value)}
                tick={{ fill: '#64748b', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={72}
              />
              <Tooltip
                formatter={(value, name) => [formatMoney(String(value)), String(name)]}
                labelFormatter={(label) => monthLabel(String(label))}
                cursor={{ fill: '#1e293b', opacity: 0.4 }}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '0.5rem',
                  color: '#e2e8f0',
                }}
              />
              <Legend
                formatter={(value: string) => (
                  <span className="text-xs text-slate-300">{value}</span>
                )}
              />
              {/* Par de contraste LOCAL (aporte vs rendimento), não identidade
                  de seção nem categoria — usa dois neutros (slate claro + teal
                  apagado) que não pertencem a nenhum mapa central, evitando
                  carregar significado de seção/categoria. */}
              <Bar dataKey="aportes" name="Aportes" stackId="mes" fill="#94a3b8" />
              <Bar
                dataKey="rendimentos"
                name="Rendimentos"
                stackId="mes"
                fill="#14b8a6"
                radius={[3, 3, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
