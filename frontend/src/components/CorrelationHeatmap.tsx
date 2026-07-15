import { cellColor, formatCoef, type HoveredCell } from '../lib/correlation'

const CELL = 28 // px

interface Props {
  tickers: string[]
  valueAt: (rowTicker: string, colTicker: string) => number | null
  showValues: boolean
  onHover: (hovered: HoveredCell | null) => void
}

export default function CorrelationHeatmap({
  tickers,
  valueAt,
  showValues,
  onHover,
}: Props) {
  return (
    <div className="overflow-auto rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="inline-block" onMouseLeave={() => onHover(null)}>
        {/* Column header labels, rotated. */}
        <div className="flex" style={{ paddingLeft: 72 }}>
          {tickers.map((ticker) => (
            <div
              key={ticker}
              style={{ width: CELL, height: 72 }}
              className="flex items-end justify-center"
            >
              <span
                className="whitespace-nowrap text-[10px] text-slate-400"
                style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
              >
                {ticker}
              </span>
            </div>
          ))}
        </div>
        {tickers.map((rowTicker) => (
          <div key={rowTicker} className="flex items-center">
            <div
              className="pr-2 text-right text-[11px] text-slate-400"
              style={{ width: 72 }}
            >
              {rowTicker}
            </div>
            {tickers.map((colTicker) => {
              const value = valueAt(rowTicker, colTicker)
              return (
                <div
                  key={colTicker}
                  onMouseEnter={() => onHover({ a: rowTicker, b: colTicker, value })}
                  title={`${rowTicker} × ${colTicker}: ${formatCoef(value)}`}
                  style={{
                    width: CELL,
                    height: CELL,
                    backgroundColor: cellColor(value),
                  }}
                  className="flex items-center justify-center border border-slate-950/60 text-[9px] text-slate-100"
                >
                  {showValues && value != null ? value.toFixed(2) : ''}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
