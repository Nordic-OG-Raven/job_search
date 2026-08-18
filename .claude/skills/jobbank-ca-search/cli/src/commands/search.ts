import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import {
  BASE_URL,
  DETAIL_PATH,
  PROVINCES,
  SEARCH_PATH,
  fetchHtml,
  writeError,
} from "../helpers.js"

interface SearchResult {
  jobId: string
  title: string
  employer: string | null
  location: string | null
  salary: string | null
  postedDate: string | null
  source: string | null
  url: string
}

const RESULTS_PER_PAGE = 25

const SORT_MAP: Record<string, string> = {
  relevance: "M",
  date: "D",
}

function cleanText(s: string): string {
  return s.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()
}

function buildSearchUrl(params: Record<string, string>): string {
  const qs = new URLSearchParams(params)
  return `${BASE_URL}${SEARCH_PATH}?${qs.toString()}`
}

function parseTotalCount(html: string): number {
  const m = html.match(/View ([\d,]+) job postings/)
  return m ? parseInt(m[1]!.replace(/,/g, ""), 10) : 0
}

function parseResults(html: string): SearchResult[] {
  const results: SearchResult[] = []
  const parts = html.split(/<article id="article-(\d+)"/).slice(1)
  for (let i = 0; i < parts.length; i += 2) {
    const jobId = parts[i]!
    const body = parts[i + 1]!.slice(0, 3000)

    const title = cleanText(body.match(/class="noctitle">([\s\S]*?)<\/span>/)?.[1] ?? "")
    const employer = cleanText(body.match(/class="business">([\s\S]*?)<\/li>/)?.[1] ?? "") || null
    const location = cleanText(body.match(/class="location">([\s\S]*?)<\/li>/)?.[1] ?? "")
      .replace(/^Location\s*/, "") || null
    const salary = cleanText(body.match(/class="salary">([\s\S]*?)<\/li>/)?.[1] ?? "")
      .replace(/^Salary\s*/, "") || null
    const postedDate = cleanText(body.match(/class="date">([\s\S]*?)<\/li>/)?.[1] ?? "") || null
    const source = cleanText(body.match(/job-source-icon[^>]*><span class="wb-inv">([\s\S]*?)<\/span>/)?.[1] ?? "") || null

    results.push({
      jobId,
      title,
      employer,
      location,
      salary,
      postedDate,
      source,
      url: `${BASE_URL}${DETAIL_PATH}${jobId}`,
    })
  }
  return results
}

export const search = defineCommand({
  name: "search",
  description: "Search job listings on Job Bank (Canada)",
  options: {
    "search-text": option(z.string().optional(), {
      description: "Free-text keyword search (job title, skill, employer), e.g. 'python developer'",
    }),
    province: option(z.enum(Object.keys(PROVINCES) as [string, ...string[]]).optional(), {
      description: `Restrict to a province/territory via Job Bank's own location filter. One of: ${Object.keys(PROVINCES).join(", ")}`,
    }),
    days: option(z.coerce.number().int().positive().optional(), {
      description: "Only show jobs posted within the last N days",
    }),
    sort: option(z.enum(["relevance", "date"]).default("relevance"), {
      description: "Sort order: relevance (best match) or date (most recent first)",
    }),
    page: option(z.coerce.number().int().min(1).default(1), {
      description: `Page number to fetch (${RESULTS_PER_PAGE} results/page)`,
    }),
    limit: option(z.coerce.number().int().positive().max(50).default(10), {
      description: "Maximum number of results to return (fetches additional pages if needed)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const params: Record<string, string> = { sort: SORT_MAP[flags.sort]! }
    if (flags["search-text"]) params.dkw = flags["search-text"]
    if (flags.province) params.fprov = PROVINCES[flags.province]!
    if (flags.days !== undefined) params.fage = String(flags.days)

    let allResults: SearchResult[] = []
    let totalCount = 0
    let pagesFetched = 0

    try {
      const pagesNeeded = Math.ceil(flags.limit / RESULTS_PER_PAGE)
      for (let i = 0; i < pagesNeeded; i++) {
        const page = flags.page + i
        const html = await fetchHtml(buildSearchUrl({ ...params, page: String(page) }))
        totalCount = parseTotalCount(html)
        pagesFetched++
        const pageResults = parseResults(html)
        allResults.push(...pageResults)
        if (pageResults.length < RESULTS_PER_PAGE) break
      }
      allResults = allResults.slice(0, flags.limit)
    } catch (err) {
      writeError((err as Error).message, "FETCH_ERROR")
      process.exit(1)
    }

    const meta: Record<string, unknown> = {
      totalCount,
      page: flags.page,
      pagesFetched,
      returned: allResults.length,
    }
    if (flags.province) meta.province = flags.province

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results: allResults }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of allResults) {
        console.log(`${r.title} - ${r.employer ?? "Unknown"}${r.location ? ` (${r.location})` : ""}`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${totalCount} | Page: ${flags.page} | Returned: ${allResults.length}`)
      console.log("")
      for (const r of allResults) {
        console.log(`${r.title.slice(0, 45).padEnd(45)} ${(r.employer ?? "").slice(0, 25).padEnd(25)} ${(r.location ?? "").slice(0, 22).padEnd(22)} ${(r.salary ?? "").slice(0, 20).padEnd(20)} ${r.postedDate ?? ""}`)
      }
    }
  },
})
