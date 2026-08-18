import { STATIC_DEMO } from '../api/staticDemo'
import { useCallback, useEffect, useState } from 'react'
import {
  createTransaction,
  deleteTransaction,
  getTransactions,
  updateTransaction,
  type Operation,
  type Source,
  type Transaction,
  type TransactionInput,
  type TransactionQuery,
} from '../api/client'
import TransactionForm from '../components/TransactionForm'
import {
  CUSTODY_LABELS,
  CUSTODY_SHORT_LABELS,
  OPERATION_LABELS,
  SOURCE_LABELS,
  formatDate,
  formatMoney,
  formatQuantity,
} from '../lib/format'

const PAGE_SIZE = 50

type SortField = NonNullable<TransactionQuery['sort']>

const SOURCE_OPTIONS: Source[] = ['cei', 'avenue', 'binance', 'manual']

const inputClass =
  'rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-200 ' +
  'placeholder:text-slate-600 focus:border-sky-600 focus:outline-none'

const COLUMNS: { key: SortField; label: string; numeric: boolean }[] = [
  { key: 'date', label: 'Data', numeric: false },
  { key: 'ticker', label: 'Ativo', numeric: false },
  { key: 'operation', label: 'Tipo', numeric: false },
  { key: 'total_value', label: 'Total', numeric: true },
  { key: 'source', label: 'Fonte', numeric: false },
]

export default function Lancamentos() {
  const [items, setItems] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [ticker, setTicker] = useState('')
  const [source, setSource] = useState<Source | ''>('')
  const [operation, setOperation] = useState<Operation | ''>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sort, setSort] = useState<SortField>('date')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [editing, setEditing] = useState<Transaction | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    getTransactions({
      ticker: ticker || undefined,
      source: source || undefined,
      operation: operation || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      sort,
      order,
      limit: PAGE_SIZE,
      offset,
    })
      .then((data) => {
        setItems(data.items)
        setTotal(data.total)
        setError(null)
      })
      .catch(() => setError('Não foi possível carregar os lançamentos.'))
  }, [ticker, source, operation, dateFrom, dateTo, sort, order, offset])

  useEffect(() => {
    load()
  }, [load])

  // Filter changes reset to the first page.
  function onFilterChange<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value)
      setOffset(0)
    }
  }

  function toggleSort(field: SortField) {
    if (field === sort) {
      setOrder(order === 'asc' ? 'desc' : 'asc')
    } else {
      setSort(field)
      setOrder('desc')
    }
    setOffset(0)
  }

  async function handleSubmit(input: TransactionInput) {
    if (editing === 'new') {
      await createTransaction(input)
    } else if (editing) {
      await updateTransaction(editing.id, input)
    }
    setEditing(null)
    load()
  }

  async function handleDelete(transaction: Transaction) {
    if (!window.confirm(`Excluir o lançamento manual de ${transaction.ticker}?`)) {
      return
    }
    try {
      await deleteTransaction(transaction.id)
      load()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Erro ao excluir.')
    }
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Ativo</span>
            <input
              type="search"
              value={ticker}
              onChange={(e) => onFilterChange(setTicker)(e.target.value)}
              placeholder="ticker…"
              className={`w-32 ${inputClass}`}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Fonte</span>
            <select
              value={source}
              onChange={(e) => onFilterChange(setSource)(e.target.value as Source | '')}
              className={inputClass}
            >
              <option value="">Todas</option>
              {SOURCE_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Tipo</span>
            <select
              value={operation}
              onChange={(e) =>
                onFilterChange(setOperation)(e.target.value as Operation | '')
              }
              className={inputClass}
            >
              <option value="">Todos</option>
              {Object.entries(OPERATION_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">De</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => onFilterChange(setDateFrom)(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">Até</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => onFilterChange(setDateTo)(e.target.value)}
              className={inputClass}
            />
          </label>
        </div>
        {/* Nothing to write to in the frozen showcase. */}
        {!STATIC_DEMO && (
          <button
            type="button"
            onClick={() => setEditing('new')}
            className="rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-inkbrass hover:bg-sky-500"
          >
            Novo lançamento
          </button>
        )}
      </div>

      {editing !== null && (
        <TransactionForm
          initial={editing === 'new' ? null : editing}
          onSubmit={handleSubmit}
          onCancel={() => setEditing(null)}
        />
      )}

      {error && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs uppercase tracking-wide text-slate-400">
              {COLUMNS.map((column) => (
                <th key={column.key} className={column.numeric ? 'text-right' : ''}>
                  <button
                    type="button"
                    onClick={() => toggleSort(column.key)}
                    className={`px-4 py-3 font-medium hover:text-slate-200 ${
                      column.numeric ? 'w-full text-right' : 'text-left'
                    }`}
                  >
                    {column.label}
                    {sort === column.key && (order === 'asc' ? ' ▲' : ' ▼')}
                  </button>
                </th>
              ))}
              <th className="px-4 py-3 text-right">Quantidade</th>
              <th className="px-4 py-3 text-right">Preço</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {items.map((tx) => (
              <tr
                key={tx.id}
                className="border-b border-slate-800/60 last:border-b-0 hover:bg-slate-800/40"
              >
                <td className="px-4 py-2 tabular-nums">{formatDate(tx.date)}</td>
                <td className="px-4 py-2 font-medium">
                  {tx.ticker}
                  {tx.custody && (
                    <span
                      title={CUSTODY_LABELS[tx.custody]}
                      className={`ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                        tx.custody === 'cold_wallet'
                          ? 'bg-sky-500/15 text-sky-300'
                          : 'bg-amber-500/15 text-amber-300'
                      }`}
                    >
                      {CUSTODY_SHORT_LABELS[tx.custody]}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-300">
                  {OPERATION_LABELS[tx.operation]}
                  {tx.operation === 'custody_transfer' &&
                    tx.custody_from &&
                    tx.custody_to && (
                      <span className="ml-1 text-xs text-slate-500">
                        {CUSTODY_SHORT_LABELS[tx.custody_from]}→
                        {CUSTODY_SHORT_LABELS[tx.custody_to]}
                      </span>
                    )}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {formatMoney(tx.total_value, tx.currency)}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs ${
                      tx.source === 'manual'
                        ? 'bg-sky-900/60 text-sky-300'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    {SOURCE_LABELS[tx.source]}
                  </span>
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {formatQuantity(tx.quantity)}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {formatMoney(tx.unit_price, tx.currency)}
                </td>
                <td className="px-4 py-2 text-right">
                  {tx.source === 'manual' && !STATIC_DEMO ? (
                    <span className="flex justify-end gap-2 text-xs">
                      <button
                        type="button"
                        onClick={() => setEditing(tx)}
                        className="text-sky-400 hover:underline"
                      >
                        Editar
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(tx)}
                        className="text-red-400 hover:underline"
                      >
                        Excluir
                      </button>
                    </span>
                  ) : (
                    <span
                      className="text-xs text-slate-600"
                      title="Linha importada: somente leitura. Para corrigir, crie um lançamento manual de ajuste."
                    >
                      somente leitura
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-slate-500">
                  Nenhum lançamento encontrado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-slate-400">
        <p>
          {total} lançamentos · importados são somente leitura; correções viram um
          lançamento manual de ajuste
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded-lg border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-40"
          >
            Anterior
          </button>
          <span className="tabular-nums">
            {page} / {pages}
          </span>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded-lg border border-slate-700 px-3 py-1 hover:bg-slate-800 disabled:opacity-40"
          >
            Próxima
          </button>
        </div>
      </div>
    </main>
  )
}
