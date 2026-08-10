import { cellColor, formatCoef, type HoveredCell } from '../lib/correlation'

interface Props {
  tickers: string[]
  valueAt: (rowTicker: string, colTicker: string) => number | null
  showValues: boolean
  onHover: (hovered: HoveredCell | null) => void
  // Compact mode for side-by-side placement (e.g. next to the sector
  // heatmap) — shrinks cells and the label gutter together.
  cellSize?: number
  labelWidth?: number
}

export default function CorrelationHeatmap({
  tickers,
  valueAt,
  showValues,
  onHover,
  cellSize = 28,
  labelWidth = 72,
}: Props) {
  return (
    <div className="overflow-auto rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="inline-block" onMouseLeave={() => onHover(null)}>
        {/* Column header labels, rotated. */}
        <div className="flex" style={{ paddingLeft: labelWidth }}>
          {tickers.map((ticker) => (
            <div
              key={ticker}
              style={{ width: cellSize, height: labelWidth }}
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
              className="truncate pr-2 text-right text-[11px] text-slate-400"
              style={{ width: labelWidth }}
              title={rowTicker}
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
                    width: cellSize,
                    height: cellSize,
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
