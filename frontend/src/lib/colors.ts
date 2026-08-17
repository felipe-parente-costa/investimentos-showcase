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

// Valores como var(--color-data-*) (definidas no @theme do index.css), não
// hex direto: o MESMO arquivo reteme sozinho entre os temas claro/escuro (a
// variável resolve para o valor certo no navegador) sem tocar nenhum
// consumidor — idêntico ao mecanismo já usado pelos tokens slate/sky.

// A) Identidade por seção — linhas e áreas. Cada gráfico de linha/área da
// seção usa SUA cor-identidade. O Total assume o latão da marca.
export const SECTION_COLORS = {
  total: 'var(--color-data-brass)', // latão — Dashboard/Total (cor de marca)
  br: 'var(--color-data-blue)', // azul — Brasil
  us: 'var(--color-data-orange)', // laranja — EUA
  crypto: 'var(--color-data-pink)', // rosa — Cripto
  rf: 'var(--color-data-teal)', // verde-água — Renda Fixa
} as const

// C2) Donuts de domínio aberto (setor, país): 6 cores distintas por tamanho
// desc; 7ª categoria em diante colapsa em "Outros" cinza.
// ORDEM FIXA validada contra CVD — pares adjacentes maximamente distintos.
export const DONUT_PALETTE = [
  'var(--color-data-blue)', // 1 azul
  'var(--color-data-pink)', // 2 rosa
  'var(--color-data-gold)', // 3 dourado
  'var(--color-data-teal)', // 4 verde-água
  'var(--color-data-orange)', // 5 laranja
  'var(--color-data-violet)', // 6 violeta
] as const

export const OTHERS_COLOR = 'var(--color-data-gray)' // cinza quente — "Outros" / sem classificação
export const OTHERS_LABEL = 'Outros'

// C1) Cor FIXA por categoria (estável: mesma cor no donut e no swatch da lista
// de posições). Distinção garantida DENTRO de cada donut; reuso de matiz entre
// donuts diferentes é ok porque cada um é seu próprio contexto, e a legenda de
// texto do donut nomeia cada fatia.
export const CLASS_COLORS = {
  acoes: 'var(--color-data-gold)', // Ações (BR) — dourado (mnemônico mantido do âmbar)
  fii: 'var(--color-data-teal)', // FIIs — verde-água
  stocks: 'var(--color-data-orange)', // Stocks (US) — laranja
  etf: 'var(--color-data-violet)', // ETFs / ETF Exterior — violeta
  rf: 'var(--color-data-blue)', // Renda Fixa — azul (mnemônico mantido do azul-aço)
  crypto: 'var(--color-data-pink)', // Cripto — rosa (mnemônico mantido do magenta)
} as const

export const CUSTODY_COLORS: Record<string, string> = {
  binance: 'var(--color-data-gold)', // Binance (hot) — dourado
  cold_wallet: 'var(--color-data-blue)', // Cold Wallet — azul
}

export const INDEXER_COLORS: Record<string, string> = {
  ipca: 'var(--color-data-teal)', // IPCA+ — verde-água
  prefixado: 'var(--color-data-gold)', // Pré-Fixado — dourado
  selic: 'var(--color-data-blue)', // SELIC/CDI — azul
}

export const CURRENCY_COLORS: Record<string, string> = {
  BRL: 'var(--color-data-blue)', // azul
  USD: 'var(--color-data-gold)', // dourado (par azul×dourado é o mais seguro p/ CVD)
}

// Benchmarks (linhas tracejadas) — versão CLARA do matiz da seção que cada um
// referencia (CDI↔RF, IBOV↔Brasil, S&P↔EUA, BTC↔Cripto): a linha de referência
// "pertence" visualmente ao segmento e se distingue por luminosidade + traço no
// escuro; no claro (onde "mais claro" desapareceria contra a página) a mesma
// variável passa a ser uma versão dessaturada/acinzentada do matiz — o traço
// tracejado vira o principal diferenciador de linha ali. IPCA+6 e Dólar+5 não
// têm seção-par (são referências macro, não segmentos da carteira); usam os
// dois matizes restantes da paleta de 6 (dourado, violeta) — validados junto
// dos 4 existentes via validate_palette.js (mesmo pior par ΔE do conjunto já
// aprovado, sem degradação: dark 10.2 e58aab↔ec8c5f, light 6.3 c98fa0↔c99a7f).
export const BENCHMARK_COLORS: Record<string, string> = {
  cdi: 'var(--color-data-cdi)', // par da RF
  ibov: 'var(--color-data-ibov)', // par do Brasil
  sp500: 'var(--color-data-sp500)', // par dos EUA
  btc: 'var(--color-data-btc)', // par da Cripto
  ipca6: 'var(--color-data-ipca6)', // dourado — sem seção-par
  dolar5: 'var(--color-data-dolar5)', // violeta — sem seção-par
}

// Faixas de Sharpe do gráfico Risco × Retorno. Escala de ESTADO (ruim -> bom),
// não de categoria: por isso fica fora do DONUT_PALETTE e nunca é usada como
// identidade de série. A `shape` não é decoração — é a codificação secundária
// obrigatória: uma rampa vermelho->verde de 4 degraus não separa a fronteira
// do zero nem para visão normal (ΔE 2,2 no par laranja×oliva do tema claro),
// e é exatamente essa fronteira que a forma resolve. Ver o bloco de tokens no
// index.css para os números da validação.
export const SHARPE_BANDS = [
  { min: -Infinity, max: 0, color: 'var(--color-sharpe-neg)', ink: 'var(--color-sharpe-neg-ink)', shape: 'down' as const, label: 'abaixo de 0' },
  { min: 0, max: 0.5, color: 'var(--color-sharpe-low)', ink: 'var(--color-sharpe-low-ink)', shape: 'circle' as const, label: '0 a 0,5' },
  { min: 0.5, max: 1, color: 'var(--color-sharpe-mid)', ink: 'var(--color-sharpe-mid-ink)', shape: 'circle' as const, label: '0,5 a 1' },
  { min: 1, max: Infinity, color: 'var(--color-sharpe-high)', ink: 'var(--color-sharpe-high-ink)', shape: 'circle' as const, label: '1 ou mais' },
] as const

export type SharpeBand = (typeof SHARPE_BANDS)[number]

export function sharpeBand(sharpe: number | null): SharpeBand | null {
  if (sharpe === null) return null
  return SHARPE_BANDS.find((b) => sharpe >= b.min && sharpe < b.max) ?? null
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
