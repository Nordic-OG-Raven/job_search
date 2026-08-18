export const BASE_URL = "https://www.jobs.ch"

export type Lang = "en" | "de"

// jobs.ch route map (from __GLOBAL__.ROUTES) for the two locales this skill supports.
export const SEARCH_PATH: Record<Lang, string> = {
  en: "/en/vacancies/",
  de: "/de/stellenangebote/",
}

export const DETAIL_PATH: Record<Lang, string> = {
  en: "/en/vacancies/detail/",
  de: "/de/stellenangebote/detail/",
}

// jobs.ch "region" search filter IDs (from metadata-api.jobs.ch's gis/type-ahead jobs_region
// data). "central-switzerland" (jobs_id 15) covers Lucerne, Zug, Schwyz, Uri, Obwalden and
// Nidwalden as a single server-side geographic filter — no per-canton breakdown exists.
export const REGION_IDS: Record<string, string> = {
  "central-switzerland": "15",
}

export const CANTON_NAMES: Record<string, string> = {
  AG: "Aargau",
  AI: "Appenzell Innerrhoden",
  AR: "Appenzell Ausserrhoden",
  BE: "Bern",
  BL: "Basel-Landschaft",
  BS: "Basel-Stadt",
  FR: "Fribourg",
  GE: "Geneva",
  GL: "Glarus",
  GR: "Grisons",
  JU: "Jura",
  LU: "Lucerne",
  NE: "Neuchâtel",
  NW: "Nidwalden",
  OW: "Obwalden",
  SG: "St. Gallen",
  SH: "Schaffhausen",
  SO: "Solothurn",
  SZ: "Schwyz",
  TG: "Thurgau",
  TI: "Ticino",
  UR: "Uri",
  VD: "Vaud",
  VS: "Valais",
  ZG: "Zug",
  ZH: "Zurich",
}

export async function fetchHtml(url: string): Promise<{ status: number; html: string }> {
  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((resolve) => setTimeout(resolve, delay + jitter))
      delay = Math.min(delay * 2, 5000)
      continue
    }
    return { status: response.status, html: await response.text() }
  }
  throw new Error("Request failed after max retries")
}

/**
 * jobs.ch server-rendered pages embed `__INIT__ = { ... };` — a large JSON object with
 * no separate API call needed. JSON.parse can't stop at the right `}` on its own because
 * the object contains nested braces inside strings, so this walks the string tracking
 * brace depth and string/escape state to find the matching end.
 */
export function extractInitJson(html: string): Record<string, unknown> | null {
  const marker = "__INIT__ = "
  const start = html.indexOf(marker)
  if (start === -1) return null
  const jsonStart = start + marker.length
  if (html[jsonStart] !== "{") return null

  let depth = 0
  let inString = false
  let escaped = false
  for (let i = jsonStart; i < html.length; i++) {
    const ch = html[i]
    if (inString) {
      if (escaped) {
        escaped = false
      } else if (ch === "\\") {
        escaped = true
      } else if (ch === '"') {
        inString = false
      }
      continue
    }
    if (ch === '"') {
      inString = true
    } else if (ch === "{") {
      depth++
    } else if (ch === "}") {
      depth--
      if (depth === 0) {
        return JSON.parse(html.slice(jsonStart, i + 1))
      }
    }
  }
  return null
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

export function stripHtml(html: string): string {
  return html.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim()
}
