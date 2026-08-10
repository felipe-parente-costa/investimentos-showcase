import { useEffect, useMemo, useState } from 'react'
import { getPortfolio, type PortfolioResponse, type Position } from '../api/client'
import AllocationDonut, { type DonutSlice } from '../components/AllocationDonut'
import CapmSection from '../components/CapmSection'
import PositionsTable from '../components/PositionsTable'
import PositionsSection from '../components/PositionsSection'
import SegmentReturnsChart from '../components/SegmentReturnsChart'
import UsdBrlMarketCard from '../components/UsdBrlMarketCard'
import { SkeletonCard, SkeletonChart, SkeletonRows } from '../components/Skeleton'
import {
  type GroupDef,
  type Groupable,
  brasilGroup,
  BRASIL_GROUPS,
  euaGroup,
  EUA_GROUPS,
  rfGroup,
  RF_GROUPS,
} from '../lib/grouping'
import {
  CUSTODY_LABELS,
  INDEXER_LABELS,
  formatMoney,
  formatPercent,
  formatSignedPercent,
} from '../lib/format'
import {
  BENCHMARK_COLORS,
  CUSTODY_COLORS,
  INDEXER_COLORS,
  SECTION_COLORS,
} from '../lib/colors'

const REFRESH_MS = 5 * 60 * 1000

export type SegmentKey = 'br' | 'us' | 'crypto' | 'rf'

interface SegmentConfig {
  key: SegmentKey
  title: string
  color: string
  match: (p: Position) => boolean
  benchmark?: { key: string; label: string; color: string }
}

const CONFIGS: Record<SegmentKey, SegmentConfig> = {
  br: {
    key: 'br',
    title: 'Brasil (B3)',
    color: SECTION_COLORS.br,
    match: (p) => p.market === 'br' && p.asset_class !== 'fixed_income',
    benchmark: { key: 'ibov', label: 'IBOV', color: BENCHMARK_COLORS.ibov },
  },
  us: {
    key: 'us',
    title: 'EUA (Avenue)',
    color: SECTION_COLORS.us,
    match: (p) => p.market === 'us',
    benchmark: { key: 'sp500', label: 'S&P 500', color: BENCHMARK_COLORS.sp500 },
  },
  crypto: {
    key: 'crypto',
    title: 'Cripto',
    color: SECTION_COLORS.crypto,
    match: (p) => p.market === 'crypto',
    benchmark: { key: 'btc', label: 'BTC', color: BENCHMARK_COLORS.btc },
  },
  rf: {
    key: 'rf',
    title: 'Renda Fixa',
    color: SECTION_COLORS.rf,
    match: (p) => p.asset_class === 'fixed_income',
    benchmark: { key: 'cdi', label: 'CDI', color: BENCHMARK_COLORS.cdi },
  },
}

// Per-page grouping (Cripto is handled separately, ungrouped).
const GROUPING: Record<
  'br' | 'us' | 'rf',
  { groupOf: (p: Groupable) => string; groupMeta: Record<string, GroupDef> }
> = {
  br: { groupOf: brasilGroup, groupMeta: BRASIL_GROUPS },
  us: { groupOf: euaGroup, groupMeta: EUA_GROUPS },
  rf: { groupOf: rfGroup, groupMeta: RF_GROUPS },
}

function changeColor(value: number | null): string {
  if (value == null || value === 0) return 'text-slate-300'
  return value > 0 ? 'text-green-400' : 'text-red-400'
}

type AssetClassFilter = 'all' | 'stock' | 'fii' | 'etf'

// Chips do donut "Alocação por ativo" (só Brasil e EUA). Afeta SÓ esse donut.
const ASSET_FILTERS: Partial<
  Record<SegmentKey, { value: AssetClassFilter; label: string }[]>
> = {
  br: [
    { value: 'all', label: 'Tudo' },
    { value: 'stock', label: 'Ações' },
    { value: 'fii', label: 'FIIs' },
  ],
  us: [
    { value: 'all', label: 'All' },
    { value: 'stock', label: 'Stocks' },
    { value: 'etf', label: 'ETFs' },
  ],
}

function sliceBy(
  positions: Position[],
  label: (p: Position) => string,
  color?: (p: Position) => string | undefined,
): DonutSlice[] {
  const groups = new Map<string, DonutSlice>()
  for (const position of positions) {
    if (position.market_value_brl == null) continue
    const key = label(position)
    const slice = groups.get(key) ?? { label: key, value: 0, color: color?.(position) }
    slice.value += Number(position.market_value_brl)
    groups.set(key, slice)
  }
  return [...groups.values()]
}

interface Props {
  segment: SegmentKey
}

export default function Segmento({ segment }: Props) {
  const config = CONFIGS[segment]
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  // App.tsx mounts this component with `key={page}` (page === segment), so a
  // segment change always remounts fresh — this state already starts at
  // 'all' on every section, no reset-on-prop-change effect needed.
  const [assetClassFilter, setAssetClassFilter] = useState<AssetClassFilter>('all')

  useEffect(() => {
    let cancelled = false
    function load() {
      getPortfolio()
        .then((data) => {
          if (cancelled) return
          setPortfolio(data)
          setError(null)
        })
        .catch(() => {
          if (!cancelled) setError('Não foi possível carregar o portfólio.')
        })
    }
    load()
    const interval = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const positions = useMemo(
    () => (portfolio ? portfolio.positions.filter(config.match) : []),
    [portfolio, config],
  )
  const summary = portfolio?.segment_summaries.find((s) => s.key === segment)

  // EUA and Cripto are read in USD; Brasil and Renda Fixa stay in BRL.
  const isUsd = segment === 'us' || segment === 'crypto'

  // Positions remapped so the table/donuts show the USD numbers in the same
  // fields they already read (display-only; the consolidated total stays BRL).
  const displayPositions = useMemo(() => {
    if (!isUsd) return positions
    return positions.map((p) => {
      const qty = Number(p.quantity)
      return {
        ...p,
        currency: 'USD',
        average_price: p.usd_average_price ?? p.average_price,
        total_cost: p.usd_total_cost ?? p.total_cost,
        market_value_brl: p.usd_market_value ?? p.market_value_brl,
        unrealized_pnl: p.usd_unrealized_pnl ?? p.unrealized_pnl,
        quote_currency: 'USD',
        quote_price:
          p.usd_market_value != null && qty !== 0
            ? String(Number(p.usd_market_value) / qty)
            : p.quote_price,
      }
    })
  }, [positions, isUsd])

  // "Por ativo" donut in USD for the dollar sections (EUA and Cripto), reusing
  // the same usd_market_value the section already shows. The crypto basis
  // between {ticker}BRL and {ticker}USDT shifts slice shares by ~0,002pp
  // (two real market prices, validated as benign). Brasil/RF stay BRL.
  const useUsdDonuts = segment === 'us' || segment === 'crypto'
  const donutPositions = useUsdDonuts ? displayPositions : positions
  const donutCurrency = useUsdDonuts ? 'USD' : 'BRL'

  // Renda Fixa: split marked-to-market (Tesouro) from at-cost (private).
  const marked = positions.filter((p) => p.priced)
  const atCost = positions.filter((p) => !p.priced)
  const cryptoCustody = positions.filter((p) => p.custody != null)

  // Renda Fixa: market value by indexer, and each indexer's share of the
  // whole portfolio (not just of the segment).
  const indexerTotals = useMemo(() => {
    const totals = new Map<string, number>()
    for (const p of positions) {
      if (p.indexer == null || p.market_value_brl == null) continue
      totals.set(p.indexer, (totals.get(p.indexer) ?? 0) + Number(p.market_value_brl))
    }
    return totals
  }, [positions])
  const portfolioTotal = portfolio ? Number(portfolio.total_market_value_brl) : 0

  // Section-level display values: USD for EUA/Cripto, BRL otherwise.
  const sectionValue = isUsd ? summary?.usd_total : summary?.total_brl
  const sectionPnl = isUsd ? summary?.usd_unrealized_pnl : summary?.unrealized_pnl_brl
  const sectionPnlPct = isUsd ? summary?.usd_pnl_pct : summary?.pnl_pct
  const sectionCurrency = isUsd ? 'USD' : 'BRL'

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="font-display text-xl font-semibold">{config.title}</h2>
        {isUsd && (
          <span
            title="Esta seção é exibida em dólar; o patrimônio total e a seção Brasil seguem em reais."
            className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-300"
          >
            Valores em dólar (US$)
          </span>
        )}
      </div>

      {segment === 'us' && <UsdBrlMarketCard />}

      {error && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}
      {!error && !portfolio && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="h-72">
              <SkeletonChart />
            </div>
          </div>
          <SkeletonRows />
        </div>
      )}
      {portfolio && positions.length === 0 && (
        <p className="text-slate-400">Nenhuma posição aberta neste segmento.</p>
      )}

      {portfolio && positions.length > 0 && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <p className="text-xs text-slate-400">Valor total</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {formatMoney(sectionValue ?? '0', sectionCurrency)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {summary?.position_count ?? positions.length} posições
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <p className="text-xs text-slate-400">P&L não realizado</p>
              {summary && sectionPnl != null ? (
                <>
                  <p
                    className={`mt-1 text-2xl font-semibold tabular-nums ${changeColor(
                      Number(sectionPnl),
                    )}`}
                  >
                    {formatMoney(sectionPnl, sectionCurrency)}
                  </p>
                  {sectionPnlPct != null && (
                    <p
                      className={`mt-1 text-xs tabular-nums ${changeColor(
                        Number(sectionPnlPct),
                      )}`}
                    >
                      {formatSignedPercent(Number(sectionPnlPct))} sobre o custo ·
                      retorno simples
                    </p>
                  )}
                  <p className="mt-1 text-[11px] text-slate-500">
                    Quanto a posição atual vale acima do que custou. Diferente da
                    rentabilidade (TWR) no gráfico abaixo.
                  </p>
                </>
              ) : (
                <p className="mt-1 text-2xl font-semibold text-slate-500">—</p>
              )}
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <p className="text-xs text-slate-400">Peso no patrimônio</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {summary?.weight_pct != null
                  ? formatPercent(Number(summary.weight_pct))
                  : '—'}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                de {formatMoney(portfolio.total_market_value_brl)}
              </p>
            </div>
          </div>

          {/* Renda Fixa: marked-to-market vs at-cost breakdown */}
          {segment === 'rf' && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                <p className="text-sm text-slate-300">
                  Marcados a mercado (Tesouro){' '}
                  <span className="text-xs text-slate-500">({marked.length})</span>
                </p>
                <ul className="mt-2 space-y-1 text-xs text-slate-400">
                  {marked.map((p) => (
                    <li key={p.ticker} className="flex justify-between gap-2">
                      <span>{p.ticker}</span>
                      <span className="tabular-nums text-slate-300">
                        {formatMoney(p.market_value_brl)}
                      </span>
                    </li>
                  ))}
                  {marked.length === 0 && <li>Nenhum.</li>}
                </ul>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                <p className="text-sm text-slate-300">
                  A custo (privados: CDB/LCI/LCA){' '}
                  <span className="text-xs text-slate-500">({atCost.length})</span>
                </p>
                <ul className="mt-2 space-y-1 text-xs text-slate-400">
                  {atCost.map((p) => (
                    <li key={p.ticker} className="flex justify-between gap-2">
                      <span>{p.ticker}</span>
                      <span className="tabular-nums text-slate-300">
                        {formatMoney(p.market_value_brl)}
                      </span>
                    </li>
                  ))}
                  {atCost.length === 0 && <li>Nenhum.</li>}
                </ul>
              </div>
            </div>
          )}

          {/* Allocation donuts */}
          <div className="grid gap-6 lg:grid-cols-2">
            <AllocationDonut
              title="Alocação por ativo"
              slices={sliceBy(
                assetClassFilter === 'all'
                  ? donutPositions
                  : donutPositions.filter((p) => p.asset_class === assetClassFilter),
                (p) => p.ticker,
              )}
              currency={donutCurrency}
              maxSlices={8}
              headerRight={
                ASSET_FILTERS[segment] && (
                  <div className="flex gap-1">
                    {ASSET_FILTERS[segment]!.map((f) => (
                      <button
                        key={f.value}
                        type="button"
                        onClick={() => setAssetClassFilter(f.value)}
                        className={`rounded-md px-2 py-1 text-xs ${
                          assetClassFilter === f.value
                            ? 'bg-slate-700 text-slate-100'
                            : 'text-slate-400 hover:bg-slate-800'
                        }`}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                )
              }
            />
            {/* Sector makes sense only for Brasil and EUA. Crypto would be
                ~100% "Sem setor"; Renda Fixa is a single sector. */}
            {segment !== 'crypto' && segment !== 'rf' && (
              <AllocationDonut
                title="Distribuição por setor"
                slices={sliceBy(donutPositions, (p) => p.sector ?? 'Sem setor')}
                currency={donutCurrency}
              />
            )}
            {segment === 'crypto' && cryptoCustody.length > 0 && (
              <AllocationDonut
                title="Por custódia (hot/cold)"
                slices={sliceBy(
                  donutPositions.filter((p) => p.custody != null),
                  (p) => CUSTODY_LABELS[p.custody!],
                  (p) => CUSTODY_COLORS[p.custody!],
                )}
                currency={donutCurrency}
              />
            )}
            {segment === 'rf' && indexerTotals.size > 0 && (
              <div className="space-y-3">
                <AllocationDonut
                  title="Alocação por indexador (dentro da renda fixa)"
                  slices={sliceBy(
                    positions.filter((p) => p.indexer != null),
                    (p) => INDEXER_LABELS[p.indexer!],
                    (p) => INDEXER_COLORS[p.indexer!],
                  )}
                />
                <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
                  <p className="mb-2 text-xs text-slate-400">
                    Peso de cada indexador no patrimônio total
                  </p>
                  <ul className="space-y-1 text-xs">
                    {[...indexerTotals.entries()]
                      .sort((a, b) => b[1] - a[1])
                      .map(([key, value]) => (
                        <li key={key} className="flex items-center justify-between gap-2">
                          <span className="flex items-center gap-1.5 text-slate-300">
                            <span
                              className="h-2.5 w-2.5 rounded-sm"
                              style={{ backgroundColor: INDEXER_COLORS[key] }}
                            />
                            {INDEXER_LABELS[key as keyof typeof INDEXER_LABELS]}
                          </span>
                          <span className="tabular-nums text-slate-400">
                            {formatMoney(String(value))}
                            {portfolioTotal > 0 && (
                              <span className="ml-2 text-slate-500">
                                {formatPercent(value / portfolioTotal)}
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                  </ul>
                </div>
              </div>
            )}
          </div>

          {/* CAPM: correlation, alpha, beta. Brasil breaks into Total/Ações/
              FIIs; EUA stands alone. Cripto and Renda Fixa get no alpha/beta. */}
          {segment === 'br' && (
            <CapmSection segmentKeys={['br_total', 'br_stock', 'br_fii']} />
          )}
          {segment === 'us' && <CapmSection segmentKeys={['us']} />}
          {segment === 'crypto' && (
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-xs text-slate-400">
              Alfa e beta não são exibidos para Cripto: contra o próprio mercado
              cripto o beta diz pouco. A comparação relevante é a rentabilidade vs.
              BTC no gráfico abaixo.
            </div>
          )}
          {segment === 'rf' && (
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-xs text-slate-400">
              Renda Fixa não tem alfa/beta (não se aplica a CAPM). A comparação
              relevante é a rentabilidade vs. CDI no gráfico abaixo.
            </div>
          )}

          <SegmentReturnsChart
            segmentKey={config.key}
            segmentLabel={config.title}
            color={config.color}
            benchmark={config.benchmark}
            currency={sectionCurrency}
          />

          {segment === 'crypto' ? (
            // Cripto: 3 ativos, lista direta (sem agrupar).
            <PositionsTable positions={displayPositions} valueCurrency={sectionCurrency} />
          ) : (
            <PositionsSection
              positions={displayPositions}
              groupOf={GROUPING[segment].groupOf}
              groupMeta={GROUPING[segment].groupMeta}
              valueCurrency={sectionCurrency}
              showIndexer={segment === 'rf'}
              showDy={segment !== 'rf'}
            />
          )}

          {portfolio.warnings.filter((w) => positions.some((p) => w.startsWith(p.ticker)))
            .length > 0 && (
            <div className="rounded-xl border border-amber-900/60 bg-amber-950/30 p-4 text-xs text-amber-300">
              <ul className="list-inside list-disc space-y-1">
                {portfolio.warnings
                  .filter((w) => positions.some((p) => w.startsWith(p.ticker)))
                  .map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
              </ul>
            </div>
          )}
        </>
      )}
    </main>
  )
}
