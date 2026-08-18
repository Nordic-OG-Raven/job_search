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
      description: "Only offers first online on/after this date, format YYYY-MM-DD",
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
    const body: Record<string, unknown> = {
      offset: flags.offset,
      limit: flags.limit,
      sort: flags.sort,
    }
    if (flags.query) body.query = flags.query
    if (flags.filter && flags.filter.length > 0) body.filters = flags.filter
    if (flags.status && flags.status.length > 0) body.status = flags.status
    if (flags.since) body.gt_initial_online = `${flags.since}T00:00:00Z`

    let data: JobSearchResults
    try {
      data = await apiPost<JobSearchResults>("/offer/search", body)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const results: SearchResult[] = data.offers.map((o) => ({
      id: o.offer.id,
      title: pickLang(o.offer.title),
      company: o.company.name,
      companySlug: o.company.slug,
      status: o.offer.status,
      visibleOnline: o.offer.visible_online,
      onlineUntil: o.offer.online_until,
      isPremium: o.offer.is_premium,
      url: `https://jobfinder.lu/en/jobs/${o.offer.id}`,
    }))

    const meta = { hits: data.meta.hits, offset: data.meta.offset, limit: data.meta.limit }

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
