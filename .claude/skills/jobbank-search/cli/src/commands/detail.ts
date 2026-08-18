import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, fetchWithUA, writeError } from "../helpers.js"

interface JobDetail {
  id: string
  url: string
  title: string | null
  description: string | null
  datePosted: string | null
  deadline: string | null
  employmentType: string[] | null
  company: { name: string | null; logo: string | null } | null
  location: {
    streetAddress: string
    city: string
    postalCode: string
    country: string
  } | null
}

function stripHtml(html: string): string {
  return html.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim()
}

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job posting",
  options: {
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

    let html: string
    try {
      const res = await fetchWithUA(`${BASE_URL}/job/${id}/`)
      if (!res.ok) {
        writeError("Job not found", "NOT_FOUND")
        process.exit(1)
      }
      html = await res.text()
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const ldMatch = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/i)
    if (!ldMatch) {
      writeError("No JSON-LD found on job page", "PARSE_ERROR")
      process.exit(1)
    }

    let ld: any
    try {
      ld = JSON.parse(ldMatch[1])
    } catch {
      writeError("No JSON-LD found on job page", "PARSE_ERROR")
      process.exit(1)
    }

    const address = ld.jobLocation?.address

    const result: JobDetail = {
      id: ld.identifier?.value ?? id,
      url: ld.url ?? `${BASE_URL}/job/${id}/`,
      title: ld.title ?? null,
      description: ld.description ?? null,
      datePosted: ld.datePosted ?? null,
      deadline: ld.validThrough ?? null,
      employmentType: ld.employmentType ?? null,
      company: ld.hiringOrganization
        ? { name: ld.hiringOrganization.name ?? null, logo: ld.hiringOrganization.logo ?? null }
        : null,
      location: address
        ? {
            streetAddress: address.streetAddress ?? "",
            city: address.addressLocality ?? "",
            postalCode: address.postalCode ?? "",
            country: address.addressCountry ?? "",
          }
        : null,
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title ?? "N/A"}`)
      console.log(`Company: ${result.company?.name ?? "N/A"}`)
      if (result.location) {
        console.log(`Location: ${[result.location.streetAddress, result.location.postalCode, result.location.city].filter(Boolean).join(" ")}`)
      }
      console.log(`Posted: ${result.datePosted ?? "N/A"}`)
      console.log(`Deadline: ${result.deadline ?? "N/A"}`)
      console.log(`URL: ${result.url}`)
      console.log("")
      console.log(stripHtml(result.description ?? ""))
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
