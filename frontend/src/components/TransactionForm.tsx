import { useState } from 'react'
import type {
  AssetClass,
  Custody,
  Indexer,
  Market,
  Operation,
  Transaction,
  TransactionInput,
} from '../api/client'
import {
  ASSET_CLASS_LABELS,
  CUSTODY_LABELS,
  INDEXER_LABELS,
  MARKET_LABELS,
  OPERATION_LABELS,
} from '../lib/format'

interface Props {
  initial: Transaction | null
  onSubmit: (input: TransactionInput) => Promise<void>
  onCancel: () => void
}

const inputClass =
  'w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm ' +
  'text-slate-200 placeholder:text-slate-600 focus:border-sky-600 focus:outline-none'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-400">{label}</span>
      {children}
    </label>
  )
}

type Mode = 'transaction' | 'custody_transfer'

export default function TransactionForm({ initial, onSubmit, onCancel }: Props) {
  const [mode, setMode] = useState<Mode>(
    initial?.operation === 'custody_transfer' ? 'custody_transfer' : 'transaction',
  )
  const [form, setForm] = useState<TransactionInput>({
    date: initial?.date ?? new Date().toISOString().slice(0, 10),
    ticker: initial?.ticker ?? '',
    asset_name: initial?.asset_name ?? '',
    asset_class: initial?.asset_class ?? 'stock',
    market: initial?.market ?? 'br',
    institution: initial?.institution ?? '',
    custody: initial?.custody ?? null,
    custody_from: initial?.custody_from ?? 'binance',
    custody_to: initial?.custody_to ?? 'cold_wallet',
    indexer: initial?.indexer ?? null,
    currency: initial?.currency ?? 'BRL',
    operation: initial?.operation ?? 'buy',
    quantity: initial?.quantity ?? '',
    unit_price: initial?.unit_price ?? '0',
    fees: initial?.fees ?? '0',
    notes: initial?.notes ?? '',
  })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  function set<K extends keyof TransactionInput>(key: K, value: TransactionInput[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      if (mode === 'custody_transfer') {
        await onSubmit({
          date: form.date,
          ticker: form.ticker,
          asset_class: 'crypto',
          market: 'crypto',
          operation: 'custody_transfer',
          quantity: form.quantity,
          unit_price: '0',
          fees: '0',
          currency: 'BRL',
          custody_from: form.custody_from ?? null,
          custody_to: form.custody_to ?? null,
          notes: form.notes || null,
        })
      } else {
        await onSubmit({
          ...form,
          asset_name: form.asset_name || null,
          institution: form.institution || null,
          // Custody only applies to crypto; drop it otherwise.
          custody: form.asset_class === 'crypto' ? form.custody ?? null : null,
          custody_from: null,
          custody_to: null,
          // Indexer only applies to fixed income.
          indexer: form.asset_class === 'fixed_income' ? form.indexer ?? null : null,
          notes: form.notes || null,
        })
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Erro ao salvar.')
      setSaving(false)
    }
  }

  const toggle = (
    <div className="flex gap-1 rounded-lg border border-slate-700 bg-slate-950 p-1 text-xs">
      {(
        [
          ['transaction', 'Transação'],
          ['custody_transfer', 'Transferência de custódia'],
        ] as [Mode, string][]
      ).map(([value, label]) => (
        <button
          key={value}
          type="button"
          onClick={() => setMode(value)}
          className={`rounded-md px-3 py-1 font-medium ${
            mode === value
              ? 'bg-sky-600 text-slate-950'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )

  if (mode === 'custody_transfer') {
    return (
      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-sky-900/60 bg-slate-900 p-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-medium text-slate-300">
            {initial ? `Editar transferência ${initial.ticker}` : 'Transferência de custódia'}
          </p>
          {!initial && toggle}
        </div>
        <p className="text-xs text-slate-500">
          Move quantidade entre custódias pelo preço médio atual da origem. Não é
          compra nem venda e não gera P&amp;L; o preço médio consolidado não muda.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Data">
            <input
              type="date"
              required
              value={form.date}
              onChange={(e) => set('date', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Ativo (cripto)">
            <input
              required
              value={form.ticker}
              onChange={(e) => set('ticker', e.target.value.toUpperCase())}
              placeholder="BTC"
              className={inputClass}
            />
          </Field>
          <Field label="Quantidade">
            <input
              required
              inputMode="decimal"
              value={form.quantity}
              onChange={(e) => set('quantity', e.target.value)}
              placeholder="0.3"
              className={inputClass}
            />
          </Field>
          <Field label="Custódia origem">
            <select
              value={form.custody_from ?? ''}
              onChange={(e) => set('custody_from', (e.target.value || null) as Custody | null)}
              className={inputClass}
            >
              {Object.entries(CUSTODY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Custódia destino">
            <select
              value={form.custody_to ?? ''}
              onChange={(e) => set('custody_to', (e.target.value || null) as Custody | null)}
              className={inputClass}
            >
              {Object.entries(CUSTODY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Notas (opcional)">
            <input
              value={form.notes ?? ''}
              onChange={(e) => set('notes', e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-slate-950 hover:bg-sky-500 disabled:opacity-50"
          >
            {saving ? 'Salvando…' : 'Salvar'}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-700 px-4 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            Cancelar
          </button>
        </div>
      </form>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded-xl border border-sky-900/60 bg-slate-900 p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-300">
          {initial ? `Editar transação ${initial.ticker}` : 'Nova transação manual'}
        </p>
        {!initial && toggle}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Fonte">
          <div
            className={`${inputClass} cursor-not-allowed text-slate-400`}
            title="Lançamentos criados aqui são sempre manuais; transações importadas vêm dos arquivos."
          >
            Manual
          </div>
        </Field>
        <Field label="Data">
          <input
            type="date"
            required
            value={form.date}
            onChange={(e) => set('date', e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Ticker">
          <input
            required
            value={form.ticker}
            onChange={(e) => set('ticker', e.target.value.toUpperCase())}
            placeholder="PETR4"
            className={inputClass}
          />
        </Field>
        <Field label="Operação">
          <select
            value={form.operation}
            onChange={(e) => set('operation', e.target.value as Operation)}
            className={inputClass}
          >
            {Object.entries(OPERATION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Classe">
          <select
            value={form.asset_class}
            onChange={(e) => set('asset_class', e.target.value as AssetClass)}
            className={inputClass}
          >
            {Object.entries(ASSET_CLASS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Mercado">
          <select
            value={form.market}
            onChange={(e) => set('market', e.target.value as Market)}
            className={inputClass}
          >
            {Object.entries(MARKET_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Quantidade">
          <input
            required
            inputMode="decimal"
            value={form.quantity}
            onChange={(e) => set('quantity', e.target.value)}
            placeholder="100 (negativa p/ transferência de saída)"
            className={inputClass}
          />
        </Field>
        <Field label="Preço unitário">
          <input
            inputMode="decimal"
            value={form.unit_price}
            onChange={(e) => set('unit_price', e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Taxas">
          <input
            inputMode="decimal"
            value={form.fees}
            onChange={(e) => set('fees', e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Moeda">
          <input
            value={form.currency}
            onChange={(e) => set('currency', e.target.value.toUpperCase())}
            className={inputClass}
          />
        </Field>
        <Field label="Corretora (opcional)">
          <input
            value={form.institution ?? ''}
            onChange={(e) => set('institution', e.target.value)}
            className={inputClass}
          />
        </Field>
        {form.asset_class === 'crypto' && (
          <Field label="Custódia (cripto)">
            <select
              value={form.custody ?? ''}
              onChange={(e) => set('custody', (e.target.value || null) as Custody | null)}
              className={inputClass}
            >
              <option value="">— não informada</option>
              {Object.entries(CUSTODY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        )}
        {form.asset_class === 'fixed_income' && (
          <Field label="Indexador (renda fixa)">
            <select
              value={form.indexer ?? ''}
              onChange={(e) => set('indexer', (e.target.value || null) as Indexer | null)}
              className={inputClass}
            >
              <option value="">— derivar do nome</option>
              {Object.entries(INDEXER_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Nome do ativo (opcional)">
          <input
            value={form.asset_name ?? ''}
            onChange={(e) => set('asset_name', e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Notas (opcional)">
          <input
            value={form.notes ?? ''}
            onChange={(e) => set('notes', e.target.value)}
            className={inputClass}
          />
        </Field>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-slate-950 hover:bg-sky-500 disabled:opacity-50"
        >
          {saving ? 'Salvando…' : 'Salvar'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-slate-700 px-4 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
        >
          Cancelar
        </button>
      </div>
    </form>
  )
}
