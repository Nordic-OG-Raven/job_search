import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import {
  BASE_URL,
  fetchWithUA,
  rssFetch,
  parseRssDescription,
  extractJobIdFromUrl,
  writeError,
} from "../helpers.js"

interface SearchResult {
  id: string
  title: string
  company: string
  location: string
  jobType: string
  description: string
  url: string
  posted: string
  deadline: string | null
}

const MONTHS: Record<string, string> = {
  Jan: "01", Feb: "02", Mar: "03", Apr: "04", May: "05", Jun: "06",
  Jul: "07", Aug: "08", Sep: "09", Oct: "10", Nov: "11", Dec: "12",
}

function normalizePubDate(pubDate: string): string {
  // "Wed, 27 May 2026 00:00:00 +0200" -> "2026-05-27T00:00:00+02:00"
  const m = pubDate.match(/^\w+,\s+(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s+([+-]\d{2})(\d{2})$/)
  if (!m) return pubDate
  const [, day, monthName, year, hh, mm, ss, tzh, tzm] = m
  const month = MONTHS[monthName] ?? "01"
  return `${year}-${month}-${day.padStart(2, "0")}T${hh}:${mm}:${ss}${tzh}:${tzm}`
}

function normalizeDeadline(deadline: string | null): string | null {
  // "12.04.2026" -> "2026-04-12"
  if (!deadline) return null
  const m = deadline.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/)
  if (!m) return deadline
  const [, dd, mm, yyyy] = m
  return `${yyyy}-${mm.padStart(2, "0")}-${dd.padStart(2, "0")}`
}

export const search = defineCommand({
  name: "search",
  description: "Search job listings via RSS feed",
  options: {
    key: option(z.string().optional(), {
      description: "Keyword search (title, company, keyword)",
    }),
    exclude: option(z.string().optional(), {
      description: "Exclude keywords (antikey)",
    }),
    type: option(z.array(z.coerce.number().int()).optional(), {
      description: "Job type code (cvtype). Repeatable for multiple",
      repeatable: true,
    }),
    education: option(z.array(z.coerce.number().int()).optional(), {
      description: "Education field code (udd). Repeatable",
      repeatable: true,
    }),
    location: option(z.array(z.coerce.number().int()).optional(), {
      description: "Region code (amt). Repeatable",
      repeatable: true,
    }),
    "work-area": option(z.array(z.coerce.number().int()).optional(), {
      description: "Work area / function code (erf). Repeatable",
      repeatable: true,
    }),
    industry: option(z.array(z.coerce.number().int()).optional(), {
      description: "Industry code (branche). Repeatable",
      repeatable: true,
    }),
    "suitable-for": option(z.array(z.coerce.number().int()).optional(), {
      description: "Suitable-for code (andet). Repeatable",
      repeatable: true,
    }),
    company: option(z.coerce.number().int().optional(), {
      description: "Company ID (virk)",
    }),
    remote: option(z.enum(["helt", "delvist"]).optional(), {
      description: "Remote work: helt or delvist",
    }),
    since: option(z.string().optional(), {
      description: "Posted on or after date, format YYYY-MM-DD (oprettet)",
    }),
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap total results returned by CLI (client-side)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const hasFilter =
      flags.key ||
      flags.exclude ||
      (flags.type && flags.type.length > 0) ||
      (flags.education && flags.education.length > 0) ||
      (flags.location && flags.location.length > 0) ||
      (flags["work-area"] && flags["work-area"].length > 0) ||
      (flags.industry && flags.industry.length > 0) ||
      (flags["suitable-for"] && flags["suitable-for"].length > 0) ||
      flags.company ||
      flags.remote ||
      flags.since

    if (!hasFilter) {
      writeError("--key or at least one filter is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    const params: Record<string, string | string[]> = {}
    if (flags.key) params.key = flags.key
    if (flags.exclude) params.antikey = flags.exclude
    if (flags.type && flags.type.length > 0) params.cvtype = flags.type.map(String)
    if (flags.education && flags.education.length > 0) params.udd = flags.education.map(String)
    if (flags.location && flags.location.length > 0) params.amt = flags.location.map(String)
    if (flags["work-area"] && flags["work-area"].length > 0) params.erf = flags["work-area"].map(String)
    if (flags.industry && flags.industry.length > 0) params.branche = flags.industry.map(String)
    if (flags["suitable-for"] && flags["suitable-for"].length > 0) params.andet = flags["suitable-for"].map(String)
    if (flags.company) params.virk = String(flags.company)
    if (flags.remote) params.fjernarbejde = flags.remote
    if (flags.since) params.oprettet = flags.since

    let items: Awaited<ReturnType<typeof rssFetch>>
    try {
      items = await rssFetch(params)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    let total: number | null = null
    try {
      await new Promise((resolve) => setTimeout(resolve, 300))
      const searchParams = new URLSearchParams()
      for (const [k, v] of Object.entries(params)) {
        if (Array.isArray(v)) {
          for (const item of v) searchParams.append(k, item)
        } else {
          searchParams.append(k, v)
        }
      }
      const res = await fetchWithUA(`${BASE_URL}/job/?${searchParams.toString()}`)
      if (res.ok) {
        const html = await res.text()
        const titleMatch = html.match(/<title>\s*([\d.,]+)\s*relevante job/i)
        if (titleMatch) {
          total = parseInt(titleMatch[1].replace(/[.,]/g, ""), 10)
        }
      }
    } catch {
      total = null
    }

    let results: SearchResult[] = items.map((item) => {
      const parsed = parseRssDescription(item.description)
      return {
        id: extractJobIdFromUrl(item.link),
        title: item.title,
        company: parsed.company,
        location: parsed.location,
        jobType: parsed.jobType,
        description: item.description,
        url: item.link,
        posted: normalizePubDate(item.pubDate),
        deadline: normalizeDeadline(parsed.deadline),
      }
    })

    if (flags.limit) {
      results = results.slice(0, flags.limit)
    }

    const meta = { total }

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        console.log(`${r.title} - ${r.company} (${r.location})`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${meta.total ?? "?"}`)
      console.log("")
      for (const r of results) {
        console.log(`${r.id.padEnd(10)} ${r.title.slice(0, 50).padEnd(50)} ${r.company.slice(0, 30).padEnd(30)} ${r.location}`)
      }
    }
  },
})
