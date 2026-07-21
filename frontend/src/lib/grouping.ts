import type { AssetClass, Indexer, Market } from '../api/client'
import {
  CLASS_COLORS,
  INDEXER_COLORS,
  OTHERS_COLOR,
} from './colors'

export interface GroupDef {
  label: string
  color: string
}

// The subset of Position/SnapshotPosition fields grouping needs — narrow on
// purpose so the same groupOf functions work for live positions AND for
// historical snapshot positions (used by the group sparkline), which don't
// carry every Position field.
export interface Groupable {
  asset_class: AssetClass
  market: Market
  indexer?: Indexer | null
}

// Swatches da lista de posições importam do MESMO mapa central de categoria
// usado pelos donuts — nunca uma cor própria. Cripto na lista = mesmo magenta
// que Cripto no donut, etc.
const UNKNOWN: GroupDef = { label: 'Sem classificação', color: OTHERS_COLOR }

// Dashboard: asset_class + region (market). Stock BR and stock US must not
// share a group, so the region (a real field) splits them.
export function dashboardGroup(p: Groupable): string {
  if (p.asset_class === 'fixed_income') return 'rf'
  if (p.market === 'crypto') return 'crypto'
  if (p.market === 'br' && p.asset_class === 'stock') return 'br_stock'
  if (p.market === 'br' && p.asset_class === 'fii') return 'br_fii'
  if (p.market === 'us' && p.asset_class === 'stock') return 'us_stock'
  if (p.market === 'us' && p.asset_class === 'etf') return 'us_etf'
  return 'unknown'
}

export const DASHBOARD_GROUPS: Record<string, GroupDef> = {
  br_stock: { label: 'Ações', color: CLASS_COLORS.acoes },
  br_fii: { label: 'FIIs', color: CLASS_COLORS.fii },
  us_stock: { label: 'Stocks', color: CLASS_COLORS.stocks },
  us_etf: { label: 'ETF Exterior', color: CLASS_COLORS.etf },
  rf: { label: 'Renda Fixa', color: CLASS_COLORS.rf },
  crypto: { label: 'Cripto', color: CLASS_COLORS.crypto },
  unknown: UNKNOWN,
}

// Brasil page: asset_class only (single region).
export function brasilGroup(p: Groupable): string {
  if (p.asset_class === 'stock') return 'stock'
  if (p.asset_class === 'fii') return 'fii'
  if (p.asset_class === 'etf') return 'etf'
  return 'unknown'
}

export const BRASIL_GROUPS: Record<string, GroupDef> = {
  stock: { label: 'Ações', color: CLASS_COLORS.acoes },
  fii: { label: 'FIIs', color: CLASS_COLORS.fii },
  etf: { label: 'ETFs', color: CLASS_COLORS.etf },
  unknown: UNKNOWN,
}

// EUA page: asset_class (Stocks vs ETFs).
export function euaGroup(p: Groupable): string {
  if (p.asset_class === 'stock') return 'stock'
  if (p.asset_class === 'etf') return 'etf'
  return 'unknown'
}

export const EUA_GROUPS: Record<string, GroupDef> = {
  stock: { label: 'Stocks', color: CLASS_COLORS.stocks },
  etf: { label: 'ETFs', color: CLASS_COLORS.etf },
  unknown: UNKNOWN,
}

// Renda Fixa page: indexer.
export function rfGroup(p: Groupable): string {
  return p.indexer ?? 'unknown'
}

export const RF_GROUPS: Record<string, GroupDef> = {
  ipca: { label: 'IPCA+', color: INDEXER_COLORS.ipca },
  prefixado: { label: 'Pré-Fixado', color: INDEXER_COLORS.prefixado },
  selic: { label: 'SELIC/CDI', color: INDEXER_COLORS.selic },
  unknown: UNKNOWN,
}
