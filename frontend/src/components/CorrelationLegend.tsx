import { formatCoef, type HoveredCell } from '../lib/correlation'

// Shared by every correlation heatmap panel (assets, sectors/sub-setores,
// top-10) — the -1..+1 gradient key plus the hovered-cell readout. Kept in
// one place so a future tweak (color thresholds, gradient stops) doesn't
// need to be repeated per panel.
export default function CorrelationLegend({ hovered }: { hovered: HoveredCell | null }) {
  return (
    <div className="flex items-center gap-4 text-xs text-slate-400">
      <div className="flex items-center gap-2">
        <span>-1</span>
        <div className="h-2.5 w-32 rounded bg-gradient-to-r from-red-500 via-slate-700 to-green-500" />
        <span>+1</span>
      </div>
      <div className="min-h-4 font-medium text-slate-200">
        {hovered && (
          <span>
            {hovered.a} × {hovered.b}:{' '}
            <span
              className={
                hovered.value == null
                  ? 'text-slate-500'
                  : hovered.value >= 0
                    ? 'text-green-400'
                    : 'text-red-400'
              }
            >
              {formatCoef(hovered.value)}
            </span>
          </span>
        )}
      </div>
    </div>
  )
}
