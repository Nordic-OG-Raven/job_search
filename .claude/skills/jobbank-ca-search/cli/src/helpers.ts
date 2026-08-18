export const BASE_URL = "https://www.jobbank.gc.ca"

export const SEARCH_PATH = "/jobsearch/jobsearch"

export const DETAIL_PATH = "/jobsearch/jobposting/"

// Job Bank's "fprov" search filter — real server-side province/territory filter
// (verified: changing it changes the total result count, and every result's
// location ends in "(<code>)"). Lowercase keys are the CLI's --province values.
export const PROVINCES: Record<string, string> = {
  ab: "AB",
  bc: "BC",
  mb: "MB",
  nb: "NB",
  nl: "NL",
  ns: "NS",
  nt: "NT",
  nu: "NU",
  on: "ON",
  pe: "PE",
  qc: "QC",
  sk: "SK",
  yt: "YT",
}

export const PROVINCE_NAMES: Record<string, string> = {
  AB: "Alberta",
  BC: "British Columbia",
  MB: "Manitoba",
  NB: "New Brunswick",
  NL: "Newfoundland and Labrador",
  NS: "Nova Scotia",
  NT: "Northwest Territories",
  NU: "Nunavut",
  ON: "Ontario",
  PE: "Prince Edward Island",
  QC: "Quebec",
  SK: "Saskatchewan",
  YT: "Yukon",
}

export async function fetchHtml(url: string): Promise<string> {
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
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response.text()
  }
  throw new Error("Request failed after max retries")
}

const ENTITY_MAP: Record<string, string> = {
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&nbsp;": " ",
  "&amp;": "&",
}

// Job Bank's detail-page description is HTML, double-HTML-encoded inside the page
// (e.g. `&amp;amp;` for a literal `&`) — decode twice to undo both layers.
export function decodeEntities(text: string): string {
  const decodeOnce = (s: string) => s.replace(/&lt;|&gt;|&quot;|&#39;|&apos;|&nbsp;|&amp;/g, (m) => ENTITY_MAP[m]!)
  return decodeOnce(decodeOnce(text))
}

export function stripHtml(html: string): string {
  return decodeEntities(html).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()
}

/**
 * Extracts the text content of `<span ... property="${prop}" ...>...</span>`,
 * walking nested `<span>` tags to find the matching close tag.
 */
export function extractBalancedSpan(html: string, prop: string, fromIndex = 0): string | null {
  const re = new RegExp(`<span[^>]*\\sproperty="${prop}"[^>]*>`, "i")
  const slice = html.slice(fromIndex)
  const m = re.exec(slice)
  if (!m) return null
  const start = fromIndex + m.index + m[0].length
  let depth = 1
  let i = start
  while (depth > 0) {
    const nextOpen = html.indexOf("<span", i)
    const nextClose = html.indexOf("</span>", i)
    if (nextClose === -1) return null
    if (nextOpen !== -1 && nextOpen < nextClose) {
      depth++
      i = nextOpen + 5
    } else {
      depth--
      i = nextClose + 7
    }
  }
  return html.slice(start, i - 7)
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}
