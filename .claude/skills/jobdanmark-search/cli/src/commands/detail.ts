import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, writeError, stripHtml } from "../helpers.js"

interface JobDetail {
  slug: string
  url: string
  title: string | null
  datePosted: string | null
  validThrough: string | null
  employmentType: string[] | null
  hiringOrganization: { name: string | null; logo: string | null } | null
  jobLocation: {
    streetAddress: string | null
    addressLocality: string | null
    addressRegion: string | null
    postalCode: string | null
    addressCountry: string | null
  } | null
  description: string | null
}

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job posting (by slug)",
  options: {
    format: option(z.enum(["json", "plain"]).default("json"), {
      description: "Output format: json, plain",
    }),
  },
  handler: async ({ flags, positional }) => {
    const slug = positional[0]
    if (!slug) {
      writeError("Job slug is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    const url = `${BASE_URL}/job/${slug}`
    let html: string
    try {
      const res = await fetch(url)
      if (!res.ok) {
        throw new Error(`Job not found`)
      }
      html = await res.text()
    } catch (err) {
      writeError("Job not found", "NOT_FOUND")
      process.exit(1)
    }

    const ldMatch = html.match(/<script type="application\/ld(?:\+|&#x2B;)json">([\s\S]*?)<\/script>/i)
    if (!ldMatch) {
      writeError("Failed to parse JSON-LD from job page", "PARSE_ERROR")
      process.exit(1)
    }

    let ld: any
    try {
      const decoded = ldMatch[1]
        .replace(/&#x2B;/g, "+")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
      ld = JSON.parse(decoded)
    } catch {
      writeError("Failed to parse JSON-LD from job page", "PARSE_ERROR")
      process.exit(1)
    }

    const address = ld.jobLocation?.address
    const result: JobDetail = {
      slug,
      url,
      title: ld.title ?? null,
      datePosted: ld.datePosted ?? null,
      validThrough: ld.validThrough ?? null,
      employmentType: ld.employmentType ?? null,
      hiringOrganization: ld.hiringOrganization
        ? { name: ld.hiringOrganization.name ?? null, logo: ld.hiringOrganization.logo ?? null }
        : null,
      jobLocation: address
        ? {
            streetAddress: address.streetAddress ?? null,
            addressLocality: address.addressLocality ?? null,
            addressRegion: address.addressRegion ?? null,
            postalCode: address.postalCode ?? null,
            addressCountry: address.addressCountry ?? null,
          }
        : null,
      description: ld.description ?? null,
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title ?? "N/A"}`)
      console.log(`Company: ${result.hiringOrganization?.name ?? "N/A"}`)
      if (result.jobLocation) {
        console.log(`Location: ${[result.jobLocation.streetAddress, result.jobLocation.postalCode, result.jobLocation.addressLocality].filter(Boolean).join(" ")}`)
      }
      console.log(`Posted: ${result.datePosted ?? "N/A"}`)
      console.log(`Deadline: ${result.validThrough ?? "N/A"}`)
      console.log(`URL: ${result.url}`)
      console.log("")
      console.log(stripHtml(result.description ?? ""))
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
