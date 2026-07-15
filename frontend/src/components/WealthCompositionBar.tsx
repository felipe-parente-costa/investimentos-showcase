import { formatMoney, formatPercent, formatSignedPercent } from '../lib/format'

interface Props {
  // Aggregates from /portfolio (already in BRL): aportado = Σ cost_brl of the
  // current positions (PM × qty); total = total_market_value_brl.
  aportado: number
  total: number
}

// Composição do patrimônio (hoje): aportado + valorização = total, por
// construção (valorização = total − aportado), então a identidade vale mesmo
// quando a valorização é negativa (perda). A barra sempre cobre o maior dos
// dois, então a perda aparece "comendo" o aportado sem quebrar a largura.
export default function WealthCompositionBar({ aportado, total }: Props) {
  const valorizacao = total - aportado
  const isLoss = valorizacao < 0
  const maxVal = Math.max(aportado, total, 1)
  const returnPct = aportado !== 0 ? valorizacao / aportado : 0
  const hasComposition = total > 0 || aportado > 0

  if (!hasComposition) return null

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <p className="text-section">Composição do patrimônio (atual)</p>
      <div className="mt-4 flex h-7 w-full overflow-hidden rounded-md bg-slate-950">
        {isLoss ? (
          <>
            <div
              className="bg-sky-500"
              style={{ width: `${(total / maxVal) * 100}%` }}
              title={`Patrimônio atual: ${formatMoney(String(total))}`}
            />
            <div
              className="bg-red-500"
              style={{ width: `${(-valorizacao / maxVal) * 100}%` }}
              title={`Perda: ${formatMoney(String(valorizacao))} (${formatSignedPercent(
                returnPct,
              )} sobre o aportado)`}
            />
          </>
        ) : (
          <>
            <div
              className="bg-sky-500"
              style={{ width: `${(aportado / maxVal) * 100}%` }}
              title={`Aportado: ${formatMoney(String(aportado))}`}
            />
            <div
              className="bg-emerald-500"
              style={{ width: `${(valorizacao / maxVal) * 100}%` }}
              title={`Valorização: ${formatMoney(String(valorizacao))} (${formatSignedPercent(
                returnPct,
              )} sobre o aportado)`}
            />
          </>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-body">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-sky-500" />
          <span className="text-slate-400">Aportado</span>
          <span className="tabular-nums text-slate-200">
            {formatMoney(String(aportado))}
          </span>
          <span className="text-slate-500">
            ({formatPercent(total > 0 ? aportado / total : 0)})
          </span>
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className={`h-2.5 w-2.5 rounded-sm ${
              isLoss ? 'bg-red-500' : 'bg-emerald-500'
            }`}
          />
          <span className="text-slate-400">{isLoss ? 'Perda' : 'Valorização'}</span>
          <span
            className={`tabular-nums ${isLoss ? 'text-red-400' : 'text-emerald-400'}`}
          >
            {formatMoney(String(valorizacao))}
          </span>
          <span className="text-slate-500">
            ({formatSignedPercent(returnPct)} sobre o aportado)
          </span>
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          <span className="text-slate-400">Total</span>
          <span className="font-medium tabular-nums text-slate-100">
            {formatMoney(String(total))}
          </span>
        </span>
      </div>
    </div>
  )
}
