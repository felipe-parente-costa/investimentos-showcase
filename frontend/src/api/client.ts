const BASE_URL = '/api'

export interface HealthResponse {
  status: string
  database: string
}

export type AssetClass = 'stock' | 'fii' | 'etf' | 'fixed_income' | 'crypto'
export type Market = 'br' | 'us' | 'crypto'
// Crypto custody: hot exchange wallet vs cold self-custody. Null for non-crypto.
export type Custody = 'binance' | 'cold_wallet'
// Fixed-income indexer; selic covers Selic/CDI post-fixed. Null for non-FI.
export type Indexer = 'ipca' | 'prefixado' | 'selic'

// Money fields arrive as strings (Decimal on the backend, never float).
export interface Position {
  ticker: string
  asset_name: string | null
  asset_class: AssetClass
  market: Market
  institution: string | null
  custody: Custody | null
  indexer: Indexer | null
  sector: string | null
  country: string | null
  currency: string
  quantity: string
  average_price: string
  total_cost: string
  realized_pnl: string
  income: string
  priced: boolean
  quote_price: string | null
  quote_currency: string | null
  quote_date: string | null
  quote_fetched_at: string | null
  quote_stale: boolean
  market_value: string | null
  market_value_brl: string | null
  unrealized_pnl: string | null
  day_change_brl: string | null
  day_change_pct: string | null
  // Trailing-12m income (native currency) and the DY it implies over the
  // current market value; dy is null for fixed income and unpriced positions.
  income_12m: string
  dy_12m_pct: string | null
  // USD view (EUA/Cripto): null for BRL sections.
  usd_average_price: string | null
  usd_total_cost: string | null
  usd_market_value: string | null
  usd_unrealized_pnl: string | null
}

export interface Segment {
  market: Market
  total_brl: string
  position_count: number
}

export interface SegmentSummary {
  key: string
  label: string
  total_brl: string
  cost_brl: string
  unrealized_pnl_brl: string
  pnl_pct: string | null
  weight_pct: string | null
  position_count: number
  display_currency: string
  usd_total: string | null
  usd_cost: string | null
  usd_unrealized_pnl: string | null
  usd_pnl_pct: string | null
}

export interface PortfolioResponse {
  total_market_value_brl: string
  day_change_brl: string | null
  day_change_pct: string | null
  income_ytd_brl: string
  // Trailing-12m income (BRL) and portfolio-level DY over the current total.
  income_12m_brl: string
  dy_12m_pct: string | null
  segments: Segment[]
  segment_summaries: SegmentSummary[]
  usd_brl_rate: string | null
  usd_brl_date: string | null
  fx_stale: boolean
  positions: Position[]
  warnings: string[]
}

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function request<T>(
  path: string,
  options?: { method?: string; body?: unknown },
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: options?.method ?? 'GET',
    headers: options?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
  })
  if (!response.ok) {
    let detail = `Erro ${response.status}`
    try {
      const payload = await response.json()
      if (typeof payload.detail === 'string') detail = payload.detail
    } catch {
      // keep generic message
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return response.json() as Promise<T>
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

export type Operation =
  | 'buy'
  | 'sell'
  | 'dividend'
  | 'jcp'
  | 'yield'
  | 'transfer'
  | 'split'
  | 'bonus'
  | 'custody_transfer'

export type Source = 'cei' | 'avenue' | 'binance' | 'manual'

export interface Transaction {
  id: string
  source: Source
  date: string
  ticker: string
  asset_name: string | null
  asset_class: AssetClass
  market: Market
  institution: string | null
  custody: Custody | null
  custody_from: Custody | null
  custody_to: Custody | null
  indexer: Indexer | null
  currency: string
  operation: Operation
  quantity: string
  unit_price: string
  fees: string
  total_value: string
  notes: string | null
  created_at: string
}

export interface TransactionInput {
  date: string
  ticker: string
  asset_name?: string | null
  asset_class: AssetClass
  market: Market
  institution?: string | null
  custody?: Custody | null
  custody_from?: Custody | null
  custody_to?: Custody | null
  indexer?: Indexer | null
  currency: string
  operation: Operation
  quantity: string
  unit_price: string
  fees: string
  total_value?: string | null
  notes?: string | null
}

export interface TransactionList {
  items: Transaction[]
  total: number
}

export interface TransactionQuery {
  ticker?: string
  source?: Source
  operation?: Operation
  date_from?: string
  date_to?: string
  sort?: 'date' | 'ticker' | 'operation' | 'total_value' | 'source'
  order?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export function getTransactions(params: TransactionQuery): Promise<TransactionList> {
  const search = new URLSearchParams()
  if (params.ticker) search.set('ticker', params.ticker)
  if (params.source) search.set('source', params.source)
  if (params.operation) search.set('operation', params.operation)
  if (params.date_from) search.set('date_from', params.date_from)
  if (params.date_to) search.set('date_to', params.date_to)
  if (params.sort) search.set('sort', params.sort)
  if (params.order) search.set('order', params.order)
  search.set('limit', String(params.limit ?? 50))
  search.set('offset', String(params.offset ?? 0))
  return request<TransactionList>(`/transactions?${search}`)
}

export function createTransaction(input: TransactionInput): Promise<Transaction> {
  return request<Transaction>('/transactions', { method: 'POST', body: input })
}

export function updateTransaction(
  id: string,
  input: TransactionInput,
): Promise<Transaction> {
  return request<Transaction>(`/transactions/${id}`, { method: 'PUT', body: input })
}

export function deleteTransaction(id: string): Promise<void> {
  return request<void>(`/transactions/${id}`, { method: 'DELETE' })
}

export type ImportSource = 'cei' | 'avenue' | 'binance' | 'lending-events'

export interface SkippedRow {
  row: number
  movement_type: string
  reason: string
}

// A row the parser kept as-is but flagged for manual reconciliation (e.g. a
// priced stock-lending leg the B3 statement cannot distinguish from a real
// trade — CEI defects 2/3). Emitted by the parser, so a reimport repeats
// them even when every row is a duplicate. `quantity` is a Decimal string.
export interface ImportWarning {
  row: number
  ticker: string
  date: string
  quantity: string
  message: string
}

export interface ImportResult {
  imported: number
  duplicates: number
  skipped: SkippedRow[]
  warnings: ImportWarning[]
  // Only for source 'lending-events': reference rows added to the
  // lending_events table vs already known (timeline-extension idempotency).
  events_added?: number
  events_known?: number
}

export async function importFile(
  source: ImportSource,
  file: File,
): Promise<ImportResult> {
  // Multipart upload: let the browser set the Content-Type boundary, so
  // this bypasses the JSON request() helper.
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${BASE_URL}/imports/${source}`, {
    method: 'POST',
    body: form,
  })
  if (!response.ok) {
    let detail = `Erro ${response.status}`
    try {
      const payload = await response.json()
      if (typeof payload.detail === 'string') detail = payload.detail
    } catch {
      // keep generic message
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<ImportResult>
}

export function getPortfolio(): Promise<PortfolioResponse> {
  return request<PortfolioResponse>('/portfolio')
}

export interface FngEntry {
  value: number | null
  classification: string | null
  date: string | null
}

export interface Fng {
  today: FngEntry | null
  yesterday: FngEntry | null
  last_week: FngEntry | null
  source: string
  stale: boolean
}

export interface MarketIndicator {
  key: string
  label: string
  value: string | null
  unit: string | null
  change: string | null
  change_pct: string | null
  btc_price_usd: string | null
  btc_change_pct: string | null
  as_of: string | null
  source: string
  stale: boolean
}

export interface Mayer {
  value: string | null
  price: string | null
  ma200: string | null
  min: string | null
  max: string | null
  percentile: string | null
  years: number | null
  source: string
  as_of: string | null
  stale: boolean
}

export interface MarketResponse {
  fng: Fng
  btc_dominance: MarketIndicator
  mayer: Mayer
  ibov: MarketIndicator
  sp500: MarketIndicator
  vix: MarketIndicator
  dxy: MarketIndicator
  treasury_3m: MarketIndicator
  treasury_10y: MarketIndicator
  fetched_at: string
  warnings: string[]
}

export function getMarket(refresh = false): Promise<MarketResponse> {
  return request<MarketResponse>(`/market${refresh ? '?refresh=true' : ''}`)
}

export interface Mover {
  ticker: string
  asset_name: string | null
  segment: string // br | us | crypto
  change_pct: string // fractional day variation
  price: string // current quote, native currency
  currency: string // BRL | USD
}

export interface MoversBucket {
  gainers: Mover[]
  losers: Mover[]
}

export type MoversFilter = 'all' | 'br' | 'us' | 'crypto'

export interface MoversResponse {
  filters: Record<MoversFilter, MoversBucket>
  // Crypto band shown only under "all": BTC/ETH with their Binance 24h change,
  // kept out of the stock ranking (different metric).
  crypto_info: Mover[]
  skipped: number
  fetched_at: string
  warnings: string[]
}

export function getMovers(refresh = false): Promise<MoversResponse> {
  return request<MoversResponse>(`/market/movers${refresh ? '?refresh=true' : ''}`)
}

export interface UsdBrlMarket {
  rate: string | null
  quote_date: string | null
  fetched_at: string | null
  source: string | null
  stale: boolean
}

export function getUsdBrlMarket(): Promise<UsdBrlMarket> {
  return request<UsdBrlMarket>('/portfolio/usdbrl-market')
}

export interface HistoryPoint {
  date: string
  total_brl: string
  twr_index: string
}

export interface PortfolioHistoryResponse {
  points: HistoryPoint[]
  warnings: string[]
}

export type Granularity = 'daily' | 'weekly' | 'monthly'

export interface PerformancePoint {
  date: string
  carteira: string
  cdi: string | null
  ibov: string | null
  sp500: string | null
  btc: string | null
}

export interface PerformanceResponse {
  points: PerformancePoint[]
  warnings: string[]
}

export interface ContributionMonth {
  month: string
  aportes: string
  vendas: string
  rendimentos: string
}

export interface ContributionsResponse {
  months: ContributionMonth[]
}

export function getContributions(months = 24): Promise<ContributionsResponse> {
  return request<ContributionsResponse>(`/portfolio/contributions?months=${months}`)
}

export function getPerformance(
  granularity: Granularity = 'weekly',
): Promise<PerformanceResponse> {
  return request<PerformanceResponse>(
    `/portfolio/performance?granularity=${granularity}`,
  )
}

export function getPortfolioHistory(
  granularity: Granularity = 'daily',
): Promise<PortfolioHistoryResponse> {
  return request<PortfolioHistoryResponse>(
    `/portfolio/history?granularity=${granularity}`,
  )
}

export type ReturnsPeriod = '1M' | '3M' | '6M' | 'YTD' | '1A' | 'MAX'

export interface ReturnPoint {
  date: string
  return_pct: string | null
}

export interface ReturnSeries {
  key: string
  label: string
  kind: 'segment' | 'benchmark'
  points: ReturnPoint[]
}

export interface ReturnsResponse {
  period: string
  start: string | null
  series: ReturnSeries[]
  warnings: string[]
}

export function getReturns(params: {
  segments: string[]
  benchmarks: string[]
  period: ReturnsPeriod
  currency?: 'BRL' | 'USD'
}): Promise<ReturnsResponse> {
  const search = new URLSearchParams({
    segments: params.segments.join(','),
    benchmarks: params.benchmarks.join(','),
    period: params.period,
  })
  if (params.currency) search.set('currency', params.currency)
  return request<ReturnsResponse>(`/portfolio/returns?${search}`)
}

export type CorrelationPeriod = '3M' | '6M' | '1A' | 'MAX'
export type CorrelationSegment = '' | 'br' | 'us' | 'crypto'

export interface CorrelationResponse {
  period: string
  segment: string | null
  tickers: string[]
  matrix: (number | null)[][]
  warnings: string[]
}

export function getCorrelation(params: {
  period: CorrelationPeriod
  segment: CorrelationSegment
}): Promise<CorrelationResponse> {
  const search = new URLSearchParams({ period: params.period })
  if (params.segment) search.set('segment', params.segment)
  return request<CorrelationResponse>(`/portfolio/correlation?${search}`)
}

export type CapmPeriod = '6M' | '1A' | '2A' | 'MAX'

export interface CapmSegment {
  key: string
  label: string
  benchmark_label: string
  risk_free_label: string
  period: string
  period_label: string
  frequency: string
  beta: number | null
  alpha_annual_pct: number | null
  correlation: number | null
  observations: number
  note: string | null
  warnings: string[]
}

export interface CapmResponse {
  period: string
  period_label: string
  frequency: string
  segments: CapmSegment[]
  warnings: string[]
}

export function getCapm(period: CapmPeriod = '1A'): Promise<CapmResponse> {
  return request<CapmResponse>(`/portfolio/capm?period=${period}`)
}

export interface SnapshotSummary {
  year_month: string
  as_of_date: string
  total_brl: string
  month_return_pct: string | null
  cumulative_return_pct: string | null
  income_month_brl: string
}

export interface SnapshotPosition {
  ticker: string
  asset_name: string | null
  asset_class: AssetClass
  market: Market
  institution: string | null
  currency: string
  quantity: string
  average_price: string
  market_value_brl: string
  unrealized_pnl_brl: string | null
  priced: boolean
}

export interface SnapshotDetail extends SnapshotSummary {
  created_at: string
  last_recomputed_at: string | null
  recompute_reason: string | null
  positions: SnapshotPosition[]
  allocation_class: Record<string, string>
  allocation_currency: Record<string, string>
  allocation_broker: Record<string, string>
  usd_brl_rate: string | null
}

export function getMonthlyReports(): Promise<{ items: SnapshotSummary[] }> {
  return request<{ items: SnapshotSummary[] }>('/reports/monthly')
}

export function getMonthlyReport(yearMonth: string): Promise<SnapshotDetail> {
  return request<SnapshotDetail>(`/reports/monthly/${yearMonth}`)
}

export function generateMonthlyReport(): Promise<SnapshotDetail> {
  return request<SnapshotDetail>('/reports/monthly/generate', { method: 'POST' })
}
