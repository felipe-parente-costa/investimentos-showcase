import type { ReactNode } from 'react'
import type { RiskOverall } from '../api/client'
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

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
        {title}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{children}</div>
    </div>
  )
}

interface Props {
  overall: RiskOverall
  periodLabel: string
}

export default function RiskSummaryCards({ overall, periodLabel }: Props) {
  const o = overall
  const notEnoughData = o.observations < 20

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

      <Group title="Perdas extremas (1 dia)">
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
        <Metric label="VaR histórico 95%">
          <span className={lossColor(o.var_hist_95_pct)}>
            {o.var_hist_95_pct != null ? formatPercent(o.var_hist_95_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR histórico 99%">
          <span className={lossColor(o.var_hist_99_pct)}>
            {o.var_hist_99_pct != null ? formatPercent(o.var_hist_99_pct) : '—'}
          </span>
        </Metric>
        <Metric label="CVaR 95%" hint="perda média além do VaR">
          <span className={lossColor(o.cvar_hist_95_pct)}>
            {o.cvar_hist_95_pct != null ? formatPercent(o.cvar_hist_95_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR paramétrico 95%" hint="normal">
          <span className={lossColor(o.var_parametric_95_pct)}>
            {o.var_parametric_95_pct != null ? formatPercent(o.var_parametric_95_pct) : '—'}
          </span>
        </Metric>
        <Metric label="VaR 95% em R$">
          <span className={lossColor(o.var_hist_95_brl != null ? Number(o.var_hist_95_brl) : null)}>
            {o.var_hist_95_brl != null ? formatMoney(o.var_hist_95_brl) : '—'}
          </span>
        </Metric>
        <Metric label="CVaR 95% em R$">
          <span
            className={lossColor(o.cvar_hist_95_brl != null ? Number(o.cvar_hist_95_brl) : null)}
          >
            {o.cvar_hist_95_brl != null ? formatMoney(o.cvar_hist_95_brl) : '—'}
          </span>
        </Metric>
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
