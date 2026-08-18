import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import {
  BASE_URL,
  CITY_LOCATION_CODES,
  DETAIL_PATH,
  apiFetch,
  writeError,
} from "../helpers.js"

interface CodedLabel {
  code: string
  label: string
}

interface RawResult {
  vacancyId: number
  title: string
  description: string
  employerName: string | null
  organisation: CodedLabel | null
  location: CodedLabel | null
  state: string | null
  suburb: string | null
  postCode: string | null
  jobType: CodedLabel | null
  workType: CodedLabel | null
  tenure: CodedLabel | null
  salary: CodedLabel | null
  positionsAvailable: number | null
  isNewJob: boolean
  isExternalJob: boolean
  creationDate: string | null
}

interface VacanciesResponse {
  totalCount: number
  pageNumber: number
  pageSize: number
  results: { score: number; result: RawResult }[]
}

interface SearchResult {
  vacancyId: number
  title: string
  employer: string | null
  location: string | null
  state: string | null
  suburb: string | null
  jobType: string | null
  workType: string | null
  salary: string | null
  positionsAvailable: number | null
  isNew: boolean
  isExternal: boolean
  postedDate: string | null
  snippet: string
  url: string
}

const SORT_MAP: Record<string, string> = {
  none: "None",
  "title-asc": "TitleAscending",
  "title-desc": "TitleDescending",
  "date-asc": "DateAddedAscending",
  "date-desc": "DateAddedDescending",
}

function mapResult(r: RawResult): SearchResult {
  return {
    vacancyId: r.vacancyId,
    title: r.title,
    employer: r.employerName || r.organisation?.label || null,
    location: r.location?.label ?? null,
    state: r.state,
    suburb: r.suburb,
    jobType: r.jobType?.label ?? null,
    workType: r.workType?.label ?? null,
    salary: r.salary?.label ?? null,
    positionsAvailable: r.positionsAvailable,
    isNew: !!r.isNewJob,
    isExternal: !!r.isExternalJob,
    postedDate: r.creationDate,
    snippet: r.description.replace(/\s+/g, " ").trim(),
    url: `${BASE_URL}${DETAIL_PATH}${r.vacancyId}`,
  }
}

export const search = defineCommand({
  name: "search",
  description: "Search job listings on Workforce Australia",
  options: {
    "search-text": option(z.string().optional(), {
      description: "Free-text keyword search (job title, skill, employer), e.g. 'python developer'",
    }),
    city: option(z.enum(Object.keys(CITY_LOCATION_CODES) as [string, ...string[]]).optional(), {
      description: `Restrict to a capital-city region via Workforce Australia's own location filter. One of: ${Object.keys(CITY_LOCATION_CODES).join(", ")}`,
    }),
    sort: option(z.enum(["none", "title-asc", "title-desc", "date-asc", "date-desc"]).default("date-desc"), {
      description: "Sort order: none, title-asc, title-desc, date-asc, date-desc (default: date-desc, most recent first)",
    }),
    page: option(z.coerce.number().int().min(1).default(1), {
      description: "Page number to fetch (1-indexed)",
    }),
    limit: option(z.coerce.number().int().positive().max(100).default(10), {
      description: "Number of results to return (max 100)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const params: Record<string, string> = {
      pageNumber: String(flags.page),
      pageSize: String(flags.limit),
      sort: SORT_MAP[flags.sort],
    }
    if (flags["search-text"]) params.searchText = flags["search-text"]
    if (flags.city) params.locationCodes = CITY_LOCATION_CODES[flags.city]

    let data: VacanciesResponse
    try {
      data = await apiFetch<VacanciesResponse>(params)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const results = data.results.map((r) => mapResult(r.result))
    const meta: Record<string, unknown> = {
      totalCount: data.totalCount,
      page: data.pageNumber,
      pageSize: data.pageSize,
      returned: results.length,
    }
    if (flags.city) meta.city = flags.city

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        console.log(`${r.title} - ${r.employer ?? "Unknown"}${r.location ? ` (${r.location})` : ""}`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${meta.totalCount} | Page: ${meta.page} | Returned: ${meta.returned}`)
      console.log("")
      for (const r of results) {
        console.log(`${r.title.slice(0, 45).padEnd(45)} ${(r.employer ?? "").slice(0, 25).padEnd(25)} ${(r.location ?? "").slice(0, 28).padEnd(28)} ${(r.workType ?? "").padEnd(20)} ${r.postedDate?.slice(0, 10) ?? ""}`)
      }
    }
  },
})
