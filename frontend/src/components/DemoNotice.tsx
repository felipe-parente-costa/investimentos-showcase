import { useEffect, useState } from 'react'
import { getMeta } from '../api/staticDemo'

/** The first thing a visitor reads on the published showcase.
 *
 * It stays on screen instead of being dismissible: the page is public and
 * gets screenshotted and linked out of context, so the disclaimer has to
 * travel with it. The date comes from the frozen bundle itself
 * (`meta.json`, written by the prerender script), never from a constant
 * someone forgets to update. */
export default function DemoNotice() {
  const [generatedAt, setGeneratedAt] = useState<string | null>(null)

  useEffect(() => {
    getMeta()
      .then((meta) => setGeneratedAt(meta.generated_at))
      .catch(() => setGeneratedAt(null))
  }, [])

  const formatted = generatedAt
    ? new Date(`${generatedAt}T12:00:00`).toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: 'long',
        year: 'numeric',
      })
    : null

  return (
    <div className="border-b border-sky-700/60 bg-sky-500/10 px-6 py-3">
      <div className="flex flex-wrap items-baseline justify-center gap-x-3 gap-y-1 text-center">
        <p className="text-sm font-semibold text-sky-300">
          Demonstração: todas as movimentações financeiras deste portfólio são fictícias e
          fabricadas.
        </p>
        {formatted && (
          <p className="text-caption text-slate-400">Última atualização: {formatted}</p>
        )}
      </div>
    </div>
  )
}
