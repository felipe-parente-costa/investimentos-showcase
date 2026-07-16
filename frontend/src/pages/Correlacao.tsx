import { useEffect, useMemo, useState } from 'react'
import {
  getCorrelation,
  getPortfolio,
  type CorrelationPeriod,
  type CorrelationResponse,
  type CorrelationSegment,
} from '../api/client'
import CorrelationHeatmap from '../components/CorrelationHeatmap'
import { formatCoef, type HoveredCell } from '../lib/correlation'

const PERIODS: CorrelationPeriod[] = ['3M', '6M', '1A', 'MAX']
const PERIOD_LABELS: Record<CorrelationPeriod, string> = {
  '3M': '3M',
  '6M': '6M',
  '1A': '1A',
  MAX: 'Desde o início',
}

const SEGMENTS: { value: CorrelationSegment; label: string }[] = [
  { value: '', label: 'Todos' },
  { value: 'br', label: 'Brasil' },
  { value: 'us', label: 'EUA' },
  { value: 'crypto', label: 'Cripto' },
]

const TOP_N = 10

export default function Correlacao() {
  const [period, setPeriod] = useState<CorrelationPeriod>('1A')
  const [segment, setSegment] = useState<CorrelationSegment>('')
  const [data, setData] = useState<CorrelationResponse | null>(null)
  const [error, setError] = useState(false)
  const [hovered, setHovered] = useState<HoveredCell | null>(null)
  // Manual asset selection for the main heatmap; resets to "all" on each load.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Market value (BRL) per ticker, summed across positions, for top-N ranking.
  const [weights, setWeights] = useState<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false
    getCorrelation({ period, segment })
      .then((response) => {
        if (cancelled) return
        setData(response)
        setSelected(new Set(response.tickers))
        setError(false)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [period, segment])

  useEffect(() => {
    let cancelled = false
    getPortfolio()
      .then((portfolio) => {
        if (cancelled) return
        const byTicker: Record<string, number> = {}
        for (const position of portfolio.positions) {
          if (position.market_value_brl == null) continue
          byTicker[position.ticker] =
            (byTicker[position.ticker] ?? 0) + Number(position.market_value_brl)
        }
        setWeights(byTicker)
      })
      .catch(() => {
        if (!cancelled) setWeights({})
      })
    return () => {
      cancelled = true
    }
  }, [])

  const loading = data === null && !error
  const tickers = useMemo(() => data?.tickers ?? [], [data])

  const indexOf = useMemo(
    () => new Map(tickers.map((ticker, i) => [ticker, i])),
    [tickers],
  )

  const valueAt = useMemo(() => {
    return (a: string, b: string): number | null => {
      const i = indexOf.get(a)
      const j = indexOf.get(b)
      if (i == null || j == null || !data) return null
      return data.matrix[i][j]
    }
  }, [indexOf, data])

  const selectedTickers = useMemo(
    () => tickers.filter((ticker) => selected.has(ticker)),
    [tickers, selected],
  )

  // Top-N by market value among the matrix tickers; independent of the manual
  // selection above (the spec asks for an automatic, fixed second heatmap).
  const topTickers = useMemo(
    () =>
      [...tickers]
        .sort((a, b) => (weights[b] ?? 0) - (weights[a] ?? 0))
        .slice(0, TOP_N),
    [tickers, weights],
  )

  function toggle(ticker: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(ticker)) next.delete(ticker)
      else next.add(ticker)
      return next
    })
  }

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <div>
        <h2 className="font-display text-lg font-semibold">Correlação dos retornos diários</h2>
        <p className="mt-1 text-sm text-slate-400">
          Coeficiente de Pearson entre os retornos diários dos ativos da carteira, a
          partir das cotações em cache. Verde = movem juntos, vermelho = movem em
          sentido oposto.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1">
          {SEGMENTS.map((option) => (
            <button
              key={option.value || 'all'}
              type="button"
              onClick={() => setSegment(option.value)}
              className={`rounded-md px-3 py-1 text-xs ${
                segment === option.value
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {PERIODS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setPeriod(option)}
              className={`rounded-md px-2 py-1 text-xs ${
                period === option
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {PERIOD_LABELS[option]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-4 text-xs text-slate-400">
        <div className="flex items-center gap-2">
          <span>-1</span>
          <div className="h-2.5 w-32 rounded bg-gradient-to-r from-red-500 via-slate-700 to-green-500" />
          <span>+1</span>
        </div>
        <div className="min-h-4 font-medium text-slate-200">
          {hovered && (
            <span>
              {hovered.a} × {hovered.b}:{' '}
              <span
                className={
                  hovered.value == null
                    ? 'text-slate-500'
                    : hovered.value >= 0
                      ? 'text-green-400'
                      : 'text-red-400'
                }
              >
                {formatCoef(hovered.value)}
              </span>
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          Não foi possível carregar a correlação.
        </div>
      )}
      {!error && loading && (
        <p className="text-sm text-slate-500">Calculando correlações…</p>
      )}
      {!error && !loading && tickers.length < 2 && (
        <p className="text-sm text-slate-500">
          Não há ativos cotados suficientes neste segmento/período para correlacionar.
        </p>
      )}

      {!error && !loading && tickers.length >= 2 && data && (
        <>
          {/* Asset selector */}
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm text-slate-300">
                Ativos comparados{' '}
                <span className="text-xs text-slate-500">
                  ({selectedTickers.length} de {tickers.length})
                </span>
              </p>
              <div className="flex gap-3 text-xs">
                <button
                  type="button"
                  onClick={() => setSelected(new Set(tickers))}
                  className="text-sky-400 hover:underline"
                >
                  Marcar todos
                </button>
                <button
                  type="button"
                  onClick={() => setSelected(new Set())}
                  className="text-sky-400 hover:underline"
                >
                  Limpar
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {tickers.map((ticker) => (
                <label
                  key={ticker}
                  className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-300"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(ticker)}
                    onChange={() => toggle(ticker)}
                    className="h-3.5 w-3.5 accent-sky-500"
                  />
                  {ticker}
                </label>
              ))}
            </div>
          </div>

          {selectedTickers.length >= 2 ? (
            <CorrelationHeatmap
              tickers={selectedTickers}
              valueAt={valueAt}
              showValues
              onHover={setHovered}
            />
          ) : (
            <p className="text-sm text-slate-500">
              Selecione ao menos dois ativos para montar o heatmap.
            </p>
          )}

          {/* Fixed top-N heatmap, by market value, generated automatically. */}
          {topTickers.length >= 2 && (
            <div className="space-y-2 pt-2">
              <div>
                <h3 className="text-base font-semibold">
                  {TOP_N} maiores posições (por valor de mercado)
                </h3>
                <p className="mt-1 text-sm text-slate-400">
                  Correlação automática entre os {TOP_N} ativos de maior peso na carteira,
                  sem depender da seleção acima.
                </p>
              </div>
              <CorrelationHeatmap
                tickers={topTickers}
                valueAt={valueAt}
                showValues
                onHover={setHovered}
              />
            </div>
          )}
        </>
      )}

      {data && data.warnings.length > 0 && (
        <details className="rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-xs text-amber-300">
          <summary className="cursor-pointer font-medium">
            {data.warnings.length} ativo(s) fora da matriz
          </summary>
          <ul className="mt-2 list-inside list-disc space-y-1">
            {data.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </main>
  )
}
