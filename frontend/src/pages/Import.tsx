import { useMemo, useRef, useState } from 'react'
import {
  importFile,
  type ImportResult,
  type ImportSource,
  type ImportWarning,
  type SkippedRow,
} from '../api/client'

interface SourceDef {
  key: ImportSource
  label: string
  description: string
  accept: string
  extensions: string[]
  // Visible warning rendered on the card (real-world export gotchas).
  help?: string
}

const SOURCES: SourceDef[] = [
  {
    key: 'cei',
    label: 'B3',
    description: 'Movimentação (Área do Investidor)',
    accept: '.xlsx',
    extensions: ['.xlsx'],
  },
  {
    key: 'avenue',
    label: 'Avenue',
    description: 'Extrato da conta',
    accept: '.csv',
    extensions: ['.csv'],
  },
  {
    key: 'binance',
    label: 'Binance',
    description: 'Spot Trade/Order History',
    accept: '.xlsx',
    extensions: ['.xlsx'],
  },
  {
    key: 'lending-events',
    label: 'B3 — Empréstimos',
    description: 'Eventos de empréstimo + reembolsos',
    accept: '.xlsx',
    extensions: ['.xlsx'],
    help:
      '⚠ Na B3, o filtro "Empréstimos" NÃO retorna as linhas de Empréstimo: ' +
      'exporte com o filtro "Outros" (eventos) e "Reembolso e Empréstimos" ' +
      '(renda). Reimportar não duplica; exports mais novos estendem a linha ' +
      'do tempo.',
  },
]

function hasValidExtension(file: File, source: SourceDef): boolean {
  const name = file.name.toLowerCase()
  return source.extensions.some((ext) => name.endsWith(ext))
}

function groupSkipped(skipped: SkippedRow[]): { reason: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const row of skipped) {
    counts.set(row.reason, (counts.get(row.reason) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count)
}

interface WarningGroup {
  ticker: string
  items: ImportWarning[]
}

// Reconciliation warnings come in bursts of near-identical lines per lent
// ticker; grouping by ticker keeps the block scannable (which tickers to
// check) while every backend message stays available verbatim on expand.
function groupWarnings(warnings: ImportWarning[]): WarningGroup[] {
  const groups = new Map<string, ImportWarning[]>()
  for (const warning of warnings) {
    const items = groups.get(warning.ticker) ?? []
    items.push(warning)
    groups.set(warning.ticker, items)
  }
  return [...groups.entries()]
    .map(([ticker, items]) => ({ ticker, items }))
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
}

// With this few warnings everything fits on screen: start every group open.
const EXPAND_ALL_THRESHOLD = 5

interface Props {
  onGoToDashboard: () => void
}

export default function Import({ onGoToDashboard }: Props) {
  const [sourceKey, setSourceKey] = useState<ImportSource>('cei')
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  // The reconciliation block stays on screen until explicitly closed (no
  // auto-dismiss): it is the only trigger for the manual qty/PM check.
  const [warningsDismissed, setWarningsDismissed] = useState(false)
  const [expandedTickers, setExpandedTickers] = useState<Set<string>>(new Set())
  const inputRef = useRef<HTMLInputElement>(null)

  const source = SOURCES.find((s) => s.key === sourceKey)!
  const skippedGroups = useMemo(
    () => (result ? groupSkipped(result.skipped) : []),
    [result],
  )
  const warningGroups = useMemo(
    () => (result ? groupWarnings(result.warnings) : []),
    [result],
  )

  function toggleTicker(ticker: string) {
    setExpandedTickers((current) => {
      const next = new Set(current)
      if (next.has(ticker)) {
        next.delete(ticker)
      } else {
        next.add(ticker)
      }
      return next
    })
  }

  function chooseSource(key: ImportSource) {
    setSourceKey(key)
    // A file picked for another source may have the wrong extension.
    setFile(null)
    setResult(null)
    setStatus('idle')
    setError(null)
  }

  function acceptFile(picked: File | null) {
    if (!picked) return
    if (!hasValidExtension(picked, source)) {
      setFile(null)
      setError(`${source.label} espera um arquivo ${source.accept}.`)
      setStatus('error')
      return
    }
    setFile(picked)
    setError(null)
    setStatus('idle')
    setResult(null)
  }

  function onDrop(event: React.DragEvent) {
    event.preventDefault()
    setDragOver(false)
    acceptFile(event.dataTransfer.files[0] ?? null)
  }

  async function submit() {
    if (!file) return
    setStatus('loading')
    setError(null)
    try {
      const imported = await importFile(sourceKey, file)
      setResult(imported)
      setWarningsDismissed(false)
      setExpandedTickers(
        imported.warnings.length <= EXPAND_ALL_THRESHOLD
          ? new Set(imported.warnings.map((w) => w.ticker))
          : new Set(),
      )
      setStatus('done')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Falha ao importar.')
      setStatus('error')
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h2 className="font-display text-lg font-semibold">Importar transações</h2>
        <p className="mt-1 text-sm text-slate-400">
          Escolha a fonte e envie o arquivo exportado. Reimportar o mesmo arquivo
          não duplica nada.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {SOURCES.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => chooseSource(option.key)}
            className={`rounded-xl border p-4 text-left transition-colors ${
              sourceKey === option.key
                ? 'border-sky-500 bg-sky-500/10'
                : 'border-slate-800 bg-slate-900 hover:border-slate-600'
            }`}
          >
            <span className="block text-sm font-medium">{option.label}</span>
            <span className="mt-0.5 block text-xs text-slate-400">
              {option.description}
            </span>
            <span className="mt-1 block text-xs text-slate-600">{option.accept}</span>
          </button>
        ))}
      </div>

      {source.help && (
        <div className="rounded-xl border border-amber-700 bg-amber-950/40 p-3 text-xs text-amber-200">
          {source.help}
        </div>
      )}

      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
          dragOver ? 'border-sky-500 bg-sky-500/5' : 'border-slate-700 bg-slate-900/50'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={source.accept}
          className="hidden"
          onChange={(event) => acceptFile(event.target.files?.[0] ?? null)}
        />
        {file ? (
          <div className="space-y-1">
            <p className="text-sm text-slate-200">{file.name}</p>
            <p className="text-xs text-slate-500">{(file.size / 1024).toFixed(0)} KB</p>
            <button
              type="button"
              onClick={() => {
                setFile(null)
                setResult(null)
                setStatus('idle')
              }}
              className="text-xs text-sky-400 hover:underline"
            >
              Trocar arquivo
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm text-slate-400">
              Arraste o arquivo {source.accept} de {source.label} aqui
            </p>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
            >
              Selecionar arquivo
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={!file || status === 'loading'}
          className="rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-inkbrass hover:bg-sky-500 disabled:opacity-50"
        >
          {status === 'loading' ? 'Importando…' : 'Importar'}
        </button>
      </div>

      {result && (
        <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="grid grid-cols-4 gap-4 text-center">
            <div>
              <p className="text-2xl font-semibold tabular-nums text-green-400">
                {result.imported}
              </p>
              <p className="text-xs text-slate-400">importadas</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-slate-300">
                {result.duplicates}
              </p>
              <p className="text-xs text-slate-400">duplicatas (ignoradas)</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-amber-400">
                {result.skipped.length}
              </p>
              <p className="text-xs text-slate-400">puladas</p>
            </div>
            <div>
              <p
                className={`text-2xl font-semibold tabular-nums ${
                  result.warnings.length > 0 ? 'text-amber-400' : 'text-slate-500'
                }`}
              >
                {result.warnings.length}
              </p>
              <p className="text-xs text-slate-400">avisos</p>
            </div>
          </div>

          {result.events_added != null && (
            <p className="border-t border-slate-800 pt-3 text-center text-sm text-slate-300">
              eventos de empréstimo:{' '}
              <span className="font-semibold text-green-400 tabular-nums">
                {result.events_added} novos
              </span>
              {' · '}
              <span className="tabular-nums text-slate-400">
                {result.events_known ?? 0} já conhecidos
              </span>
            </p>
          )}

          {result.warnings.length > 0 && !warningsDismissed && (
            <div className="rounded-xl border border-amber-700 bg-amber-950/40 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-amber-300">
                    ⚠ {result.warnings.length}{' '}
                    {result.warnings.length === 1 ? 'linha' : 'linhas'} para
                    reconciliação manual
                  </p>
                  <p className="mt-1 text-xs text-amber-200/80">
                    O parser manteve estas linhas como compra/venda, mas elas
                    podem ser pernas de empréstimo de ativos. Confira a
                    quantidade e o preço médio dos tickers abaixo após o
                    import.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setWarningsDismissed(true)}
                  className="shrink-0 rounded-lg border border-amber-700 px-3 py-1 text-xs text-amber-300 hover:bg-amber-900/40"
                >
                  Fechar
                </button>
              </div>
              <ul className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
                {warningGroups.map((group) => {
                  const expanded = expandedTickers.has(group.ticker)
                  return (
                    <li key={group.ticker}>
                      <button
                        type="button"
                        onClick={() => toggleTicker(group.ticker)}
                        className="flex w-full items-baseline justify-between gap-3 text-left"
                      >
                        <span className="text-sm font-medium text-amber-200">
                          {expanded ? '▾' : '▸'} {group.ticker}
                        </span>
                        <span className="text-xs tabular-nums text-amber-400/80">
                          {group.items.length}{' '}
                          {group.items.length === 1 ? 'linha' : 'linhas'}
                        </span>
                      </button>
                      {expanded ? (
                        <ul className="mt-1 space-y-1 pl-4">
                          {group.items.map((warning) => (
                            <li
                              key={warning.row}
                              className="text-xs text-amber-200/90"
                            >
                              <span className="text-amber-500/70">
                                linha {warning.row} —{' '}
                              </span>
                              {warning.message}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="truncate pl-4 text-xs text-amber-200/50">
                          {group.items[0].message}
                        </p>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {skippedGroups.length > 0 && (
            <div className="border-t border-slate-800 pt-3">
              <p className="mb-2 text-xs font-medium text-slate-400">
                Motivos das linhas puladas
              </p>
              <ul className="space-y-1 text-xs text-slate-400">
                {skippedGroups.map((group) => (
                  <li key={group.reason} className="flex justify-between gap-4">
                    <span>{group.reason}</span>
                    <span className="tabular-nums text-slate-500">{group.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center gap-3 border-t border-slate-800 pt-3">
            <button
              type="button"
              onClick={onGoToDashboard}
              className="rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-inkbrass hover:bg-sky-500"
            >
              Ver carteira atualizada →
            </button>
            <p className="text-xs text-slate-500">
              O dashboard recalcula as posições automaticamente.
            </p>
          </div>
        </div>
      )}
    </main>
  )
}
