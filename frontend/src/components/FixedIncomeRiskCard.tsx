import type { FixedIncomeRisk } from '../api/client'
import { formatMoney, formatPercent, prettifyInstitution } from '../lib/format'
import { DONUT_PALETTE } from '../lib/colors'

const INDEXER_BAR_COLORS: Record<string, string> = {
  ipca: 'var(--color-data-teal)',
  prefixado: 'var(--color-data-gold)',
  selic: 'var(--color-data-blue)',
}

export default function FixedIncomeRiskCard({
  data,
}: {
  data: FixedIncomeRisk | null | undefined
}) {
  if (data === undefined) return null // no fixed-income position at all
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <p className="text-section">Renda fixa — risco de concentração</p>
      <p className="mb-4 text-xs text-slate-500">
        Marcada a custo (exceto Tesouro): sem volatilidade ou VaR de mercado. O risco aqui é
        de indexador (juros) e de emissor (crédito/contraparte), não de preço.
      </p>
      {data === null && <p className="text-sm text-slate-500">Carregando…</p>}
      {data !== null && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              Por indexador
            </p>
            <div className="flex h-3 overflow-hidden rounded-full bg-slate-800">
              {data.by_indexer.map((slice) => (
                <div
                  key={slice.key}
                  style={{
                    width: `${slice.weight_pct * 100}%`,
                    backgroundColor: INDEXER_BAR_COLORS[slice.key] ?? 'var(--color-data-gray)',
                  }}
                  title={`${slice.label}: ${formatPercent(slice.weight_pct)}`}
                />
              ))}
            </div>
            <ul className="mt-3 space-y-1.5 text-sm">
              {data.by_indexer.map((slice) => (
                <li key={slice.key} className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 text-slate-300">
                    <span
                      className="h-2.5 w-2.5 rounded-sm"
                      style={{
                        backgroundColor:
                          INDEXER_BAR_COLORS[slice.key] ?? 'var(--color-data-gray)',
                      }}
                    />
                    {slice.label}
                  </span>
                  <span className="tabular-nums text-slate-400">
                    {formatMoney(slice.value_brl)}{' '}
                    <span className="text-slate-500">({formatPercent(slice.weight_pct)})</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="mb-2 flex items-center justify-between text-xs font-medium uppercase tracking-wide text-slate-500">
              <span>Por instituição</span>
              {data.hhi_institution != null && (
                <span className="normal-case text-slate-500">
                  HHI {data.hhi_institution.toFixed(2)}
                </span>
              )}
            </p>
            <ul className="space-y-1.5 text-sm">
              {data.by_institution.map((slice, i) => (
                <li key={slice.label} className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 text-slate-300">
                    <span
                      className="h-2.5 w-2.5 rounded-sm"
                      style={{ backgroundColor: DONUT_PALETTE[i % DONUT_PALETTE.length] }}
                    />
                    {prettifyInstitution(slice.label)}
                  </span>
                  <span className="tabular-nums text-slate-400">
                    {formatMoney(slice.value_brl)}{' '}
                    <span className="text-slate-500">({formatPercent(slice.weight_pct)})</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      <p className="mt-4 text-xs text-slate-500">
        Total em renda fixa: {data ? formatMoney(data.total_brl) : '—'}
      </p>
    </div>
  )
}
