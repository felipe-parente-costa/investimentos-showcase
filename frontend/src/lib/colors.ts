// Central color system (Fase 2 do redesign; recolorido na F4 do redesign
// "Ledger" 2026-07) — fonte ÚNICA de cor de apresentação para gráficos,
// donuts e swatches de grupos de lista.
//
// Princípio: cor é sistêmica, não tela-por-tela. Uma categoria tem sempre a
// mesma cor, em todo lugar, importando daqui (nunca uma segunda cópia que só
// "casa" visualmente).
//
// Paleta "Ledger": 6 matizes re-harmonizados para a superfície quente
// (#1b1917) e VALIDADOS por script (banda de luminosidade OKLCH dark, piso
// de croma, separação protan/deutan ΔE≥8 nos pares adjacentes, piso de visão
// normal, contraste ≥3:1) — não estimados no olho. A ordem do DONUT_PALETTE
// é o mecanismo de segurança para daltonismo: não reordenar sem revalidar.
//
// FORA daqui (de propósito): a semântica financeira ganho/perda
// (verde=positivo / vermelho=negativo) continua nos utilitários Tailwind
// `text-green-400` / `text-red-400` (recalibrados no @theme do index.css).
// A paleta abaixo é só para composição/evolução/categorias — nunca para
// sinal de lucro/prejuízo.

// A) Identidade por seção — linhas e áreas. Cada gráfico de linha/área da
// seção usa SUA cor-identidade. O Total assume o latão da marca.
export const SECTION_COLORS = {
  total: '#d9a84e', // latão — Dashboard/Total (cor de marca)
  br: '#3987e5', // azul — Brasil
  us: '#d95926', // laranja — EUA
  crypto: '#d55181', // rosa — Cripto
  rf: '#199e70', // verde-água — Renda Fixa
} as const

// C2) Donuts de domínio aberto (setor, país): 6 cores distintas por tamanho
// desc; 7ª categoria em diante colapsa em "Outros" cinza.
// ORDEM FIXA validada contra CVD — pares adjacentes maximamente distintos.
export const DONUT_PALETTE = [
  '#3987e5', // 1 azul
  '#d55181', // 2 rosa
  '#c98500', // 3 dourado
  '#199e70', // 4 verde-água
  '#d95926', // 5 laranja
  '#9085e9', // 6 violeta
] as const

export const OTHERS_COLOR = '#6e675c' // cinza quente — "Outros" / sem classificação
export const OTHERS_LABEL = 'Outros'

// C1) Cor FIXA por categoria (estável: mesma cor no donut e no swatch da lista
// de posições). Distinção garantida DENTRO de cada donut; reuso de matiz entre
// donuts diferentes é ok porque cada um é seu próprio contexto, e a legenda de
// texto do donut nomeia cada fatia.
export const CLASS_COLORS = {
  acoes: '#c98500', // Ações (BR) — dourado (mnemônico mantido do âmbar)
  fii: '#199e70', // FIIs — verde-água
  stocks: '#d95926', // Stocks (US) — laranja
  etf: '#9085e9', // ETFs / ETF Exterior — violeta
  rf: '#3987e5', // Renda Fixa — azul (mnemônico mantido do azul-aço)
  crypto: '#d55181', // Cripto — rosa (mnemônico mantido do magenta)
} as const

export const CUSTODY_COLORS: Record<string, string> = {
  binance: '#c98500', // Binance (hot) — dourado
  cold_wallet: '#3987e5', // Cold Wallet — azul
}

export const INDEXER_COLORS: Record<string, string> = {
  ipca: '#199e70', // IPCA+ — verde-água
  prefixado: '#c98500', // Pré-Fixado — dourado
  selic: '#3987e5', // SELIC/CDI — azul
}

export const CURRENCY_COLORS: Record<string, string> = {
  BRL: '#3987e5', // azul
  USD: '#c98500', // dourado (par azul×dourado é o mais seguro p/ CVD)
}

// Benchmarks (linhas tracejadas) — versão CLARA do matiz da seção que cada um
// referencia (CDI↔RF, IBOV↔Brasil, S&P↔EUA, BTC↔Cripto): a linha de referência
// "pertence" visualmente ao segmento e se distingue por luminosidade + traço.
export const BENCHMARK_COLORS: Record<string, string> = {
  cdi: '#5cc39c', // verde-água claro (par da RF)
  ibov: '#82b4ef', // azul claro (par do Brasil)
  sp500: '#ec8c5f', // laranja claro (par dos EUA)
  btc: '#e58aab', // rosa claro (par da Cripto)
}

// Cor fixa de uma classe de ativo. Ações dividem por região (`market`):
// BR=dourado, US=laranja; demais classes independem de região.
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
