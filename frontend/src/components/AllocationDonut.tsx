import type { ReactNode } from 'react'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { formatMoney, formatPercent } from '../lib/format'
import { DONUT_PALETTE, OTHERS_COLOR, OTHERS_LABEL } from '../lib/colors'

export interface DonutSlice {
  label: string
  value: number
  color?: string
  // Preenchido só na fatia "Outros": os itens agregados, para o tooltip listar
  // quais são os "outros" (não só a soma).
  members?: { label: string; value: number }[]
}

interface Props {
  title: string
  slices: DonutSlice[]
  // Currency for the tooltip values; reuses the shared formatMoney so the
  // pt-BR formatting (e.g. "US$ 5.545,65") matches the rest of the section.
  currency?: string
  // Máximo de fatias nomeadas (por tamanho desc); o excedente colapsa numa
  // fatia única "Outros". Default = tamanho da paleta central.
  maxSlices?: number
  // Conteúdo opcional à direita do título (ex.: chips de filtro).
  headerRight?: ReactNode
}

export default function AllocationDonut({
  title,
  slices,
  currency = 'BRL',
  maxSlices = DONUT_PALETTE.length,
  headerRight,
}: Props) {
  const sorted = [...slices].sort((a, b) => b.value - a.value)
  // "Outros" só aparece com MAIS que maxSlices fatias; com ≤ maxSlices, todas
  // nomeadas, sem cinza. O excedente vira uma fatia única com seus membros.
  const data: DonutSlice[] =
    sorted.length > maxSlices
      ? [
          ...sorted.slice(0, maxSlices),
          {
            label: OTHERS_LABEL,
            value: sorted
              .slice(maxSlices)
              .reduce((sum, slice) => sum + slice.value, 0),
            color: OTHERS_COLOR,
            members: sorted
              .slice(maxSlices)
              .map((s) => ({ label: s.label, value: s.value })),
          },
        ]
      : sorted
  // Base única do %: o total ATUAL do donut (top N + Outros). Toda fatia e todo
  // item do "Outros" são % desse total — somam ~100% com o que está visível.
  const total = data.reduce((sum, slice) => sum + slice.value, 0)
  const pct = (value: number) => formatPercent(total > 0 ? value / total : 0)

  // Direct label for the two largest slices only (data is already sorted
  // desc, "Outros" appended last) — the rest stay legend/tooltip-only so the
  // donut doesn't turn into a wall of tiny text. Percent only (not the
  // category name): the cards are narrow in a 3-column grid, and a long
  // label like "Renda fixa"/"Estados Unidos" on the left side clips against
  // the card edge — the name is one glance away in the legend below.
  const RADIAN = Math.PI / 180
  const renderDirectLabel = (props: {
    cx: number
    cy: number
    midAngle: number
    outerRadius: number
    index: number
    payload: DonutSlice
  }) => {
    const { cx, cy, midAngle, outerRadius, index, payload } = props
    if (index > 1) return null
    const radius = outerRadius + 12
    const x = cx + radius * Math.cos(-midAngle * RADIAN)
    const y = cy + radius * Math.sin(-midAngle * RADIAN)
    return (
      <text
        x={x}
        y={y}
        fill="var(--color-slate-100)"
        fontSize={11}
        fontWeight={600}
        textAnchor={x > cx ? 'start' : 'end'}
        dominantBaseline="central"
      >
        {pct(payload.value)}
      </text>
    )
  }

  const renderTooltip = ({
    active,
    payload,
  }: {
    active?: boolean
    payload?: ReadonlyArray<{ payload?: DonutSlice }>
  }): ReactNode => {
    if (!active || !payload || payload.length === 0) return null
    const slice = payload[0].payload
    if (!slice) return null
    const box =
      'rounded-lg border border-slate-700 bg-slate-900 text-xs text-slate-200'

    if (slice.members && slice.members.length > 0) {
      return (
        <div className={box} style={{ pointerEvents: 'auto' }}>
          <div className="border-b border-slate-700 px-3 py-2 font-medium">
            {slice.label} ({slice.members.length}){' '}
            <span className="tabular-nums text-slate-400">
              {formatMoney(String(slice.value), currency)} ({pct(slice.value)})
            </span>
          </div>
          <ul className="max-h-64 space-y-1 overflow-y-auto px-3 py-2">
            {[...slice.members]
              .sort((a, b) => b.value - a.value)
              .map((m) => (
                <li
                  key={m.label}
                  className="flex items-center justify-between gap-4"
                >
                  <span>{m.label}</span>
                  <span className="tabular-nums text-slate-400">
                    {formatMoney(String(m.value), currency)}
                    <span className="ml-2 text-slate-500">{pct(m.value)}</span>
                  </span>
                </li>
              ))}
          </ul>
        </div>
      )
    }

    return (
      <div className={`${box} px-3 py-2`}>
        <div className="font-medium">{slice.label}</div>
        <div className="tabular-nums text-slate-300">
          {formatMoney(String(slice.value), currency)} ({pct(slice.value)})
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-slate-400">{title}</p>
        {headerRight}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius="55%"
              outerRadius="80%"
              paddingAngle={2}
              stroke="none"
              label={renderDirectLabel}
              labelLine={false}
            >
              {data.map((slice, index) => (
                <Cell
                  key={index}
                  fill={slice.color ?? DONUT_PALETTE[index % DONUT_PALETTE.length]}
                />
              ))}
            </Pie>
            <Tooltip content={renderTooltip} wrapperStyle={{ pointerEvents: 'auto' }} />
            <Legend
              formatter={(value: string) => (
                <span className="text-xs text-slate-300">{value}</span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
