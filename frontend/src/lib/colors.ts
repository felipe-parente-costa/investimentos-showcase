// Central color system (Fase 2 do redesign) — fonte ÚNICA de cor de
// apresentação para gráficos, donuts e swatches de grupos de lista.
//
// Princípio: cor é sistêmica, não tela-por-tela. Uma categoria tem sempre a
// mesma cor, em todo lugar, importando daqui (nunca uma segunda cópia que só
// "casa" visualmente).
//
// FORA daqui (de propósito): a semântica financeira ganho/perda
// (verde=positivo / vermelho=negativo) continua nos utilitários Tailwind
// `text-green-400` / `text-red-400`. A paleta abaixo é só para
// composição/evolução/categorias — nunca para sinal de lucro/prejuízo.

// A) Identidade por seção — linhas e áreas. Cada gráfico de linha/área da
// seção usa SUA cor-identidade.
export const SECTION_COLORS = {
  total: '#22d3ee', // cyan — Dashboard/Total
  br: '#fbbf24', // âmbar — Brasil
  us: '#34d399', // verde — EUA
  crypto: '#e879f9', // magenta — Cripto
  rf: '#60a5fa', // azul-aço — Renda Fixa
} as const

// C2) Donuts de domínio aberto (setor, país): 6 cores distintas por tamanho
// desc; 7ª categoria em diante colapsa em "Outros" cinza.
export const DONUT_PALETTE = [
  '#22d3ee', // 1 cyan
  '#fbbf24', // 2 âmbar
  '#e879f9', // 3 magenta
  '#34d399', // 4 verde
  '#60a5fa', // 5 azul-aço
  '#a78bfa', // 6 violeta
] as const

export const OTHERS_COLOR = '#64748b' // cinza — "Outros" / sem classificação
export const OTHERS_LABEL = 'Outros'

// C1) Cor FIXA por categoria (estável: mesma cor no donut e no swatch da lista
// de posições). Distinção garantida DENTRO de cada donut; reuso de matiz entre
// donuts diferentes é ok porque cada um é seu próprio contexto, e a legenda de
// texto do donut nomeia cada fatia.
export const CLASS_COLORS = {
  acoes: '#fbbf24', // Ações (BR) — âmbar
  fii: '#22d3ee', // FIIs — cyan
  stocks: '#34d399', // Stocks (US) — verde (mnemônico = EUA)
  etf: '#a78bfa', // ETFs / ETF Exterior — violeta
  rf: '#60a5fa', // Renda Fixa — azul-aço
  crypto: '#e879f9', // Cripto — magenta
} as const

export const CUSTODY_COLORS: Record<string, string> = {
  binance: '#fbbf24', // Binance (hot) — âmbar
  cold_wallet: '#60a5fa', // Cold Wallet — azul-aço
}

export const INDEXER_COLORS: Record<string, string> = {
  ipca: '#34d399', // IPCA+ — verde
  prefixado: '#fbbf24', // Pré-Fixado — âmbar
  selic: '#60a5fa', // SELIC/CDI — azul-aço
}

export const CURRENCY_COLORS: Record<string, string> = {
  BRL: '#22d3ee', // cyan
  USD: '#fbbf24', // âmbar
}

// Benchmarks (linhas tracejadas) — sub-paleta distinta das 5 identidades de
// seção para não colidir.
export const BENCHMARK_COLORS: Record<string, string> = {
  cdi: '#a78bfa', // violeta
  ibov: '#fb923c', // laranja
  sp500: '#fb7185', // rosa
  btc: '#facc15', // dourado
}

// Cor fixa de uma classe de ativo. Ações dividem por região (`market`):
// BR=âmbar, US=verde; demais classes independem de região.
export function classColor(assetClass: string, market?: string): string {
  switch (assetClass) {
    case 'stock':
      return market === 'us' ? CLASS_COLORS.stocks : CLASS_COLORS.acoes
    case 'fii':
      return CLASS_COLORS.fii
    case 'etf':
      return CLASS_COLORS.etf
    case 'fixed_income':
      return CLASS_COLORS.rf
    case 'crypto':
      return CLASS_COLORS.crypto
    default:
      return OTHERS_COLOR
  }
}
