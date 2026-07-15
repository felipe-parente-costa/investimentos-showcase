import { useState } from 'react'
import Correlacao from './pages/Correlacao'
import Dashboard from './pages/Dashboard'
import Import from './pages/Import'
import Lancamentos from './pages/Lancamentos'
import Mercado from './pages/Mercado'
import Relatorios from './pages/Relatorios'
import Segmento, { type SegmentKey } from './pages/Segmento'

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

const PAGES: { value: Page; label: string }[] = [
  { value: 'dashboard', label: 'Dashboard' },
  { value: 'br', label: 'Brasil' },
  { value: 'rf', label: 'Renda Fixa' },
  { value: 'us', label: 'EUA' },
  { value: 'crypto', label: 'Cripto' },
  { value: 'mercado', label: 'Mercado' },
  { value: 'correlacao', label: 'Correlação' },
  { value: 'relatorios', label: 'Relatórios' },
  { value: 'lancamentos', label: 'Lançamentos' },
  { value: 'import', label: 'Importar' },
]

export default function App() {
  const [page, setPage] = useState<Page>('mercado')

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex items-center gap-6 border-b border-slate-800 px-6 py-4">
        <h1 className="text-xl font-semibold">Investimentos</h1>
        <nav className="flex gap-1">
          {PAGES.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setPage(item.value)}
              className={`rounded-lg px-3 py-1.5 text-sm ${
                page === item.value
                  ? 'bg-slate-800 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800/60'
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
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
