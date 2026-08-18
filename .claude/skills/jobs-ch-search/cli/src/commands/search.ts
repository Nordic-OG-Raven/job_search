import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import {
  BASE_URL,
  CANTON_NAMES,
  DETAIL_PATH,
  REGION_IDS,
  SEARCH_PATH,
  extractInitJson,
  fetchHtml,
  type Lang,
  writeError,
} from "../helpers.js"

interface RawLocation {
  cantonCode: string | null
  city: string | null
  postalCode: string | null
  countryCode: string | null
}

interface RawCompany {
  id: string
  name: string
  slug: string
}

interface RawResult {
  id: string
  title: string
  company: RawCompany
  place: string | null
  locations: RawLocation[]
  employmentGrades: [number, number]
  employmentTypeIds: string[]
  isNew: boolean
  isPaid: boolean
  publicationDate: string | null
  relativeDate: string | null
}

interface SearchMeta {
  numPages: number
  totalHits: number
  baseOptions: { rows: number }
}

interface SearchResult {
  id: string
  title: string
  company: string
  companySlug: string
  place: string | null
  cantons: string[]
  employmentGrades: [number, number]
  isNew: boolean
  isPaid: boolean
  publicationDate: string | null
  relativeDate: string | null
  url: string
}

function buildSearchUrl(lang: Lang, params: Record<string, string>): string {
  const qs = new URLSearchParams(params)
  return `${BASE_URL}${SEARCH_PATH[lang]}?${qs.toString()}`
}

async function fetchSearchPage(
  lang: Lang,
  params: Record<string, string>
): Promise<{ results: RawResult[]; meta: SearchMeta }> {
  const { html } = await fetchHtml(buildSearchUrl(lang, params))
  const init = extractInitJson(html)
  const main = (init as any)?.vacancy?.results?.main ?? {}
  return {
    results: (main.results ?? []) as RawResult[],
    meta: (main.meta ?? { numPages: 0, totalHits: 0, baseOptions: { rows: 20 } }) as SearchMeta,
  }
}

function mapResult(r: RawResult, lang: Lang): SearchResult {
  return {
    id: r.id,
    title: r.title,
    company: r.company?.name ?? "",
    companySlug: r.company?.slug ?? "",
    place: r.place ?? null,
    cantons: (r.locations ?? []).map((l) => l.cantonCode).filter((c): c is string => !!c),
    employmentGrades: r.employmentGrades ?? [0, 100],
    isNew: !!r.isNew,
    isPaid: !!r.isPaid,
    publicationDate: r.publicationDate ?? null,
    relativeDate: r.relativeDate ?? null,
    url: `${BASE_URL}${DETAIL_PATH[lang]}${r.id}/`,
  }
}

export const search = defineCommand({
  name: "search",
  description: "Search job listings on jobs.ch (Switzerland)",
  options: {
    term: option(z.string().optional(), {
      description: "Free-text keyword search (job title, skill, company)",
    }),
    "employment-grade-min": option(z.coerce.number().int().min(0).max(100).optional(), {
      description: "Minimum employment grade (% of full time), e.g. 80",
    }),
    "employment-grade-max": option(z.coerce.number().int().min(0).max(100).optional(), {
      description: "Maximum employment grade (% of full time), e.g. 100",
    }),
    region: option(z.enum(["central-switzerland"]).optional(), {
      description: "Restrict to a region via jobs.ch's own region filter: central-switzerland = Lucerne, Zug, Schwyz, Uri, Obwalden, Nidwalden (Zentralschweiz). This is a server-side filter that covers all listings in the region, not just ones with structured location data.",
    }),
    page: option(z.coerce.number().int().min(1).default(1), {
      description: "Upstream page to start from (20 results/page on jobs.ch)",
    }),
    limit: option(z.coerce.number().int().positive().max(50).default(10), {
      description: "Maximum number of results to return (fetches additional pages if needed)",
    }),
    lang: option(z.enum(["en", "de"]).default("en"), {
      description: "Site locale for the search and result URLs: en or de",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const params: Record<string, string> = { term: flags.term ?? "" }
    if (flags["employment-grade-min"] !== undefined) params["employment-grade-min"] = String(flags["employment-grade-min"])
    if (flags["employment-grade-max"] !== undefined) params["employment-grade-max"] = String(flags["employment-grade-max"])
    if (flags.region) params.region = REGION_IDS[flags.region]

    let allResults: SearchResult[] = []
    let totalHits = 0
    let numPages = 0
    let pagesFetched = 0

    try {
      const pagesNeeded = Math.ceil(flags.limit / 20)
      for (let i = 0; i < pagesNeeded; i++) {
        const page = flags.page + i
        const { results, meta } = await fetchSearchPage(flags.lang, { ...params, page: String(page) })
        totalHits = meta.totalHits
        numPages = meta.numPages
        pagesFetched++
        allResults.push(...results.map((r) => mapResult(r, flags.lang)))
        if (page >= numPages) break
      }
      allResults = allResults.slice(0, flags.limit)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const meta: Record<string, unknown> = { totalHits, numPages, page: flags.page, pagesFetched, returned: allResults.length }
    if (flags.region) meta.region = flags.region

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results: allResults }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of allResults) {
        const cantons = r.cantons.map((c) => CANTON_NAMES[c] ?? c).join(", ")
        console.log(`${r.title} - ${r.company}${r.place ? ` (${r.place}${cantons ? `, ${cantons}` : ""})` : ""}`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${totalHits} | Page: ${flags.page}/${numPages} | Returned: ${allResults.length}`)
      console.log("")
      for (const r of allResults) {
        const grade = r.employmentGrades[0] === r.employmentGrades[1]
          ? `${r.employmentGrades[0]}%`
          : `${r.employmentGrades[0]}-${r.employmentGrades[1]}%`
        console.log(`${r.title.slice(0, 45).padEnd(45)} ${r.company.slice(0, 25).padEnd(25)} ${(r.place ?? "").padEnd(15)} ${grade.padEnd(8)} ${r.relativeDate ?? ""}`)
      }
    }
  },
})
