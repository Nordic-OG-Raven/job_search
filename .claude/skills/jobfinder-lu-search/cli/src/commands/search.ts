import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, apiPost, pickLang, writeError, type LangMap } from "../helpers.js"

interface OfferSearchView {
  id: string
  title: LangMap
  status: string
  visible_online: string | null
  online_until: string | null
  is_premium: boolean
}

interface CompanySearchView {
  id: string
  name: string
  slug: string
}

interface OfferSearchResult {
  offer: OfferSearchView
  company: CompanySearchView
}

interface SearchMeta {
  hits: number
  offset: number
  limit: number
  facet: {
    filters: Record<string, number>
    status: Record<string, number>
  }
}

interface JobSearchResults {
  offers: OfferSearchResult[]
  meta: SearchMeta
}

interface SearchResult {
  id: string
  title: string | null
  company: string
  companySlug: string
  status: string
  visibleOnline: string | null
  onlineUntil: string | null
  isPremium: boolean
  url: string
}

export const search = defineCommand({
  name: "search",
  description: "Search job listings on Jobfinder.lu (Luxembourg)",
  options: {
    query: option(z.string().optional(), {
      description: "Free-text keyword search (job title, skill, company)",
    }),
    filter: option(z.array(z.string()).optional(), {
      description: "Filter ID from the 'filters' command (category, contract type, working time, experience, education). Repeatable",
      repeatable: true,
    }),
    sort: option(z.enum(["date", "relevance", "initial_online"]).default("relevance"), {
      description: "Sort order: date, relevance, initial_online",
    }),
    status: option(z.array(z.enum(["draft", "pending", "online", "archived"])).optional(), {
      description: "Offer status filter (default: online). Repeatable",
      repeatable: true,
    }),
    since: option(z.string().optional(), {
      description: "Only offers that went live (visibleOnline) on/after this date, format YYYY-MM-DD. Filtered client-side — see handler comment.",
    }),
    offset: option(z.coerce.number().int().min(0).default(0), {
      description: "Pagination offset",
    }),
    limit: option(z.coerce.number().int().positive().max(50).default(10), {
      description: "Number of results to return (max 50)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const mapResult = (o: OfferSearchResult): SearchResult => ({
      id: o.offer.id,
      title: pickLang(o.offer.title),
      company: o.company.name,
      companySlug: o.company.slug,
      status: o.offer.status,
      visibleOnline: o.offer.visible_online,
      onlineUntil: o.offer.online_until,
      isPremium: o.offer.is_premium,
      url: `https://jobfinder.lu/en/jobs/${o.offer.id}`,
    })

    const baseBody: Record<string, unknown> = {}
    if (flags.query) baseBody.query = flags.query
    if (flags.filter && flags.filter.length > 0) baseBody.filters = flags.filter
    if (flags.status && flags.status.length > 0) baseBody.status = flags.status

    let results: SearchResult[]
    let totalHits: number

    if (flags.since) {
      // The API's gt_initial_online filter does not track this listing's own
      // freshness — it returns zero results for any realistic recent cutoff
      // even when clearly-recent listings exist (verified: a listing with
      // visibleOnline 8 days ago is excluded by gt_initial_online covering a
      // 26-day window). visibleOnline is the field that actually reflects
      // when this specific posting went live, so filter on that client-side
      // instead of sending a since-style filter to the API at all.
      const sinceDate = flags.since
      const PAGE_SIZE = 50
      const MAX_PAGES = 3 // covers ~150 listings — comfortably the whole market for any one query
      const matched: SearchResult[] = []
      let hits = 0
      for (let page = 0; page < MAX_PAGES; page++) {
        let data: JobSearchResults
        try {
          data = await apiPost<JobSearchResults>("/offer/search", {
            ...baseBody, sort: "date", limit: PAGE_SIZE, offset: page * PAGE_SIZE,
          })
        } catch (err) {
          writeError((err as Error).message, "API_ERROR")
          process.exit(1)
        }
        hits = data.meta.hits
        for (const o of data.offers) {
          const r = mapResult(o)
          if (r.visibleOnline && r.visibleOnline.slice(0, 10) >= sinceDate) matched.push(r)
        }
        if ((page + 1) * PAGE_SIZE >= hits) break // fetched everything the API has
        if (matched.length >= flags.limit) break // enough to satisfy the request already
      }
      results = matched.slice(0, flags.limit)
      totalHits = results.length // meta.hits from the API is the unfiltered count — report what actually matched instead
    } else {
      let data: JobSearchResults
      try {
        data = await apiPost<JobSearchResults>("/offer/search", {
          ...baseBody, sort: flags.sort, limit: flags.limit, offset: flags.offset,
        })
      } catch (err) {
        writeError((err as Error).message, "API_ERROR")
        process.exit(1)
      }
      results = data.offers.map(mapResult)
      totalHits = data.meta.hits
    }

    const meta = { hits: totalHits, offset: flags.offset, limit: flags.limit }

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        console.log(`${r.title ?? "(untitled)"} - ${r.company}`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${meta.hits} | Offset: ${meta.offset} | Limit: ${meta.limit}`)
      console.log("")
      for (const r of results) {
        console.log(`${(r.title ?? "(untitled)").slice(0, 55).padEnd(55)} ${r.company.slice(0, 30).padEnd(30)} ${r.visibleOnline?.slice(0, 10) ?? ""}`)
      }
    }
  },
})
