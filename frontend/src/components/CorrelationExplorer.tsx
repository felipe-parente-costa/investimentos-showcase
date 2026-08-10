import { useEffect, useMemo, useState } from 'react'
import {
  getCorrelation,
  type CorrelationPeriod,
  type CorrelationResponse,
  type CorrelationSegment,
  type GroupCorrelation,
  type RiskGroupBy,
} from '../api/client'
import CorrelationHeatmap from './CorrelationHeatmap'
import CorrelationLegend from './CorrelationLegend'
import type { HoveredCell } from '../lib/correlation'

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

function FilterChips({
  items,
  selected,
  onToggle,
  onSelectAll,
  onClear,
}: {
  items: string[]
  selected: Set<string>
  onToggle: (item: string) => void
  onSelectAll: () => void
  onClear: () => void
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm text-slate-300">
          Comparados <span className="text-xs text-slate-500">({selected.size} de {items.length})</span>
        </p>
        <div className="flex gap-3 text-xs">
          <button type="button" onClick={onSelectAll} className="text-sky-400 hover:underline">
            Marcar todos
          </button>
          <button type="button" onClick={onClear} className="text-sky-400 hover:underline">
            Limpar
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {items.map((item) => (
          <label key={item} className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={selected.has(item)}
              onChange={() => onToggle(item)}
              className="h-3.5 w-3.5 accent-sky-500"
            />
            {item}
          </label>
        ))}
      </div>
    </div>
  )
}

interface Props {
  groupCorrelation: GroupCorrelation | null
  groupBy: RiskGroupBy
}

// Two independently filterable heatmaps: individual assets (this component's
// original scope, back when the page was just "Correlação") and sector/
// sub-setor groups (reusing the same data RiskGroupsSection's compact
// top-10-vs-groups pair uses, just with full manual control here instead of
// a fixed auto view).
export default function CorrelationExplorer({ groupCorrelation, groupBy }: Props) {
  const [period, setPeriod] = useState<CorrelationPeriod>('1A')
  const [segment, setSegment] = useState<CorrelationSegment>('')
  const [data, setData] = useState<CorrelationResponse | null>(null)
  const [error, setError] = useState(false)
  const [assetHovered, setAssetHovered] = useState<HoveredCell | null>(null)
  const [selectedAssets, setSelectedAssets] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    getCorrelation({ period, segment })
      .then((response) => {
        if (cancelled) return
        setData(response)
        setSelectedAssets(new Set(response.tickers))
        setError(false)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [period, segment])

  const loading = data === null && !error
  const tickers = useMemo(() => data?.tickers ?? [], [data])

  const assetValueAt = useMemo(() => {
    const index = new Map(tickers.map((ticker, i) => [ticker, i]))
    return (a: string, b: string): number | null => {
      const i = index.get(a)
      const j = index.get(b)
      if (i == null || j == null || !data) return null
      return data.matrix[i][j]
    }
  }, [tickers, data])

  const selectedTickers = useMemo(
    () => tickers.filter((ticker) => selectedAssets.has(ticker)),
    [tickers, selectedAssets],
  )

  function toggleAsset(ticker: string) {
    setSelectedAssets((current) => {
      const next = new Set(current)
      if (next.has(ticker)) next.delete(ticker)
      else next.add(ticker)
      return next
    })
  }

  // Groups: same reset-on-data-change pattern as assets above, keyed off
  // the group labels identity (changes when groupBy or the risk period
  // upstream changes).
  const groupLabels = useMemo(() => groupCorrelation?.labels ?? [], [groupCorrelation])
  const [groupHovered, setGroupHovered] = useState<HoveredCell | null>(null)
  // Lazy initializer: selected starts as *all* of the current groupLabels,
  // not empty — a plain useState(new Set()) would need a follow-up effect
  // just to populate the very first render, which is what the render-time
  // reset below already replaces for every *later* change.
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(
    () => new Set(groupLabels),
  )
  // Reset the selection during render when the label set changes identity
  // (new groupCorrelation fetch) — adjusting state while rendering, not in
  // an effect, per https://react.dev/learn/you-might-not-need-an-effect.
  const [seenGroupLabels, setSeenGroupLabels] = useState(groupLabels)
  if (groupLabels !== seenGroupLabels) {
    setSeenGroupLabels(groupLabels)
    setSelectedGroups(new Set(groupLabels))
  }

  const groupValueAt = useMemo(() => {
    const index = new Map(groupLabels.map((label, i) => [label, i]))
    return (a: string, b: string): number | null => {
      const i = index.get(a)
      const j = index.get(b)
      if (i == null || j == null || !groupCorrelation) return null
      return groupCorrelation.matrix[i][j]
    }
  }, [groupLabels, groupCorrelation])

  const selectedGroupLabels = useMemo(
    () => groupLabels.filter((label) => selectedGroups.has(label)),
    [groupLabels, selectedGroups],
  )

  function toggleGroup(label: string) {
    setSelectedGroups((current) => {
      const next = new Set(current)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  return (
    <div className="space-y-8 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-section">Correlação entre ativos</p>
            <p className="text-xs text-slate-500">
              Coeficiente de Pearson entre os retornos diários dos ativos da carteira. Verde =
              movem juntos, vermelho = movem em sentido oposto.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
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
        </div>

        <CorrelationLegend hovered={assetHovered} />

        {error && (
          <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
            Não foi possível carregar a correlação.
          </div>
        )}
        {!error && loading && <p className="text-sm text-slate-500">Calculando correlações…</p>}
        {!error && !loading && tickers.length < 2 && (
          <p className="text-sm text-slate-500">
            Não há ativos cotados suficientes neste segmento/período para correlacionar.
          </p>
        )}
        {!error && !loading && tickers.length >= 2 && (
          <>
            <FilterChips
              items={tickers}
              selected={selectedAssets}
              onToggle={toggleAsset}
              onSelectAll={() => setSelectedAssets(new Set(tickers))}
              onClear={() => setSelectedAssets(new Set())}
            />
            {selectedTickers.length >= 2 ? (
              <CorrelationHeatmap
                tickers={selectedTickers}
                valueAt={assetValueAt}
                showValues
                onHover={setAssetHovered}
              />
            ) : (
              <p className="text-sm text-slate-500">Selecione ao menos dois ativos para montar o heatmap.</p>
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
      </section>

      <section className="space-y-4 border-t border-slate-800 pt-6">
        <div>
          <p className="text-section">
            Correlação entre {groupBy === 'sector' ? 'setores' : 'sub-setores'}
          </p>
          <p className="text-xs text-slate-500">
            Mesma cesta ponderada por valor do card "Risco por {groupBy === 'sector' ? 'setor' : 'sub-setor'}"
            acima, com seleção manual — troque para sub-setor no card acima para ver essa granularidade aqui também.
          </p>
        </div>

        <CorrelationLegend hovered={groupHovered} />

        {groupLabels.length < 2 && (
          <p className="text-sm text-slate-500">
            Grupos insuficientes com série de preços para correlacionar.
          </p>
        )}
        {groupLabels.length >= 2 && (
          <>
            <FilterChips
              items={groupLabels}
              selected={selectedGroups}
              onToggle={toggleGroup}
              onSelectAll={() => setSelectedGroups(new Set(groupLabels))}
              onClear={() => setSelectedGroups(new Set())}
            />
            {selectedGroupLabels.length >= 2 ? (
              <CorrelationHeatmap
                tickers={selectedGroupLabels}
                valueAt={groupValueAt}
                showValues
                onHover={setGroupHovered}
              />
            ) : (
              <p className="text-sm text-slate-500">
                Selecione ao menos dois grupos para montar o heatmap.
              </p>
            )}
          </>
        )}
      </section>
    </div>
  )
}
