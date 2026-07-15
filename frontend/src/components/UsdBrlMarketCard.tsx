import { useCallback, useEffect, useState } from 'react'
import { getUsdBrlMarket, type UsdBrlMarket } from '../api/client'

// Rates need more precision than money (4 decimals), e.g. "R$ 5,4321".
const rateFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
})

const timeFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

export default function UsdBrlMarketCard() {
  const [data, setData] = useState<UsdBrlMarket | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    getUsdBrlMarket()
      .then((d) => {
        setData(d)
        setFailed(false)
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false))
  }, [])

  // Initial fetch: state is set only in the async callbacks (not synchronously
  // in the effect body), so it does not trigger cascading renders.
  useEffect(() => {
    let cancelled = false
    getUsdBrlMarket()
      .then((d) => {
        if (!cancelled) {
          setData(d)
          setFailed(false)
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const rate = data?.rate != null ? `R$ ${rateFormatter.format(Number(data.rate))}` : '—'
  const when = data?.fetched_at ? timeFormatter.format(new Date(data.fetched_at)) : null

  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3">
      <div>
        <p className="text-xs text-slate-400">Dólar comercial (mercado)</p>
        <p className="mt-0.5 text-xl font-semibold tabular-nums">{rate}</p>
        <p className="mt-0.5 text-[11px] text-slate-500">
          Cotação de mercado, atraso ~15 min · não é a PTAX usada no custo da
          carteira.
          {when && ` Atualizado ${when}.`}
          {data?.stale && ' (última conhecida)'}
          {failed && !data && ' Indisponível no momento.'}
        </p>
      </div>
      <button
        type="button"
        onClick={load}
        disabled={loading}
        className="shrink-0 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
      >
        {loading ? 'Atualizando…' : 'Atualizar'}
      </button>
    </div>
  )
}
