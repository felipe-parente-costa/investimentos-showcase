import { useState, type ReactNode } from 'react'
import type { RiskOverall, VarHorizon } from '../api/client'
import { formatMoney, formatPercent } from '../lib/format'

const coefFormatter = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const intFormatter = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })

const dateFormatter = new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC' })

function fmtDate(iso: string): string {
  return dateFormatter.format(new Date(`${iso}T12:00:00Z`))
}

// Losses (drawdown/VaR/CVaR) are always <= 0 by construction — red is the
// correct semantic color unconditionally, not a sign check.
function lossColor(value: number | null): string {
  if (value == null) return 'text-slate-500'
  return value < 0 ? 'text-red-400' : 'text-slate-200'
}

function signedColor(value: number | null): string {
  if (value == null || value === 0) return 'text-slate-200'
  return value > 0 ? 'text-green-400' : 'text-red-400'
}

function Metric({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{children}</p>
      {hint && <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p>}
    </div>
  )
}

function Group({
  title,
  children,
  headerRight,
}: {
  title: string
  children: ReactNode
  headerRight?: ReactNode
}) {
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {title}
        </p>
        {headerRight}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{children}</div>
    </div>
  )
}

interface Props {
  overall: RiskOverall
  periodLabel: string
  varHorizons: VarHorizon[]
}

export default function RiskSummaryCards({ overall, periodLabel, varHorizons }: Props) {
  const o = overall
  const notEnoughData = o.observations < 20
  // Horizon (how long the loss has to happen in) is a different knob from
  // the window above (how much history feeds the estimate). Default 1 day.
  const [horizonDays, setHorizonDays] = useState(1)
  const horizon = varHorizons.find((h) => h.days === horizonDays) ?? varHorizons[0]
  const v = horizon ?? {
    var_hist_95_pct: o.var_hist_95_pct,
    var_hist_99_pct: o.var_hist_99_pct,
    cvar_hist_95_pct: o.cvar_hist_95_pct,
    var_hist_95_brl: o.var_hist_95_brl,
    cvar_hist_95_brl: o.cvar_hist_95_brl,
  }

  return (
    <div className="space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-section">Risco da carteira consolidada</p>
        <p className="text-xs text-slate-500">
          Janela: {periodLabel} · {o.observations} retornos diários
          {o.total_value_brl != null && ` · ${formatMoney(o.total_value_brl)}`}
        </p>
      </div>

      {notEnoughData && (
        <p className="rounded-md border border-amber-900/60 bg-amber-950/20 px-3 py-2 text-xs text-amber-300">
          Poucos retornos diários nesta janela (mínimo 20) — volatilidade, Sharpe, Sortino,
          VaR/CVaR, beta e tracking error ficam indisponíveis até haver histórico suficiente.
        </p>
      )}

      <Group title="Risco e retorno ajustado">
        <Metric label="Volatilidade anualizada">
          {o.volatility_annual_pct != null ? formatPercent(o.volatility_annual_pct) : '—'}
        </Metric>
        <Metric label="Sharpe" hint="vs. CDI">
          <span className={signedColor(o.sharpe)}>
            {o.sharpe != null ? coefFormatter.format(o.sharpe) : '—'}
          </span>
        </Metric>
        <Metric label="Sortino" hint="vs. CDI, downside">
          <span className={signedColor(o.sortino)}>
            {o.sortino != null ? coefFormatter.format(o.sortino) : '—'}
          </span>
        </Metric>
      </Group>

      <Group
        title="Perdas extremas (dia de negociação)"
        headerRight={
          varHorizons.length > 0 ? (
            <div className="flex items-center gap-1">
              <span className="text-[11px] normal-case text-slate-500">Horizonte:</span>
              {varHorizons.map((h) => (
                <button
                  key={h.days}
                  type="button"
                  onClick={() => setHorizonDays(h.days)}
                  className={`rounded-md px-2 py-0.5 text-[11px] ${
                    horizonDays === h.days
                      ? 'bg-slate-700 text-slate-100'
                      : 'text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  {h.label}
                </button>
              ))}
            </div>
          ) : undefined
        }
      >
        <Metric
          label="Máx. drawdown"
          hint={
            o.max_drawdown_date
              ? `fundo em ${fmtDate(o.max_drawdown_date)}${
                  o.max_drawdown_duration_days != null
                    ? ` · ${o.max_drawdown_duration_days}d do pico ao fundo`
                    : ''
                }`
              : undefined
          }
        >
          <span className={lossColor(o.max_drawdown_pct)}>
            {o.max_drawdown_pct != null ? formatPercent(o.max_drawdown_pct) : '—'}
          </span>
        </Metric>
        <Metric
          label="Drawdown atual"
          hint={
            o.current_drawdown_days != null
              ? o.current_drawdown_days > 0
                ? `${o.current_drawdown_days}d em queda desde o pico`
                : 'no pico da série'
              : undefined
          }
        >
          <span className={lossColor(o.current_drawdown_pct)}>
            {o.current_drawdown_pct != null ? formatPercent(o.current_drawdown_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR histórico 95%" hint={horizon?.label}>
          <span className={lossColor(v.var_hist_95_pct)}>
            {v.var_hist_95_pct != null ? formatPercent(v.var_hist_95_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR histórico 99%" hint={horizon?.label}>
          <span className={lossColor(v.var_hist_99_pct)}>
            {v.var_hist_99_pct != null ? formatPercent(v.var_hist_99_pct) : '—'}
          </span>
        </Metric>
        <Metric label="CVaR 95%" hint="perda média além do VaR">
          <span className={lossColor(v.cvar_hist_95_pct)}>
            {v.cvar_hist_95_pct != null ? formatPercent(v.cvar_hist_95_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR paramétrico 95%" hint="normal">
          <span className={lossColor(o.var_parametric_95_pct)}>
            {o.var_parametric_95_pct != null ? formatPercent(o.var_parametric_95_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR 95% em R$" hint={horizon?.label}>
          <span className={lossColor(v.var_hist_95_brl != null ? Number(v.var_hist_95_brl) : null)}>
            {v.var_hist_95_brl != null ? formatMoney(v.var_hist_95_brl) : '—'}
          </span>
        </Metric>
        <Metric label="CVaR 95% em R$" hint={horizon?.label}>
          <span
            className={lossColor(v.cvar_hist_95_brl != null ? Number(v.cvar_hist_95_brl) : null)}
          >
            {v.cvar_hist_95_brl != null ? formatMoney(v.cvar_hist_95_brl) : '—'}
          </span>
        </Metric>
        <p className="col-span-2 text-[11px] text-slate-500 sm:col-span-3 lg:col-span-4">
          VaR, CVaR, assimetria e curtose usam os {o.trading_observations} dias de
          negociação da janela, não os {o.observations} dias corridos: "um dia" num
          relatório de risco é um dia de pregão, e incluir fim de semana empurra o
          quantil para o meio da distribuição. Volatilidade e Sharpe acima seguem na
          série cheia — lá o fim de semana carrega retorno de cripto que não pode ser
          descartado.
        </p>
        {horizonDays > 1 && (
          <p className="col-span-2 text-[11px] text-slate-500 sm:col-span-3 lg:col-span-4">
            Horizonte de {horizon?.label} pela regra da raiz do tempo (VaR₁ × √{horizonDays}),
            que supõe retornos independentes e ignora a tendência — vale para poucos dias,
            não para meses longos. A perda de 1 dia é a medida direta.
          </p>
        )}
      </Group>

      <Group title="Sensibilidade a mercado">
        <Metric label="Beta vs. IBOV">
          {o.beta_ibov != null ? coefFormatter.format(o.beta_ibov) : '—'}
        </Metric>
        <Metric label="Beta vs. S&P 500">
          {o.beta_sp500 != null ? coefFormatter.format(o.beta_sp500) : '—'}
        </Metric>
        <Metric label="Tracking error" hint="vs. CDI">
          {o.tracking_error_cdi_pct != null ? formatPercent(o.tracking_error_cdi_pct) : '—'}
        </Metric>
      </Group>

      <Group title="Concentração e exposição">
        <Metric label="Nº efetivo de posições" hint="1 / HHI">
          {o.effective_positions != null ? intFormatter.format(o.effective_positions) : '—'}
        </Metric>
        <Metric label="Top 5 posições">
          {o.top5_concentration_pct != null ? formatPercent(o.top5_concentration_pct) : '—'}
        </Metric>
        <Metric
          label="Índice de diversificação"
          hint="1,0 = sem benefício; maior = melhor"
        >
          {o.diversification_ratio != null ? coefFormatter.format(o.diversification_ratio) : '—'}
        </Metric>
        <Metric label="HHI por instituição" hint="risco de custódia">
          {o.hhi_institution != null ? coefFormatter.format(o.hhi_institution) : '—'}
        </Metric>
        <Metric label="Exposição direta a USD">
          {o.usd_direct_exposure_pct != null ? formatPercent(o.usd_direct_exposure_pct) : '—'}
        </Metric>
      </Group>
    </div>
  )
}
