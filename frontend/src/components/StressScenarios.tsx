import type { StressScenario } from '../api/client'
import { formatMoney, formatSignedPercent } from '../lib/format'

function impactColor(value: number | null): string {
  if (value == null || value === 0) return 'text-slate-200'
  return value > 0 ? 'text-green-400' : 'text-red-400'
}

export default function StressScenarios({
  scenarios,
}: {
  scenarios: StressScenario[] | null
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <p className="text-section">Cenários de estresse</p>
      <p className="mb-3 text-xs text-slate-500">
        Impacto estimado se o choque ocorresse hoje, aplicado à exposição direta de cada
        segmento (beta do CAPM quando disponível, 1,0 quando não).
      </p>
      {scenarios === null && <p className="text-sm text-slate-500">Carregando…</p>}
      {scenarios !== null && scenarios.length === 0 && (
        <p className="text-sm text-slate-500">Sem exposição para simular cenários.</p>
      )}
      {scenarios !== null && scenarios.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="py-2 pr-3 font-normal">Cenário</th>
                <th className="py-2 pr-3 font-normal">Exposição</th>
                <th className="py-2 pr-3 font-normal">Beta usado</th>
                <th className="py-2 pr-3 text-right font-normal">Impacto</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr key={s.key} className="border-b border-slate-800/60 last:border-0">
                  <td className="py-2 pr-3">
                    <p className="text-slate-200">{s.label}</p>
                    {s.beta_note && <p className="text-[11px] text-slate-500">{s.beta_note}</p>}
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-slate-300">
                    {formatMoney(s.exposure_brl)}
                  </td>
                  <td className="py-2 pr-3 tabular-nums text-slate-300">
                    {s.beta.toFixed(2)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    <span className={impactColor(s.impact_pct)}>
                      {s.impact_brl != null ? formatMoney(s.impact_brl) : '—'}
                      {s.impact_pct != null && (
                        <span className="ml-2 text-xs text-slate-500">
                          ({formatSignedPercent(s.impact_pct)})
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
