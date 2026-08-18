import { STATIC_DEMO } from '../api/staticDemo'
import { useEffect, useState } from 'react'
import {
  getMarket,
  getMovers,
  type Fng,
  type FngEntry,
  type MarketIndicator,
  type MarketResponse,
  type Mayer,
  type Mover,
  type MoversFilter,
  type MoversResponse,
} from '../api/client'
import { SkeletonCard } from '../components/Skeleton'

// Indicators here are CONTEXT, not signals: no buy/sell arrows, no alerts, no
// "cheap/expensive". Only numbers, the source's own textual class (F&G), and
// dates. Semantic color is used ONLY for F&G (the source's canonical scale).

const num = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 })
const num4dec = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 4 })
const usd0 = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 })
const num4 = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const pct1 = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})
const dateFmt = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  year: '2-digit',
})
const timeFmt = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function fmtDate(value: string | null): string {
  return value ? dateFmt.format(new Date(`${value}T12:00:00`)) : '—'
}

// F&G canonical scale (alternative.me): fear = red … greed = green.
function fngColor(value: number | null): string {
  if (value == null) return 'var(--color-slate-500)'
  if (value < 25) return '#ef4444'
  if (value < 50) return '#f97316'
  if (value < 75) return '#a3e635'
  return '#22c55e'
}

function Card({
  title,
  source,
  asOf,
  stale,
  children,
}: {
  title: string
  source: string
  asOf?: string | null
  stale?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm text-slate-400">{title}</p>
        {stale && !STATIC_DEMO && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-300">
            desatualizado
          </span>
        )}
      </div>
      {children}
      <p className="mt-3 text-[11px] text-slate-500">
        {asOf ? `${fmtDate(asOf)} · ` : ''}fonte: {source}
      </p>
    </div>
  )
}

// Arrow color by sign: green > 0, gray = 0, red < 0.
function changeColor(pct: number): string {
  return pct > 0 ? 'text-green-400' : pct < 0 ? 'text-red-400' : 'text-slate-400'
}

function ChangeArrow({ ind }: { ind: MarketIndicator }) {
  if (ind.change_pct == null) return null
  const pct = Number(ind.change_pct)
  const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '–'
  // VIX: always blue (its "up" is not bad/good the way an asset's is).
  const color = ind.key === 'vix' ? 'text-sky-400' : changeColor(pct)
  return (
    <span className={`ml-2 text-xs tabular-nums ${color}`} title="vs fechamento anterior">
      {arrow} {pct1.format(Math.abs(pct))}
    </span>
  )
}

function btcChangeNode(pctStr: string | null) {
  if (pctStr == null) return null
  const pct = Number(pctStr)
  const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '–'
  return (
    <span className={`text-sm tabular-nums ${changeColor(pct)}`} title="variação 24h (Binance)">
      {arrow} {pct1.format(Math.abs(pct))}
    </span>
  )
}

function IndicatorCard({ ind }: { ind: MarketIndicator }) {
  const v = ind.value != null ? Number(ind.value) : null
  // Ratios (< 1, e.g. ETH/BTC) need more decimals than index points.
  const formatted =
    v == null ? '—' : Math.abs(v) < 1 ? num4dec.format(v) : num.format(v)
  const suffix = ind.unit && ind.unit !== '%' ? ` ${ind.unit}` : ''
  const mainValue = (
    <p className="mt-1 flex items-baseline text-2xl font-semibold tabular-nums text-slate-100">
      <span>
        {formatted}
        {v != null && ind.unit === '%' && '%'}
        {v != null && <span className="text-sm text-slate-500">{suffix}</span>}
      </span>
      <ChangeArrow ind={ind} />
    </p>
  )
  // BTC card: price is the headline (with the colored 24h change inline),
  // dominance is a small gray subtext below (same style as the Mayer subtext).
  // Dual-source by construction: the price/24h overlay is Binance (only present
  // when it answered), dominance is ind.source (coingecko) — label both. When
  // the overlay is absent the card is dominance-only and ind.source alone is right.
  if (ind.btc_price_usd != null) {
    return (
      <Card
        title="Bitcoin (BTC)"
        source={`binance (preço) · ${ind.source} (dominância)`}
        asOf={ind.as_of}
        stale={ind.stale}
      >
        <p className="mt-1 flex items-baseline gap-2 text-2xl font-semibold tabular-nums text-slate-100">
          <span>
            <span className="text-sm text-slate-500">US$ </span>
            {usd0.format(Number(ind.btc_price_usd))}
          </span>
          {btcChangeNode(ind.btc_change_pct)}
        </p>
        <p className="mt-2 text-sm text-slate-400">
          Dominância: {v != null ? `${num.format(v)}%` : '—'}
        </p>
      </Card>
    )
  }
  return (
    <Card title={ind.label} source={ind.source} asOf={ind.as_of} stale={ind.stale}>
      {mainValue}
    </Card>
  )
}

function fngRow(label: string, e: FngEntry | null) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: fngColor(e?.value ?? null) }}
        />
        <span className="tabular-nums text-slate-300">{e?.value ?? '—'}</span>
        <span className="text-slate-500">{e?.classification ?? ''}</span>
      </span>
    </div>
  )
}

function FngCard({ fng }: { fng: Fng }) {
  const t = fng.today
  const color = fngColor(t?.value ?? null)
  return (
    <Card title="Medo & Ganância (cripto)" source={fng.source} asOf={t?.date} stale={fng.stale}>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-3xl font-semibold tabular-nums" style={{ color }}>
          {t?.value ?? '—'}
        </span>
        <span className="text-sm font-medium" style={{ color }}>
          {t?.classification ?? ''}
        </span>
      </div>
      <div className="mt-3 space-y-1 border-t border-slate-800 pt-2">
        {fngRow('Hoje', fng.today)}
        {fngRow('Ontem', fng.yesterday)}
        {fngRow('Semana passada', fng.last_week)}
      </div>
    </Card>
  )
}

function MayerCard({ mayer }: { mayer: Mayer }) {
  const value = mayer.value != null ? num4.format(Number(mayer.value)) : '—'
  // Neutral position bar between historical min and max (no red/yellow/green).
  let pos: number | null = null
  if (mayer.value != null && mayer.min != null && mayer.max != null) {
    const v = Number(mayer.value)
    const lo = Number(mayer.min)
    const hi = Number(mayer.max)
    pos = hi > lo ? Math.min(1, Math.max(0, (v - lo) / (hi - lo))) : 0.5
  }
  return (
    <Card title="Múltiplo de Mayer (BTC)" source={mayer.source} asOf={mayer.as_of} stale={mayer.stale}>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-100">{value}</p>
      <p className="mt-0.5 text-[11px] text-slate-500">
        preço ÷ média 200d{mayer.price != null && mayer.ma200 != null
          ? ` · ${num.format(Number(mayer.price))} ÷ ${num.format(Number(mayer.ma200))}`
          : ''}
      </p>
      {pos != null && (
        <div className="mt-3">
          <div className="relative h-1.5 w-full rounded-full bg-slate-700">
            <span
              className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300"
              style={{ left: `${pos * 100}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-slate-500 tabular-nums">
            <span>mín {mayer.min}</span>
            <span>
              {mayer.percentile != null
                ? `${pct1.format(Number(mayer.percentile))} do hist. (${mayer.years}a)`
                : ''}
            </span>
            <span>máx {mayer.max}</span>
          </div>
        </div>
      )}
    </Card>
  )
}

const moneyFmt: Record<string, Intl.NumberFormat> = {
  BRL: new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }),
  USD: new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD' }),
}

function fmtMoney(price: string, currency: string): string {
  const fmt = moneyFmt[currency] ?? moneyFmt.BRL
  return fmt.format(Number(price))
}

const MOVERS_CHIPS: { key: MoversFilter; label: string }[] = [
  { key: 'all', label: 'Todos' },
  { key: 'br', label: 'Brasil' },
  { key: 'us', label: 'EUA' },
  { key: 'crypto', label: 'Cripto' },
]

// The variation % is the hero of the row: largest and heaviest, with an
// explicit +/− and the semantic color already used across Mercado. No arrows
// and no column headers — sign+color and the left/right column convey direction.
function MoverRow({ m, showWindow = false }: { m: Mover; showWindow?: boolean }) {
  const pct = Number(m.change_pct)
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
  return (
    <li className="flex items-baseline gap-3 py-2">
      <span className="min-w-0 flex-1 truncate" title={m.asset_name ?? m.ticker}>
        <span className="font-medium text-slate-200">{m.ticker}</span>
        {m.asset_name && m.asset_name !== m.ticker && (
          <span className="ml-1.5 text-xs text-slate-500">{m.asset_name}</span>
        )}
        {showWindow && (
          <span className="ml-1.5 text-[10px] uppercase tracking-wide text-slate-600">
            24h
          </span>
        )}
      </span>
      <span className={`text-lg font-semibold tabular-nums ${changeColor(pct)}`}>
        {sign}
        {pct1.format(Math.abs(pct))}
      </span>
      <span className="w-24 shrink-0 text-right text-xs tabular-nums text-slate-500">
        {fmtMoney(m.price, m.currency)}
      </span>
    </li>
  )
}

function MoverList({ rows, showWindow }: { rows: Mover[]; showWindow?: boolean }) {
  if (rows.length === 0) return <p className="py-2 text-sm text-slate-600">—</p>
  return (
    <ul className="divide-y divide-slate-800/60">
      {rows.map((m) => (
        <MoverRow key={`${m.segment}-${m.ticker}`} m={m} showWindow={showWindow} />
      ))}
    </ul>
  )
}

function MoversCard({ data }: { data: MoversResponse }) {
  const [filter, setFilter] = useState<MoversFilter>('all')
  const bucket = data.filters[filter] ?? { gainers: [], losers: [] }
  const isCrypto = filter === 'crypto'
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-400">Maiores Variações · última sessão</p>
        <div className="flex gap-1">
          {MOVERS_CHIPS.map((chip) => (
            <button
              key={chip.key}
              type="button"
              onClick={() => setFilter(chip.key)}
              className={`rounded-full px-2.5 py-1 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 ${
                filter === chip.key
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {/* Left = altas, right = baixas; position + color replace the headers.
          Columns collapse to one on narrow screens. */}
      <div className="mt-4 grid grid-cols-1 gap-x-10 gap-y-1 sm:grid-cols-2">
        <MoverList rows={bucket.gainers} showWindow={isCrypto} />
        <MoverList rows={bucket.losers} showWindow={isCrypto} />
      </div>

      {/* Crypto band (only under "Todos"): different metric, so it sits apart
          below a hairline with a "Cripto · 24h" eyebrow encoding the window. */}
      {filter === 'all' && data.crypto_info.length > 0 && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Cripto · 24h
          </p>
          <div className="grid grid-cols-1 gap-x-10 sm:grid-cols-2">
            <MoverList rows={data.crypto_info} />
          </div>
        </div>
      )}

      <p className="mt-3 text-[11px] text-slate-500">
        Variação vs. fechamento anterior · cripto: 24h Binance · ações BR/EUA e
        cripto da carteira, exceto renda fixa
        {data.skipped > 0 && ` · ${data.skipped} sem variação/cotação`}
      </p>
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">{title}</h3>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
    </section>
  )
}

export default function Mercado() {
  const [data, setData] = useState<MarketResponse | null>(null)
  const [movers, setMovers] = useState<MoversResponse | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  function load(refresh = false) {
    setLoading(true)
    getMarket(refresh)
      .then((d) => {
        setData(d)
        setError(false)
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
    // Movers fail independently of the macro indicators (Mercado convention).
    getMovers(refresh)
      .then(setMovers)
      .catch(() => undefined)
  }

  useEffect(() => {
    let cancelled = false
    getMarket()
      .then((d) => {
        if (!cancelled) {
          setData(d)
          setError(false)
        }
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    getMovers()
      .then((d) => {
        if (!cancelled) setMovers(d)
      })
      .catch(() => undefined)
    // Poll every 15 min while the page is open: the server serves the macro
    // indicators from their 30-min cache and overlays the fresh (15-min) BTC
    // price/24h change, so the BTC card stays current without forcing a full
    // refetch of the slow indicators.
    const interval = setInterval(() => {
      if (!cancelled) load(false)
    }, 15 * 60 * 1000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Mercado</h2>
          <p className="text-xs text-slate-500">
            Indicadores externos de contexto — não são recomendação nem sinal de
            compra/venda.
            {data && ` Atualizado ${timeFmt.format(new Date(data.fetched_at))}.`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={loading}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? 'Atualizando…' : 'Atualizar'}
        </button>
      </div>

      {error && !data && (
        <div className="rounded-xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          Não foi possível carregar os indicadores.
        </div>
      )}
      {!error && !data && (
        <div className="space-y-8">
          {[0, 1, 2].map((block) => (
            <div key={block} className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </div>
          ))}
        </div>
      )}

      {data && (
        <div className="space-y-8">
          {movers && <MoversCard data={movers} />}
          <Block title="Cripto">
            <FngCard fng={data.fng} />
            <IndicatorCard ind={data.btc_dominance} />
            <MayerCard mayer={data.mayer} />
          </Block>
          <Block title="Ações / mercado amplo">
            <IndicatorCard ind={data.ibov} />
            <IndicatorCard ind={data.sp500} />
            <IndicatorCard ind={data.vix} />
          </Block>
          <Block title="Câmbio / macro">
            <IndicatorCard ind={data.dxy} />
            <IndicatorCard ind={data.treasury_3m} />
            <IndicatorCard ind={data.treasury_10y} />
          </Block>
        </div>
      )}
    </main>
  )
}
