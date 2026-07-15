import type { PortfolioResponse } from '../api/client'
import { formatMoney, formatSignedPercent } from '../lib/format'

export interface MonthChange {
  brl: number
  pct: number | null
}

interface Props {
  portfolio: PortfolioResponse
  twrIndex: string | null
  monthChange: MonthChange | null
}

function changeColor(value: number): string {
  if (value > 0) return 'text-green-400'
  if (value < 0) return 'text-red-400'
  return 'text-slate-300'
}

export default function SummaryCards({ portfolio, twrIndex, monthChange }: Props) {
  const anyStale =
    portfolio.fx_stale || portfolio.positions.some((p) => p.quote_stale)
  const dayChange =
    portfolio.day_change_brl != null ? Number(portfolio.day_change_brl) : null
  const twrTotal = twrIndex != null ? (Number(twrIndex) - 100) / 100 : null

  return (
    <div className="space-y-6">
      {/* Herói: o número mais importante do app, sozinho e em destaque máximo. */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <p className="text-caption text-slate-400">Patrimônio total</p>
        <p className="mt-1 text-hero">
          {formatMoney(portfolio.total_market_value_brl)}
        </p>
        {dayChange != null && (
          <p
            className={`mt-2 text-body tabular-nums ${changeColor(dayChange)}`}
            title="BR e Tesouro: variação sobre o fechamento anterior; EUA e Cripto: intradiário (5 min)"
          >
            {dayChange > 0 && '+'}
            {formatMoney(portfolio.day_change_brl)}
            {portfolio.day_change_pct != null &&
              ` (${formatSignedPercent(Number(portfolio.day_change_pct))})`}
            <span className="text-slate-500"> última sessão</span>
          </p>
        )}
        <p className="mt-2 text-caption text-slate-500">
          {portfolio.positions.length} posições abertas
          {portfolio.usd_brl_rate && ` · PTAX ${formatMoney(portfolio.usd_brl_rate)}`}
        </p>
        {anyStale && (
          <p className="mt-1 text-caption text-amber-400">Cotações desatualizadas</p>
        )}
      </div>

      {/* Métricas secundárias: peso menor que o herói. Largura limitada para o
          trio não esticar com vazio à direita dos números. */}
      <div className="grid grid-cols-3 gap-6 sm:max-w-2xl">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <p className="text-caption text-slate-400">Rentabilidade total (TWR)</p>
          {twrTotal == null ? (
            <p className="mt-1 text-xl font-semibold text-slate-500">—</p>
          ) : (
            <p
              className={`mt-1 text-xl font-semibold tabular-nums ${changeColor(twrTotal)}`}
            >
              {formatSignedPercent(twrTotal)}
            </p>
          )}
          <p className="mt-1 text-caption text-slate-500">desde o início</p>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <p className="text-caption text-slate-400">Variação no mês</p>
          {monthChange == null ? (
            <p className="mt-1 text-xl font-semibold text-slate-500">—</p>
          ) : (
            <>
              <p
                className={`mt-1 text-xl font-semibold tabular-nums ${changeColor(monthChange.brl)}`}
              >
                {monthChange.brl > 0 && '+'}
                {formatMoney(String(monthChange.brl))}
              </p>
              <p className="mt-1 text-caption text-slate-500">
                {monthChange.pct != null
                  ? `${formatSignedPercent(monthChange.pct)} no mês`
                  : 'no mês'}
              </p>
            </>
          )}
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <p className="text-caption text-slate-400">Dividendos no ano</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-green-400">
            {formatMoney(portfolio.income_ytd_brl)}
          </p>
          <p className="mt-1 text-caption text-slate-500">
            dividendos, JCP e rendimentos
          </p>
        </div>
      </div>
    </div>
  )
}
