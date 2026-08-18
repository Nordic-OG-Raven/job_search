import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, DETAIL_PATH, fetchHtml, stripHtml, writeError } from "../helpers.js"

interface JsonLdJobPosting {
  "@type": "JobPosting"
  title: string
  description: string
  datePosted: string
  hiringOrganization?: { name?: string; sameAs?: string; logo?: string }
  jobLocation?: {
    address?: {
      streetAddress?: string
      addressLocality?: string
      postalCode?: string
      addressCountry?: string
    }
  }
  industry?: string
  employmentType?: string[]
  occupationalCategory?: string
}

interface JsonLdBreadcrumbList {
  "@type": "BreadcrumbList"
  itemListElement?: { position: number; name?: string; item?: { name?: string } | string }[]
}

interface JobDetail {
  id: string
  url: string
  title: string
  company: { name: string | null; website: string | null; logo: string | null }
  location: { street: string | null; city: string | null; postalCode: string | null; country: string | null }
  datePosted: string | null
  industry: string | null
  occupationalCategory: string | null
  employmentType: string[]
  categories: string[]
  description: string
}

function extractJsonLd(html: string): (JsonLdJobPosting | JsonLdBreadcrumbList)[] {
  const out: (JsonLdJobPosting | JsonLdBreadcrumbList)[] = []
  const re = /<script type="application\/ld\+json">(.*?)<\/script>/gs
  let m: RegExpExecArray | null
  while ((m = re.exec(html)) !== null) {
    try {
      const parsed = JSON.parse(m[1])
      if (Array.isArray(parsed)) {
        out.push(...parsed)
      } else {
        out.push(parsed)
      }
    } catch {
      // skip malformed JSON-LD blocks
    }
  }
  return out
}

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job posting on jobs.ch (Switzerland)",
  options: {
    lang: option(z.enum(["en", "de"]).default("en"), {
      description: "Site locale for the detail page: en or de",
    }),
    format: option(z.enum(["json", "plain"]).default("json"), {
      description: "Output format: json, plain",
    }),
  },
  handler: async ({ flags, positional }) => {
    const id = positional[0]
    if (!id) {
      writeError("Job id is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    const url = `${BASE_URL}${DETAIL_PATH[flags.lang]}${id}/`

    let html: string
    try {
      const res = await fetchHtml(url)
      if (res.status === 404) {
        writeError("Job not found", "NOT_FOUND")
        process.exit(1)
      }
      if (res.status !== 200) {
        writeError(`Request failed: ${res.status}`, "API_ERROR")
        process.exit(1)
      }
      html = res.html
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const ld = extractJsonLd(html)
    const posting = ld.find((d): d is JsonLdJobPosting => d["@type"] === "JobPosting")
    if (!posting) {
      writeError("Job not found", "NOT_FOUND")
      process.exit(1)
    }
    const breadcrumbs = ld.find((d): d is JsonLdBreadcrumbList => d["@type"] === "BreadcrumbList")

    const categories = (breadcrumbs?.itemListElement ?? [])
      .map((b) => (typeof b.item === "string" ? b.item : b.item?.name) ?? b.name)
      .filter((n): n is string => !!n)
      .map((n) => decodeURIComponent(n))
      .filter((n) => n !== "Job Offers" && n !== posting.title)

    const address = posting.jobLocation?.address
    const result: JobDetail = {
      id,
      url,
      title: posting.title,
      company: {
        name: posting.hiringOrganization?.name ?? null,
        website: posting.hiringOrganization?.sameAs ?? null,
        logo: posting.hiringOrganization?.logo ?? null,
      },
      location: {
        street: address?.streetAddress || null,
        city: address?.addressLocality ?? null,
        postalCode: address?.postalCode ?? null,
        country: address?.addressCountry ?? null,
      },
      datePosted: posting.datePosted ?? null,
      industry: posting.industry ?? null,
      occupationalCategory: posting.occupationalCategory ?? null,
      employmentType: posting.employmentType ?? [],
      categories,
      description: stripHtml(posting.description ?? ""),
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title}`)
      if (result.company.name) console.log(`Company: ${result.company.name}`)
      const loc = [result.location.street, result.location.postalCode, result.location.city, result.location.country].filter(Boolean).join(", ")
      if (loc) console.log(`Location: ${loc}`)
      if (result.employmentType.length) console.log(`Employment type: ${result.employmentType.join(", ")}`)
      if (result.occupationalCategory) console.log(`Category: ${result.occupationalCategory}`)
      if (result.industry) console.log(`Industry: ${result.industry}`)
      if (result.categories.length) console.log(`Tags: ${result.categories.join(" > ")}`)
      console.log(`Posted: ${result.datePosted ?? "N/A"}`)
      if (result.company.website) console.log(`Company site: ${result.company.website}`)
      console.log(`URL: ${result.url}`)
      console.log("")
      console.log(result.description)
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
