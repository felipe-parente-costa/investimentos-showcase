// Pulsing placeholder primitive, used in place of "Carregando…" text while
// the first fetch of a page/chart is in flight. Purely visual — no logic.
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-slate-800 ${className}`} />
}

// Placeholder for the common summary-card shape (rounded-xl border p-5, a
// label line + a big value line + a hint line) used across Dashboard,
// Segmento and Mercado.
export function SkeletonCard() {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="mt-3 h-7 w-32" />
      <Skeleton className="mt-2 h-3 w-24" />
    </div>
  )
}

// Placeholder for a fixed-height chart container — fills the parent, which
// already carries the real chart's height class (h-64/h-72/h-80…).
export function SkeletonChart() {
  return <Skeleton className="h-full w-full" />
}

// Placeholder for a PositionsTable/PositionsSection-shaped block: a header
// bar plus a handful of row bars.
export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900 p-4">
      <Skeleton className="h-4 w-28" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  )
}
