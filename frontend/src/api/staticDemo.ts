// Reading the frozen demo instead of an API.
//
// The published showcase has no backend: `scripts/prerender_static_demo.py`
// writes every response the UI can ask for into public/data, and this module
// resolves a request to one of those files. That is what makes the public
// page free of write endpoints, servers and cost.
//
// Two endpoints are too large to enumerate, so they are frozen as a superset
// and narrowed here, in the browser:
//
// - the returns chart toggles five segments and six benchmarks
//   independently, which is 2^11 combinations per period and currency;
// - the transactions list filters, sorts and pages over 371 rows.
//
// Everything else is a closed list and maps one to one.

export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === 'true'

const DATA = `${import.meta.env.BASE_URL}data`

const ALL_SEGMENTS = 'total,br,us,crypto,rf'
const ALL_BENCHMARKS = 'cdi,ibov,sp500,btc,ipca6,dolar5'

export interface DemoMeta {
  generated_at: string
  data_through: string | null
  positions: number
}

/** Mirror of `slug()` in the prerender script: path plus sorted query, with
 *  every run of non-alphanumerics collapsed to a dash. */
function slug(path: string, query: string): string {
  let raw = path.replace(/^\/+|\/+$/g, '')
  if (query) raw += '--' + query.split('&').sort().join('&')
  return raw.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '') + '.json'
}

async function readFile<T>(name: string): Promise<T> {
  const response = await fetch(`${DATA}/${name}`)
  if (!response.ok) {
    throw new Error(
      `demo estático: falta o arquivo ${name} — regenere com scripts/prerender_static_demo.py`,
    )
  }
  return (await response.json()) as T
}

export function getMeta(): Promise<DemoMeta> {
  return readFile<DemoMeta>('meta.json')
}

type Series = { key?: string }

async function returnsFor(params: URLSearchParams): Promise<unknown> {
  const period = params.get('period') ?? '1A'
  const currency = params.get('currency') ?? 'BRL'
  const full = await readFile<{ series?: Series[] }>(
    slug(
      '/portfolio/returns',
      `segments=${ALL_SEGMENTS}&benchmarks=${ALL_BENCHMARKS}&period=${period}&currency=${currency}`,
    ),
  )
  const wanted = new Set(
    [...(params.get('segments') ?? '').split(','), ...(params.get('benchmarks') ?? '').split(',')]
      .map((k) => k.trim())
      .filter(Boolean),
  )
  return { ...full, series: (full.series ?? []).filter((s) => !s.key || wanted.has(s.key)) }
}

type Row = Record<string, unknown>

async function transactionsFor(params: URLSearchParams): Promise<unknown> {
  const all = await readFile<{ items: Row[]; total: number }>(
    slug('/transactions', 'limit=100000&offset=0'),
  )
  let items = all.items

  const equals = (row: Row, field: string, value: string) =>
    String(row[field] ?? '').toLowerCase() === value.toLowerCase()
  const ticker = params.get('ticker')
  if (ticker) {
    const needle = ticker.toLowerCase()
    items = items.filter((r) => String(r.ticker ?? '').toLowerCase().includes(needle))
  }
  for (const field of ['source', 'operation'] as const) {
    const value = params.get(field)
    if (value) items = items.filter((r) => equals(r, field, value))
  }
  const from = params.get('date_from')
  if (from) items = items.filter((r) => String(r.date) >= from)
  const to = params.get('date_to')
  if (to) items = items.filter((r) => String(r.date) <= to)

  const sort = params.get('sort') ?? 'date'
  const order = params.get('order') ?? 'desc'
  const direction = order === 'asc' ? 1 : -1
  items = [...items].sort((a, b) => {
    const left = a[sort] as string | number
    const right = b[sort] as string | number
    const numeric = Number(left)
    const otherNumeric = Number(right)
    if (!Number.isNaN(numeric) && !Number.isNaN(otherNumeric) && left !== '' && right !== '') {
      return (numeric - otherNumeric) * direction
    }
    return String(left ?? '').localeCompare(String(right ?? '')) * direction
  })

  const total = items.length
  const offset = Number(params.get('offset') ?? 0)
  const limit = Number(params.get('limit') ?? 50)
  return { items: items.slice(offset, offset + limit), total }
}

/** Resolves a GET the app would have sent to the API. Anything that writes
 *  never reaches here: the demo hides those actions. */
export async function staticRequest<T>(path: string, method: string): Promise<T> {
  if (method !== 'GET') {
    throw new Error('Esta é uma demonstração estática: não há backend para gravar dados.')
  }
  const [bare, query = ''] = path.split('?')
  const params = new URLSearchParams(query)

  if (bare === '/portfolio/returns') return (await returnsFor(params)) as T
  if (bare === '/transactions') return (await transactionsFor(params)) as T
  // `refresh=true` only tells a live backend to skip its cache.
  params.delete('refresh')
  const normalized = params.toString()
  return readFile<T>(slug(bare, normalized ? decodeURIComponent(normalized) : ''))
}
