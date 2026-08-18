export const BASE_URL = "https://www.workforceaustralia.gov.au"

export const VACANCIES_PATH = "/api/v1/global/vacancies/"

export const DETAIL_PATH = "/individuals/jobs/details/"

// Workforce Australia "locationCodes" region IDs for capital-city search regions.
// Discovered via the live site's location picker (one region per city, the finest
// granularity exposed by the search UI/API — no per-suburb codes are available).
// Verified as real server-side filters: each code changes `totalCount` and every
// result's `location.label` matches the expected city/region.
export const CITY_LOCATION_CODES: Record<string, string> = {
  sydney: "21",
  melbourne: "71",
  brisbane: "41",
  perth: "81",
  adelaide: "51",
  hobart: "61",
  canberra: "19",
  darwin: "31",
}

export const CITY_LABELS: Record<string, string> = {
  sydney: "NSW - Sydney (ALL)",
  melbourne: "VIC - Melbourne (ALL)",
  brisbane: "QLD - Brisbane & Gold Coast (ALL)",
  perth: "WA - Perth (ALL)",
  adelaide: "SA - Adelaide (ALL)",
  hobart: "TAS - Hobart & Southern Tasmania",
  canberra: "ACT - Canberra & Queanbeyan",
  darwin: "NT - Darwin",
}

export async function apiFetch<T>(params: Record<string, string>): Promise<T> {
  const qs = new URLSearchParams(params)
  const url = `${BASE_URL}${VACANCIES_PATH}?${qs.toString()}`

  const maxRetries = 6
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0", Accept: "application/json" },
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`API request failed: ${response.status} ${response.statusText}`)
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((resolve) => setTimeout(resolve, delay + jitter))
      delay = Math.min(delay * 2, 5000)
      continue
    }
    if (!response.ok) {
      throw new Error(`API request failed: ${response.status} ${response.statusText}`)
    }
    return response.json() as Promise<T>
  }
  throw new Error("API request failed after max retries")
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}
