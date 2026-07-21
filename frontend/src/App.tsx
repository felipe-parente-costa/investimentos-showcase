import { useEffect, useState } from 'react'
import Correlacao from './pages/Correlacao'
import Dashboard from './pages/Dashboard'
import Import from './pages/Import'
import Lancamentos from './pages/Lancamentos'
import Mercado from './pages/Mercado'
import Relatorios from './pages/Relatorios'
import Segmento, { type SegmentKey } from './pages/Segmento'
import { applyTheme, getStoredTheme, type Theme } from './lib/theme'

type Page =
  | 'dashboard'
  | 'br'
  | 'us'
  | 'crypto'
  | 'rf'
  | 'lancamentos'
  | 'correlacao'
  | 'relatorios'
  | 'mercado'
  | 'import'

const SEGMENT_PAGES: SegmentKey[] = ['br', 'us', 'crypto', 'rf']

// Nav agrupada (F5): visão geral · carteiras · análise · operações.
// O separador entre grupos reflete a hierarquia real de uso; dentro de
// cada grupo a ordem é a mesma de antes.
const NAV_GROUPS: { value: Page; label: string }[][] = [
  [{ value: 'dashboard', label: 'Visão geral' }],
  [
    { value: 'br', label: 'Brasil' },
    { value: 'rf', label: 'Renda Fixa' },
    { value: 'us', label: 'EUA' },
    { value: 'crypto', label: 'Cripto' },
  ],
  [
    { value: 'mercado', label: 'Mercado' },
    { value: 'correlacao', label: 'Correlação' },
    { value: 'relatorios', label: 'Relatórios' },
  ],
  [
    { value: 'lancamentos', label: 'Lançamentos' },
    { value: 'import', label: 'Importar' },
  ],
]

export default function App() {
  // Abre na visão geral (F5): o dashboard é o resumo; Mercado é contexto.
  const [page, setPage] = useState<Page>('dashboard')
  const [theme, setTheme] = useState<Theme>(getStoredTheme)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-6 border-b border-slate-800 px-6 py-4">
        <h1 className="flex items-center gap-2.5 font-display text-xl font-semibold">
          {/* Marca "Ledger": camadas em base estável + ponto-patrimônio
              (mesmo desenho do favicon.svg, sem o tile). */}
          <svg
            width="22"
            height="22"
            viewBox="0 0 44 44"
            aria-hidden="true"
            className="shrink-0"
          >
            <rect x="8" y="30" width="28" height="5" rx="2.5" fill="var(--color-sky-500)" />
            <rect x="12" y="21" width="20" height="5" rx="2.5" fill="var(--color-sky-500)" opacity=".78" />
            <rect x="16" y="12" width="12" height="5" rx="2.5" fill="var(--color-sky-500)" opacity=".55" />
            <circle cx="22" cy="7" r="2.6" fill="var(--color-slate-100)" />
          </svg>
          Lastro
        </h1>
        <nav className="flex flex-wrap items-center gap-x-1">
          {NAV_GROUPS.map((group, index) => (
            <div key={group[0].value} className="flex items-center gap-x-1">
              {index > 0 && (
                <span aria-hidden="true" className="mx-1.5 select-none text-slate-700">
                  ·
                </span>
              )}
              {group.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setPage(item.value)}
                  className={`border-b-2 px-2 py-1.5 text-sm transition-colors ${
                    page === item.value
                      ? 'border-sky-500 text-slate-100'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="ml-auto flex gap-1 rounded-lg border border-slate-700 bg-slate-950 p-1 text-xs">
          {(
            [
              ['dark', 'Ledger'],
              ['light', 'Papel'],
            ] as [Theme, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setTheme(value)}
              title={value === 'dark' ? 'Tema escuro' : 'Tema claro'}
              className={`rounded-md px-3 py-1 font-medium ${
                theme === value
                  ? 'bg-sky-600 text-inkbrass'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>
      {/* Each page mounts fresh on navigation, so the dashboard refetches
          the portfolio after an import without any extra wiring. */}
      {page === 'dashboard' && <Dashboard />}
      {SEGMENT_PAGES.includes(page as SegmentKey) && (
        <Segmento key={page} segment={page as SegmentKey} />
      )}
      {page === 'lancamentos' && <Lancamentos />}
      {page === 'correlacao' && <Correlacao />}
      {page === 'relatorios' && <Relatorios />}
      {page === 'mercado' && <Mercado />}
      {page === 'import' && <Import onGoToDashboard={() => setPage('dashboard')} />}
    </div>
  )
}
