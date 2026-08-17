import { useMemo, useState, type ReactNode } from 'react'
import {
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import type { RiskGroupBy, RiskReturn, RiskReturnPoint } from '../api/client'
import { SECTION_COLORS, SHARPE_BANDS, sharpeBand } from '../lib/colors'
import { formatPercent, formatSignedPercent } from '../lib/format'
import { SkeletonChart } from './Skeleton'

type Level = 'assets' | 'groups'

const SEGMENTS: { key: string; label: string }[] = [
  { key: 'br', label: 'Brasil' },
  { key: 'us', label: 'EUA' },
  { key: 'crypto', label: 'Cripto' },
  { key: 'rf', label: 'Renda fixa' },
]

// Cor de cada carteira-seção: reusa a identidade já validada da seção
// (mesma cor que Brasil/EUA/Cripto/RF têm nos gráficos de evolução).
const SEGMENT_COLORS: Record<string, string> = {
  br: SECTION_COLORS.br,
  us: SECTION_COLORS.us,
  crypto: SECTION_COLORS.crypto,
  // Roxo, não o verde-água que a RF usa no resto do app: aqui a identidade
  // de seção divide a tela com as faixas de Sharpe, e o verde-água fica a
  // ΔE 9,8 do verde da faixa "1 ou mais". Ver o token no index.css.
  rf: 'var(--color-segment-rf)',
}

/** Short code to ride inside a bubble. Tesouro tickers are whole sentences
 * ("Tesouro IPCA+ 2029"); everything else is already a ticker. */
function shortCode(key: string): string {
  const bond = key.match(/^Tesouro\s+(IPCA\+|Prefixado|Selic)\s*(\d{2})(\d{2})/i)
  if (bond) {
    const kind = bond[1].toUpperCase().startsWith('IPCA') ? 'IPCA' : bond[1].slice(0, 3).toUpperCase()
    return `${kind}${bond[3]}`
  }
  return key.length > 7 ? key.slice(0, 7) : key
}

/** Axis domain from the data, rounded out to whole 5-point steps. Recharts'
 * own auto-domain padded this chart to ±80% when nothing lived past -50%,
 * wasting most of the card. */
function ratioDomain(values: number[], floorAtZero = false): [number, number] {
  if (values.length === 0) return [0, 1]
  const step = 0.05
  const min = Math.min(...values)
  const max = Math.max(...values)
  const pad = Math.max((max - min) * 0.08, 0.02)
  const lo = Math.floor((min - pad) / step) * step
  const hi = Math.ceil((max + pad) / step) * step
  return [floorAtZero ? Math.max(0, lo) : lo, hi]
}

// Rótulo curto das carteiras-seção no gráfico: "EUA (Avenue)" é nome de
// tela, comprido demais para ficar colado num losango.
const SHORT_LABELS: Record<string, string> = {
  portfolio: 'Carteira',
  br: 'Brasil',
  us: 'EUA',
  crypto: 'Cripto',
  rf: 'Renda fixa',
  ibov: 'IBOV',
  sp500: 'S&P 500',
}

// Same coefficient format the Sharpe card above uses — pt-BR decimal comma.
const coefFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const dayFormatter = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

interface Props {
  data: RiskReturn
  groupBy: RiskGroupBy
  onGroupByChange: (value: RiskGroupBy) => void
  periodLabel: string
}

export default function RiskReturnScatter({
  data,
  groupBy,
  onGroupByChange,
  periodLabel,
}: Props) {
  const [level, setLevel] = useState<Level>('assets')
  const [segments, setSegments] = useState<Set<string>>(() => new Set(SEGMENTS.map((s) => s.key)))
  // Lazy initialiser, not an effect: an effect comparing the initial
  // reference against itself never fires on the first render and the
  // selection would start empty (the bug the correlation explorer had).
  const sectorNames = useMemo(
    () => [...new Set(data.assets.map((a) => a.sector).filter((s): s is string => !!s))].sort(),
    [data.assets],
  )
  // Legenda clicável: cada símbolo lá embaixo liga/desliga o que ele nomeia.
  // Faixas de Sharpe filtram os ATIVOS; as chaves de carteira/benchmark
  // ligam e desligam os pontos de referência.
  const [hiddenBands, setHiddenBands] = useState<Set<string>>(() => new Set())
  const [hiddenRefs, setHiddenRefs] = useState<Set<string>>(() => new Set())
  const [sectors, setSectors] = useState<Set<string>>(() => new Set(sectorNames))
  const [knownSectors, setKnownSectors] = useState(sectorNames)
  if (knownSectors.join('|') !== sectorNames.join('|')) {
    // Reset during render when the universe itself changes (period/grouping),
    // so a sector that just appeared is not silently filtered out.
    setKnownSectors(sectorNames)
    setSectors(new Set(sectorNames))
  }

  const points = useMemo(() => {
    const source = level === 'assets' ? data.assets : data.groups
    const visibleBand = (p: RiskReturnPoint) =>
      !hiddenBands.has(sharpeBand(p.sharpe)?.label ?? '')
    if (level === 'groups') return source.filter(visibleBand)
    return source.filter(
      (p) =>
        visibleBand(p) &&
        (p.segment === null || segments.has(p.segment)) &&
        (p.sector === null || sectors.has(p.sector)),
    )
  }, [level, data.assets, data.groups, segments, sectors, hiddenBands])

  const references = useMemo(
    () =>
      [
        ...(data.portfolio ? [data.portfolio] : []),
        ...data.segments,
        ...data.benchmarks,
      ].filter(
        (p) => !hiddenRefs.has(p.kind === 'benchmark' ? 'benchmarks' : p.key),
      ),
    [data.portfolio, data.segments, data.benchmarks, hiddenRefs],
  )

  const all = [...points, ...references]
  const maxWeight = Math.max(...points.map((p) => p.weight_pct ?? 0), 0.01)
  const xDomain = ratioDomain(all.map((p) => p.volatility_annual_pct), true)
  const yDomain = ratioDomain([
    ...all.map((p) => p.return_annual_pct),
    ...(data.risk_free_annual_pct !== null ? [data.risk_free_annual_pct] : []),
  ])

  const toggle = (set: Set<string>, key: string, apply: (next: Set<string>) => void) => {
    const next = new Set(set)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    apply(next)
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-section">Risco × Retorno</p>
          <p className="mt-1 text-xs text-slate-500">
            Cada ponto é um ativo no eixo do risco que correu (volatilidade) contra o
            retorno que entregou, em {periodLabel}. Acima da linha do{' '}
            {data.risk_free_label}, bateu a renda sem risco; à esquerda, oscilou menos.
          </p>
        </div>
        <div className="flex gap-1">
          {(
            [
              ['assets', 'Ativos'],
              ['groups', groupBy === 'sector' ? 'Setores' : 'Sub-setores'],
            ] as [Level, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setLevel(key)}
              className={`rounded-md px-2 py-1 text-xs ${
                level === key ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        {level === 'assets' ? (
          <>
            <div className="flex flex-wrap gap-1">
              {SEGMENTS.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => toggle(segments, s.key, setSegments)}
                  className={`rounded-full border px-2 py-0.5 ${
                    segments.has(s.key)
                      ? 'border-slate-600 bg-slate-800 text-slate-200'
                      : 'border-slate-800 text-slate-500 line-through'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <details className="text-slate-400">
              <summary className="cursor-pointer select-none">
                Setores ({sectors.size}/{sectorNames.length})
              </summary>
              <div className="mt-2 grid max-h-40 grid-cols-2 gap-x-4 gap-y-1 overflow-y-auto pr-2 sm:grid-cols-3">
                {sectorNames.map((name) => (
                  <label key={name} className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={sectors.has(name)}
                      onChange={() => toggle(sectors, name, setSectors)}
                      className="accent-sky-500"
                    />
                    <span className="truncate">{name}</span>
                  </label>
                ))}
              </div>
            </details>
          </>
        ) : (
          <div className="flex gap-1">
            {(
              [
                ['sector', 'Setor'],
                ['subsector', 'Sub-setor'],
              ] as [RiskGroupBy, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => onGroupByChange(key)}
                className={`rounded-md px-2 py-1 ${
                  groupBy === key
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-400 hover:bg-slate-800'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 h-[540px]">
        {all.length === 0 ? (
          <SkeletonChart />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
              <CartesianGrid stroke="var(--color-slate-800)" />
              <XAxis
                type="number"
                dataKey="volatility_annual_pct"
                name="Volatilidade"
                domain={xDomain}
                tickFormatter={(v: number) => formatPercent(v)}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={{ stroke: 'var(--color-slate-700)' }}
                tickLine={false}
                label={{
                  value: 'Volatilidade anualizada',
                  position: 'insideBottom',
                  offset: -14,
                  fill: 'var(--color-slate-500)',
                  fontSize: 12,
                }}
              />
              <YAxis
                type="number"
                dataKey="return_annual_pct"
                name="Retorno"
                domain={yDomain}
                tickFormatter={(v: number) => formatPercent(v)}
                tick={{ fill: 'var(--color-slate-500)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                width={64}
                label={{
                  value: 'Retorno anualizado',
                  angle: -90,
                  position: 'insideLeft',
                  fill: 'var(--color-slate-500)',
                  fontSize: 12,
                  style: { textAnchor: 'middle' },
                }}
              />
              <ZAxis type="number" dataKey="weight_pct" range={[380, 3000]} domain={[0, maxWeight]} />
              <ReferenceLine y={0} stroke="var(--color-slate-700)" />
              {data.risk_free_annual_pct !== null && (
                <ReferenceLine
                  y={data.risk_free_annual_pct}
                  stroke="var(--color-data-cdi)"
                  strokeDasharray="4 4"
                  label={{
                    value: `${data.risk_free_label} ${formatPercent(data.risk_free_annual_pct)}`,
                    position: 'insideTopLeft',
                    fill: 'var(--color-data-cdi)',
                    fontSize: 11,
                  }}
                />
              )}
              <Tooltip
                cursor={{ strokeDasharray: '3 3', stroke: 'var(--color-slate-700)' }}
                content={<PointTooltip riskFreeLabel={data.risk_free_label} />}
              />
              <Scatter data={points} isAnimationActive={false} shape={<SharpeMark />} />
              {/* Fixed-size marks: these are anchors, not holdings, so they
                  must not ride the weight scale — the portfolio's 100% would
                  otherwise blow past the bubble domain and swamp the plot. */}
              <Scatter data={references} isAnimationActive={false} shape={<ReferenceMark />}>
                <LabelList dataKey="key" content={<ReferenceLabel />} />
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-slate-400">
        <span className="text-slate-500">Sharpe:</span>
        {SHARPE_BANDS.map((band) => (
          <LegendToggle
            key={band.label}
            label={band.label}
            active={!hiddenBands.has(band.label)}
            onClick={() => toggle(hiddenBands, band.label, setHiddenBands)}
            swatch={
              <span
                aria-hidden
                className="inline-block h-3.5 w-3.5"
                style={{
                  backgroundColor: band.color,
                  clipPath:
                    band.shape === 'down' ? 'polygon(50% 100%, 0 0, 100% 0)' : 'circle(50%)',
                }}
              />
            }
          />
        ))}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-slate-400">
        <span className="text-slate-500">Carteiras (quadrado):</span>
        <LegendToggle
          label="Total"
          active={!hiddenRefs.has('portfolio')}
          onClick={() => toggle(hiddenRefs, 'portfolio', setHiddenRefs)}
          swatch={
            <span
              aria-hidden
              className="inline-block h-3.5 w-3.5 rounded-[2px]"
              style={{ backgroundColor: 'var(--color-data-brass)' }}
            />
          }
        />
        {SEGMENTS.map((s) => (
          <LegendToggle
            key={s.key}
            label={s.label}
            active={!hiddenRefs.has(s.key)}
            onClick={() => toggle(hiddenRefs, s.key, setHiddenRefs)}
            swatch={
              <span
                aria-hidden
                className="inline-block h-3.5 w-3.5 rounded-[2px]"
                style={{ backgroundColor: SEGMENT_COLORS[s.key] }}
              />
            }
          />
        ))}
        <LegendToggle
          label="Benchmark"
          active={!hiddenRefs.has('benchmarks')}
          onClick={() => toggle(hiddenRefs, 'benchmarks', setHiddenRefs)}
          swatch={
            <span
              aria-hidden
              className="inline-block h-3 w-3 rotate-45 border-2 border-slate-400"
            />
          }
        />
      </div>

      <p className="mt-2 text-xs text-slate-500">
        Clique em qualquer símbolo da legenda para tirá-lo do gráfico. Tamanho da bolha =
        peso na carteira. Ponto esmaecido = medido em menos tempo que o resto (comprado
        dentro do período). Renda fixa privada fica fora: marcada a custo, não tem série de
        preço.
      </p>
    </div>
  )
}

/** A legend entry that is also its own filter. Off state keeps the row in
 * place (struck through, dimmed) instead of removing it, so the legend
 * never reflows under the cursor mid-click. */
function LegendToggle({
  label,
  active,
  onClick,
  swatch,
}: {
  label: string
  active: boolean
  onClick: () => void
  swatch: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-slate-800 ${
        active ? '' : 'text-slate-600 line-through'
      }`}
    >
      <span className={active ? '' : 'opacity-35'}>{swatch}</span>
      {label}
    </button>
  )
}

interface MarkProps {
  cx?: number
  cy?: number
  size?: number
  payload?: RiskReturnPoint
}

/** Anchors — the portfolio, the four segment books and the benchmarks. Fixed
 * size, since they are not holdings and would otherwise ride the weight
 * scale (the portfolio's 100% swamping every bubble around it). */
function ReferenceMark({ cx, cy, payload }: MarkProps) {
  if (cx === undefined || cy === undefined || !payload) return null
  const isPortfolio = payload.kind === 'portfolio'
  const isSegment = payload.kind === 'segment'

  // Three shape families, so what a mark *is* reads before its colour does:
  // holdings are circles/triangles, benchmarks hollow diamonds, and a
  // carteira — the whole book or one of its four segments — is a square,
  // which shares no silhouette with either of the others.
  if (isPortfolio || isSegment) {
    const half = isPortfolio ? 12 : 10
    const color = isPortfolio ? 'var(--color-data-brass)' : SEGMENT_COLORS[payload.key]
    return (
      <rect
        x={cx - half}
        y={cy - half}
        width={half * 2}
        height={half * 2}
        rx={2}
        fill={color}
        stroke="var(--color-slate-900)"
        strokeWidth={2.5}
      />
    )
  }
  const r = 9
  return (
    <polygon
      points={`${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`}
      fill="var(--color-slate-900)"
      stroke="var(--color-slate-400)"
      strokeWidth={2}
    />
  )
}

interface LabelProps {
  x?: number
  y?: number
  value?: string
  index?: number
}

function ReferenceLabel({ x, y, value }: LabelProps) {
  if (x === undefined || y === undefined || !value) return null
  return (
    <text
      x={x}
      y={y - 13}
      textAnchor="middle"
      fill="var(--color-slate-400)"
      fontSize={11}
      pointerEvents="none"
    >
      {/* The currency note and the broker name belong in the tooltip, not
          stamped on the plot next to a diamond */}
      {SHORT_LABELS[value] ?? value.replace(' (em BRL)', '').replace(/\s*\(.*\)$/, '')}
    </text>
  )
}

/** Per-point mark: colour is the Sharpe band, shape is the *sign* of the
 * Sharpe. The shape is not decoration — a 4-step red→green ramp cannot
 * separate the zero boundary by colour alone (see the token block in
 * index.css), and that boundary is the one reading that matters most. */
function SharpeMark({ cx, cy, size, payload }: MarkProps) {
  if (cx === undefined || cy === undefined || !payload) return null
  const band = sharpeBand(payload.sharpe)
  const radius = Math.max(9, Math.sqrt((size ?? 300) / Math.PI))
  const common = {
    fill: band?.color ?? 'var(--color-data-gray)',
    fillOpacity: payload.partial_window ? 0.55 : 0.9,
    stroke: 'var(--color-slate-900)', // 2px surface ring so overlaps stay readable
    strokeWidth: 2,
  }
  const code = shortCode(payload.key)
  // The ticker rides *inside* the mark once there is room for it, and drops
  // to a caption underneath when there isn't — so a small holding is still
  // named instead of silently becoming an anonymous dot.
  const insideRoom = radius >= 4 + code.length * 2.9
  const label = insideRoom ? (
    <text
      x={cx}
      y={cy + (band?.shape === 'down' ? radius * 0.34 : 0)}
      textAnchor="middle"
      dominantBaseline="central"
      fill={band?.ink ?? 'var(--color-slate-100)'}
      fontSize={Math.min(13, Math.max(9, radius * 0.62))}
      fontWeight={600}
      pointerEvents="none"
    >
      {code}
    </text>
  ) : (
    <text
      x={cx}
      y={cy + radius + 11}
      textAnchor="middle"
      fill="var(--color-slate-400)"
      fontSize={10}
      pointerEvents="none"
    >
      {code}
    </text>
  )

  if (band?.shape === 'down') {
    const side = radius * 2.3
    const points = [
      `${cx - side / 2},${cy - side * 0.42}`,
      `${cx + side / 2},${cy - side * 0.42}`,
      `${cx},${cy + side * 0.58}`,
    ].join(' ')
    return (
      <g>
        <polygon points={points} {...common} />
        {label}
      </g>
    )
  }
  return (
    <g>
      <circle cx={cx} cy={cy} r={radius} {...common} />
      {label}
    </g>
  )
}

interface TooltipProps {
  active?: boolean
  payload?: { payload: RiskReturnPoint }[]
  riskFreeLabel: string
}

function PointTooltip({ active, payload, riskFreeLabel }: TooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const p = payload[0].payload
  const band = sharpeBand(p.sharpe)
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs shadow-lg">
      <p className="font-medium text-slate-100">{p.label}</p>
      {p.key !== p.label && <p className="text-slate-500">{p.key}</p>}
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
        <dt className="text-slate-400">Volatilidade</dt>
        <dd className="text-right text-slate-200">{formatPercent(p.volatility_annual_pct)}</dd>
        <dt className="text-slate-400">Retorno anualizado</dt>
        <dd className="text-right text-slate-200">{formatSignedPercent(p.return_annual_pct)}</dd>
        {p.return_period_pct !== null && (
          <>
            <dt className="text-slate-400">Retorno no período</dt>
            <dd className="text-right text-slate-200">
              {formatSignedPercent(p.return_period_pct)}
            </dd>
          </>
        )}
        {p.sharpe !== null && (
          <>
            <dt className="text-slate-400">Sharpe (vs {riskFreeLabel})</dt>
            <dd className="text-right" style={{ color: band?.color }}>
              {coefFormatter.format(p.sharpe)}
            </dd>
          </>
        )}
        {p.weight_pct !== null && p.kind !== 'portfolio' && (
          <>
            <dt className="text-slate-400">Peso</dt>
            <dd className="text-right text-slate-200">{formatPercent(p.weight_pct)}</dd>
          </>
        )}
        <dt className="text-slate-400">Observações</dt>
        <dd className="text-right text-slate-200">{p.observations} dias</dd>
      </dl>
      {p.partial_window && p.first_date && (
        <p className="mt-1.5 max-w-56 text-amber-400">
          Medido a partir de {dayFormatter.format(new Date(`${p.first_date}T12:00:00`))} — entrou
          na carteira depois do início do período.
        </p>
      )}
    </div>
  )
}
