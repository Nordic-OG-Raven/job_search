import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, writeError } from "../helpers.js"

interface SearchResult {
  jobAdId: string
  title: string
  hiringOrgName: string | null
  occupation: string | null
  municipality: string | null
  postalCode: number | null
  postalDistrictName: string | null
  country: string | null
  publicationDate: string | null
  applicationDeadline: string | null
  applicationDeadlineStatus: string | null
  workHourPartTime: boolean | null
  isExternal: boolean | null
  hasLogo: boolean | null
  logoUrl: string | null
  cvr: string | null
  workPlaceAddress: string | null
  conceptUriDa: string | null
}

interface SearchResponse {
  jobAds: any[]
  searchFacets: Record<string, unknown>
  totalJobAdCount: number
  searchString: string | null
}

export const search = defineCommand({
  name: "search",
  description: "Search for job ads on Jobnet.dk",
  options: {
    "search-string": option(z.string().optional(), {
      short: "q",
      description: "Free-text keyword search (job title, skills, employer)",
    }),
    region: option(
      z.enum(["HovedstadenOgBornholm", "Midtjylland", "Syddanmark", "OevrigeSjaelland", "Nordjylland"]).optional(),
      { description: "One region (see Regions table)" }
    ),
    "postal-code": option(z.string().optional(), {
      description: "Postal code for radius search, e.g. 2100",
    }),
    radius: option(z.coerce.number().int().positive().default(50), {
      description: "Radius in km from postal code (requires --postal-code)",
    }),
    "work-hours": option(z.enum(["FullTime", "PartTime"]).optional(), {
      description: "FullTime or PartTime",
    }),
    duration: option(z.enum(["Permanent", "Temporary"]).optional(), {
      description: "Permanent or Temporary",
    }),
    "job-type": option(
      z.enum(["Ordinaert", "Efterloenner", "Foertidspension", "Fleksjob", "Handicapingenhindring", "Hotjob"]).optional(),
      { description: "Announcement type, e.g. Ordinaert" }
    ),
    "occupation-area": option(z.string().optional(), {
      description: "Occupation area identifier, e.g. 10000",
    }),
    "occupation-group": option(z.string().optional(), {
      description: "Occupation group identifier, e.g. 10060",
    }),
    page: option(z.coerce.number().int().min(1).default(1), {
      description: "Page number (1-indexed)",
    }),
    "per-page": option(z.coerce.number().int().positive().default(10), {
      description: "Results per page",
    }),
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap total results returned by CLI",
    }),
    order: option(z.enum(["PublicationDate", "BestMatch", "ApplicationDate"]).default("PublicationDate"), {
      description: "Sort order (see Order types table)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const params: Record<string, string> = {
      pageNumber: String(flags.page),
      resultsPerPage: String(flags["per-page"]),
      orderType: flags.order,
    }
    if (flags["search-string"]) params.searchString = flags["search-string"]
    if (flags.region) params.regions = flags.region
    if (flags["postal-code"]) {
      params.postalCode = flags["postal-code"]
      params.kmRadius = String(flags.radius)
    }
    if (flags["work-hours"]) params.workHoursType = flags["work-hours"]
    if (flags.duration) params.employmentDurationType = flags.duration
    if (flags["job-type"]) params.jobAnnouncementType = flags["job-type"]
    if (flags["occupation-area"]) params.occupationAreas = flags["occupation-area"]
    if (flags["occupation-group"]) params.occupationGroups = flags["occupation-group"]

    let data: SearchResponse
    try {
      data = await apiFetch<SearchResponse>("/FindJob/Search", params)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    let results: SearchResult[] = (data.jobAds ?? []).map((j: any) => ({
      jobAdId: j.jobAdId,
      title: j.title,
      hiringOrgName: j.hiringOrgName ?? null,
      occupation: j.occupation ?? null,
      municipality: j.municipality ?? null,
      postalCode: j.postalCode ?? null,
      postalDistrictName: j.postalDistrictName ?? null,
      country: j.country ?? null,
      publicationDate: j.publicationDate ?? null,
      applicationDeadline: j.applicationDeadline ?? null,
      applicationDeadlineStatus: j.applicationDeadlineStatus ?? null,
      workHourPartTime: j.workHourPartTime ?? null,
      isExternal: j.isExternal ?? null,
      hasLogo: j.hasLogo ?? null,
      logoUrl: j.logoUrl ?? null,
      cvr: j.cvr ?? null,
      workPlaceAddress: j.workPlaceAddress ?? null,
      conceptUriDa: j.conceptUriDa ?? null,
    }))

    if (flags.limit) {
      results = results.slice(0, flags.limit)
    }

    const meta = {
      totalJobAdCount: data.totalJobAdCount ?? 0,
      pageNumber: flags.page,
      resultsPerPage: flags["per-page"],
      searchString: data.searchString ?? null,
    }

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, facets: data.searchFacets ?? {}, results }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        console.log(`${r.title} - ${r.hiringOrgName ?? "Unknown"} (${r.postalDistrictName ?? r.municipality ?? "?"})`)
        console.log(`  https://jobnet.dk/job/${r.jobAdId}`)
      }
    } else {
      console.log(`Total: ${meta.totalJobAdCount} | Page: ${meta.pageNumber} | Per page: ${meta.resultsPerPage}`)
      console.log("")
      for (const r of results) {
        console.log(`${r.jobAdId.slice(0, 8).padEnd(10)} ${r.title.slice(0, 50).padEnd(50)} ${(r.hiringOrgName ?? "").slice(0, 25).padEnd(25)} ${r.postalDistrictName ?? r.municipality ?? ""}`)
      }
    }
  },
})
