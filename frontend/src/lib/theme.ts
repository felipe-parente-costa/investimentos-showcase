export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'lastro-theme'

// Manual toggle only (no prefers-color-scheme auto-follow) — dark "Ledger"
// is the default identity; light "Papel" is an opt-in the user remembers
// choosing, not something that should flip under them via OS settings.
export function getStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  return window.localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  window.localStorage.setItem(STORAGE_KEY, theme)
}
