import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, writeError, stripHtml, decodeEntities } from "../helpers.js"

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

    // Attribute-tolerant: the `+` in the ld+json mime type is HTML-encoded as
    // &#x2B; on jobdanmark, and there may be other attributes on the tag.
    const ldMatch = html.match(/<script[^>]*type="application\/ld(?:\+|&#x2B;)json"[^>]*>([\s\S]*?)<\/script>/i)
    if (!ldMatch) {
      writeError("Failed to parse JSON-LD from job page", "PARSE_ERROR")
      process.exit(1)
    }

    let ld: any
    try {
      // jobdanmark embeds RAW tab/newline characters inside the JSON-LD
      // description string — illegal control chars in a JSON string, which made
      // JSON.parse throw for ~half of all listings (university/PhD/analyst roles
      // etc.) and silently buried them. Replace control chars with spaces, then
      // parse. HTML entities are decoded AFTER parsing, per text field, so a
      // &quot;/&amp; inside a description can't corrupt the JSON structure (the
      // old pre-parse decode risked exactly that).
      const cleaned = ldMatch[1].replace(/[\u0000-\u001F]/g, " ")
      ld = JSON.parse(cleaned)
    } catch {
      writeError("Failed to parse JSON-LD from job page", "PARSE_ERROR")
      process.exit(1)
    }

    // JSON-LD may be a single object, an array, or wrapped in @graph — pick the
    // JobPosting node.
    if (Array.isArray(ld)) {
      ld = ld.find((x: any) => x?.["@type"] === "JobPosting") ?? ld[0]
    } else if (Array.isArray(ld?.["@graph"])) {
      ld = ld["@graph"].find((x: any) => x?.["@type"] === "JobPosting") ?? ld
    }

    const address = ld.jobLocation?.address
    const result: JobDetail = {
      slug,
      url,
      title: ld.title ? decodeEntities(ld.title) : null,
      datePosted: ld.datePosted ?? null,
      validThrough: ld.validThrough ?? null,
      employmentType: ld.employmentType ?? null,
      hiringOrganization: ld.hiringOrganization
        ? { name: ld.hiringOrganization.name ? decodeEntities(ld.hiringOrganization.name) : null, logo: ld.hiringOrganization.logo ?? null }
        : null,
      jobLocation: address
        ? {
            streetAddress: address.streetAddress ? decodeEntities(address.streetAddress) : null,
            addressLocality: address.addressLocality ? decodeEntities(address.addressLocality) : null,
            addressRegion: address.addressRegion ? decodeEntities(address.addressRegion) : null,
            postalCode: address.postalCode ?? null,
            addressCountry: address.addressCountry ?? null,
          }
        : null,
      description: ld.description ? decodeEntities(ld.description) : null,
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
