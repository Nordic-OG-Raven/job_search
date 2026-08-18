import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, htmlFetch, extractStash, decodeHtmlEntities, stripTags, writeError } from "../helpers.js"

interface SearchResult {
  id: string
  title: string
  company: string | null
  companyUrl: string | null
  location: string | null
  date: string | null
  deadline: string | null
  url: string
  applyUrl: string | null
  description: string | null
}

function extractDescription(cardHtml: string | undefined): string | null {
  if (!cardHtml) return null
  const pMatches = [...cardHtml.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/gi)]
  for (const pm of pMatches) {
    const text = decodeHtmlEntities(stripTags(pm[1]))
    if (text.length > 0) return text.length > 300 ? text.slice(0, 300) : text
  }
  return null
}

export const search = defineCommand({
  name: "search",
  description: "Search for job listings on Jobindex.dk",
  options: {
    query: option(z.string().optional(), {
      short: "q",
      description: "Keyword search query (e.g. 'python', 'grafisk designer')",
    }),
    page: option(z.coerce.number().int().min(1).default(1), {
      description: "Page number (1-indexed)",
    }),
    jobage: option(z.coerce.number().int().default(9999), {
      description: "Max age of posting in days: 1, 7, 14, 30, or 9999 (all)",
    }),
    sort: option(z.enum(["score", "date"]).default("score"), {
      description: "Sort order: score (relevance) or date (newest first)",
    }),
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap total results returned by the CLI (client-side)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const params: Record<string, string> = {}
    if (flags.query) params.q = flags.query
    if (flags.page > 1) params.page = String(flags.page)
    if (flags.jobage !== 9999) params.jobage = String(flags.jobage)
    if (flags.sort !== "score") params.sort = flags.sort

    const qs = new URLSearchParams(params).toString()
    const url = `${BASE_URL}/jobsoegning${qs ? "?" + qs : ""}`

    let html: string
    try {
      html = await htmlFetch(url)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const stash = extractStash(html)
    const searchResponse = stash?.["jobsearch/result_app"]?.storeData?.searchResponse
    if (!searchResponse) {
      writeError("Failed to parse search results", "PARSE_ERROR")
      process.exit(1)
    }

    let results: SearchResult[] = (searchResponse.results ?? []).map((r: any) => ({
      id: r.tid,
      title: decodeHtmlEntities(r.headline ?? ""),
      company: r.companytext ?? r.company?.name ?? null,
      companyUrl: r.company?.homeurl ?? null,
      location: r.area ?? null,
      date: r.firstdate ?? null,
      deadline: r.lastdate ?? null,
      url: r.share_url ?? `${BASE_URL}/vis-job/${r.tid}`,
      applyUrl: r.app_apply_url ?? r.apply_url ?? null,
      description: extractDescription(r.html),
    }))

    if (flags.limit) {
      results = results.slice(0, flags.limit)
    }

    const meta = {
      total: searchResponse.hitcount ?? 0,
      page: flags.page,
      perPage: searchResponse.page_size ?? 20,
    }

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        console.log(`${r.title} - ${r.company ?? "Unknown"} (${r.location ?? "?"})`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${meta.total} | Page: ${meta.page} | Per page: ${meta.perPage}`)
      console.log("")
      for (const r of results) {
        console.log(`${r.id.padEnd(10)} ${r.title.slice(0, 55).padEnd(55)} ${(r.company ?? "").slice(0, 30).padEnd(30)} ${r.location ?? ""}`)
      }
    }
  },
})
