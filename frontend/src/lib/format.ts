import type { AssetClass, Custody, Indexer, Market, Operation, Source } from '../api/client'

const formatters = new Map<string, Intl.NumberFormat>()

function currencyFormatter(currency: string): Intl.NumberFormat {
  let formatter = formatters.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat('pt-BR', { style: 'currency', currency })
    formatters.set(currency, formatter)
  }
  return formatter
}

const quantityFormatter = new Intl.NumberFormat('pt-BR', {
  maximumFractionDigits: 8,
})

const percentFormatter = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const signedPercentFormatter = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

export function formatMoney(
  value: string | null | undefined,
  currency: string = 'BRL',
): string {
  if (value == null) return '—'
  return currencyFormatter(currency).format(Number(value))
}

export function formatQuantity(value: string): string {
  return quantityFormatter.format(Number(value))
}

export function formatPercent(ratio: number): string {
  return percentFormatter.format(ratio)
}

export function formatSignedPercent(ratio: number): string {
  return signedPercentFormatter.format(ratio)
}

export const MARKET_LABELS: Record<Market, string> = {
  br: 'Nacional',
  us: 'Internacional',
  crypto: 'Cripto',
}

// "XP INVESTIMENTOS CCTVM S/A" -> "Xp Investimentos"; corporate suffixes
// add noise in chart legends.
export function prettifyInstitution(raw: string | null): string {
  if (!raw) return 'Sem corretora'
  const cleaned = raw
    .replace(
      /\s+(CCTVM|DTVM|CTVM|DISTRIBUIDORA DE TITULOS E VALORES MOBILIARIOS|S\/A|S\.A\.?|LTDA)\.?\b/gi,
      '',
    )
    .trim()
  return cleaned
    .toLowerCase()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  stock: 'Ações',
  fii: 'FIIs',
  etf: 'ETFs',
  fixed_income: 'Renda fixa',
  crypto: 'Cripto',
}

export const OPERATION_LABELS: Record<Operation, string> = {
  buy: 'Compra',
  sell: 'Venda',
  dividend: 'Dividendo',
  jcp: 'JCP',
  yield: 'Rendimento',
  transfer: 'Transferência',
  split: 'Desdobramento',
  bonus: 'Bonificação',
  custody_transfer: 'Transf. custódia',
}

export const CUSTODY_LABELS: Record<Custody, string> = {
  binance: 'Binance (hot)',
  cold_wallet: 'Cold Wallet',
}

// Short tag for tight spaces (table badges, donut legends).
export const CUSTODY_SHORT_LABELS: Record<Custody, string> = {
  binance: 'Hot',
  cold_wallet: 'Cold',
}

export const INDEXER_LABELS: Record<Indexer, string> = {
  ipca: 'IPCA',
  prefixado: 'Prefixado',
  selic: 'Selic/CDI',
}

export const SOURCE_LABELS: Record<Source, string> = {
  cei: 'B3',
  avenue: 'Avenue',
  binance: 'Binance',
  manual: 'Manual',
}

const dateFormatter = new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC' })

export function formatDate(iso: string): string {
  return dateFormatter.format(new Date(`${iso}T12:00:00Z`))
}
