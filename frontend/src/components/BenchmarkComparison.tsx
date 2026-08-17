import type { BenchmarkComparison as Comparison } from '../api/client'
import { formatPercent, formatSignedPercent } from '../lib/format'

const coefFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

interface Props {
  comparisons: Comparison[]
  periodLabel: string
}

/** The block a professional risk report opens with: how much of the index's
 * rise the book captured, how much of its fall it took, how often it beat
 * it, and whether the active bet paid for its own tracking error. */
export default function BenchmarkComparison({ comparisons, periodLabel }: Props) {
  if (comparisons.length === 0) return null

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-section">Contra o benchmark</p>
        <p className="text-xs text-slate-500">
          Janela: {periodLabel} · retornos mensais
        </p>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Captura de alta e de baixa comparam a média geométrica da carteira nos meses em
        que o índice subiu (ou caiu) com a do próprio índice. Capturar 100% da alta e 0%
        da baixa seria o ideal; abaixo de 100% na baixa já significa cair menos que ele.
      </p>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              <th className="py-2 pr-3 font-normal">Índice</th>
              <th className="py-2 pr-3 text-right font-normal">Captura de alta</th>
              <th className="py-2 pr-3 text-right font-normal">Captura de baixa</th>
              <th className="py-2 pr-3 text-right font-normal">Batting average</th>
              <th className="py-2 pr-3 text-right font-normal">Retorno ativo</th>
              <th className="py-2 pr-3 text-right font-normal">Tracking error</th>
              <th className="py-2 pr-3 text-right font-normal">Information ratio</th>
            </tr>
          </thead>
          <tbody>
            {comparisons.map((c) => (
              <tr key={c.key} className="border-b border-slate-800/60 last:border-0">
                <td className="py-2 pr-3 text-slate-200">
                  {c.label}
                  <span className="ml-1.5 text-xs text-slate-500">
                    {c.months} meses · {c.up_months}↑ {c.down_months}↓
                  </span>
                </td>
                {/* Capturar MAIS da alta é bom; capturar MENOS da baixa é bom. */}
                <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                  {c.upside_capture != null ? formatPercent(c.upside_capture) : '—'}
                </td>
                <td
                  className={`py-2 pr-3 text-right tabular-nums ${
                    c.downside_capture != null && c.downside_capture < 1
                      ? 'text-green-400'
                      : 'text-slate-300'
                  }`}
                >
                  {c.downside_capture != null ? formatPercent(c.downside_capture) : '—'}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                  {c.batting_average != null ? formatPercent(c.batting_average) : '—'}
                </td>
                <td
                  className={`py-2 pr-3 text-right tabular-nums ${
                    c.active_return_annual_pct != null && c.active_return_annual_pct < 0
                      ? 'text-red-400'
                      : 'text-green-400'
                  }`}
                >
                  {c.active_return_annual_pct != null
                    ? formatSignedPercent(c.active_return_annual_pct)
                    : '—'}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums text-slate-300">
                  {c.tracking_error_annual_pct != null
                    ? formatPercent(c.tracking_error_annual_pct)
                    : '—'}
                </td>
                <td
                  className={`py-2 pr-3 text-right tabular-nums ${
                    c.information_ratio != null && c.information_ratio < 0
                      ? 'text-red-400'
                      : 'text-green-400'
                  }`}
                >
                  {c.information_ratio != null ? coefFormatter.format(c.information_ratio) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        Mensais porque é como a métrica é definida — e porque retorno diário tem
        autocorrelação e ruído de microestrutura que enviesam o número. Meses parciais
        nas bordas da janela não entram. Mínimo de 12 meses para reportar.
      </p>
    </div>
  )
}
