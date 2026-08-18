import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, apiPost, writeError } from "../helpers.js"

interface SearchResult {
  title: string
  companyName: string
  companyAddress: string | null
  jobTypes: string[]
  publishedDate: string | null
  applicationDeadline: string | null
  url: string
  slug: string
}

interface SearchResponse {
  items: any[]
  currentPage: number
  totalItems: number
  itemsPrPage: number
  totalPages: number
}

interface Filter {
  type: string
  value: string | number
  displayText: string
}

export const search = defineCommand({
  name: "search",
  description: "Search job listings with filters",
  options: {
    text: option(z.string().optional(), {
      description: "Free-text keyword search (job title, keyword)",
    }),
    category: option(z.coerce.number().int().optional(), {
      description: "Category ID (see categories command)",
    }),
    "jobtitle-id": option(z.coerce.number().int().optional(), {
      description: "Job title ID from autocomplete results",
    }),
    municipality: option(z.string().optional(), {
      description: "Municipality name, e.g. Odense, København",
    }),
    zip: option(z.string().optional(), {
      description: "Zip code, e.g. 5000",
    }),
    region: option(z.string().optional(), {
      description: "Region name",
    }),
    "job-type": option(z.string().optional(), {
      description: "Comma-separated job types: fuldtid,deltid,fleksjob,elev,studiejob,praktik",
    }),
    page: option(z.coerce.number().int().min(1).default(1), {
      description: "Page number (30 items per page, server-enforced)",
    }),
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap total results returned by CLI (client-side)",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    const filters: Filter[] = []
    if (flags.text) filters.push({ type: "freetext", value: flags.text, displayText: flags.text })
    if (flags.category) filters.push({ type: "category", value: flags.category, displayText: String(flags.category) })
    if (flags["jobtitle-id"]) filters.push({ type: "jobtitle", value: flags["jobtitle-id"], displayText: String(flags["jobtitle-id"]) })
    if (flags.municipality) filters.push({ type: "municipality", value: flags.municipality, displayText: flags.municipality })
    if (flags.zip) filters.push({ type: "zip", value: flags.zip, displayText: flags.zip })
    if (flags.region) filters.push({ type: "region", value: flags.region, displayText: flags.region })

    const jobTypes = flags["job-type"] ? flags["job-type"].split(",").map((t) => t.trim()).filter(Boolean) : []

    const body = {
      jobTypes,
      filters,
      locationMode: "Text",
      distance: 50,
    }

    let data: SearchResponse
    try {
      data = await apiPost<SearchResponse>(`/api/jobsearch/search/${flags.page}`, body)
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    let results: SearchResult[] = (data.items ?? []).map((j: any) => {
      const slug = (j.url ?? "").replace(/^\/job\//, "")
      return {
        title: j.title,
        companyName: j.companyName ?? null,
        companyAddress: j.companyAddress ?? null,
        jobTypes: j.jobTypes ?? [],
        publishedDate: j.publishedDate ?? null,
        applicationDeadline: j.applicationDeadline ?? null,
        url: `${BASE_URL}${j.url}`,
        slug,
      }
    })

    if (flags.limit) {
      results = results.slice(0, flags.limit)
    }

    const meta = {
      currentPage: data.currentPage,
      totalItems: data.totalItems,
      itemsPrPage: data.itemsPrPage,
      totalPages: data.totalPages,
    }

    if (flags.format === "json") {
      console.log(JSON.stringify({ meta, results }, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        console.log(`${r.title} - ${r.companyName} (${r.companyAddress ?? "?"})`)
        console.log(`  ${r.url}`)
      }
    } else {
      console.log(`Total: ${meta.totalItems} | Page: ${meta.currentPage}/${meta.totalPages}`)
      console.log("")
      for (const r of results) {
        console.log(`${r.title.slice(0, 50).padEnd(50)} ${(r.companyName ?? "").slice(0, 30).padEnd(30)} ${r.publishedDate ?? ""}`)
      }
    }
  },
})
