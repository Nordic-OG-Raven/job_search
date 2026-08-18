import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, DETAIL_PATH, extractBalancedSpan, fetchHtml, stripHtml, writeError } from "../helpers.js"

interface JobDetail {
  jobId: string
  title: string
  originalTitle: string | null
  employer: string | null
  location: string | null
  workLocation: string | null
  salary: string | null
  employmentType: string | null
  postedDate: string | null
  validThrough: string | null
  modifiedDate: string | null
  source: string | null
  url: string
  description: string
}

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job posting on Job Bank (Canada)",
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
    if (!/^\d+$/.test(id)) {
      writeError("Job id must be numeric", "INVALID_ID")
      process.exit(1)
    }

    let html: string
    try {
      html = await fetchHtml(`${BASE_URL}${DETAIL_PATH}${id}`)
    } catch (err) {
      const message = (err as Error).message
      if (message.includes("410") || message.includes("404")) {
        writeError("Job not found", "NOT_FOUND")
      } else {
        writeError(message, "FETCH_ERROR")
      }
      process.exit(1)
    }

    if (!html.includes(`property="title"`)) {
      writeError("Job not found", "NOT_FOUND")
      process.exit(1)
    }

    const title = (extractBalancedSpan(html, "title") ?? "").trim()

    // Aggregated listings show the employer's original title separately,
    // e.g. <p class="source-title">Title posted on Indeed.com - <span>Full Stack Python Developer</span></p>
    const sourceTitleMatch = html.match(/class="source-title"[^>]*>([\s\S]*?)<\/p>/)
    let originalTitle: string | null = null
    let source: string | null = null
    if (sourceTitleMatch) {
      const labelMatch = sourceTitleMatch[1]!.match(/Title posted on ([^<]*?)\s*-/)
      source = labelMatch ? labelMatch[1]!.trim() : null
      const innerMatch = sourceTitleMatch[1]!.match(/<span class="source-title-inner">[\s\S]*?<\/span>([\s\S]*)/)
      originalTitle = innerMatch ? stripHtml(innerMatch[1]!) : null
    }

    // hiringOrganization's "name" is nested inside the hiringOrganization block —
    // search from there to skip the page's earlier publisher "name" (Government of Canada).
    const orgIdx = html.indexOf('property="hiringOrganization"')
    const employer = orgIdx === -1 ? null : stripHtml(extractBalancedSpan(html, "name", orgIdx) ?? "")

    const addressLocality = html.match(/property="addressLocality">([^<]*)</)?.[1]?.trim() ?? null
    const addressRegion = html.match(/property="addressRegion">([^<]*)</)?.[1]?.trim() ?? null
    const location = [addressLocality, addressRegion].filter(Boolean).join(", ") || null

    const workLocationMatch = html.match(/fa-building[^<]*<\/span>\s*<span class="wb-inv">[^<]*<\/span>\s*<span>([^<]*)<\/span>/)
    const workLocation = workLocationMatch ? workLocationMatch[1]!.trim() : null

    const salaryRaw = extractBalancedSpan(html, "baseSalary")
    const salary = salaryRaw
      ? stripHtml(salaryRaw).replace(/\b(YEAR|HOUR|WEEK|MONTH|DAY)\b/, "").replace(/\s+/g, " ").trim()
      : null

    const employmentTypeRaw = extractBalancedSpan(html, "employmentType")
    const employmentType = employmentTypeRaw ? stripHtml(employmentTypeRaw) : null

    const postedDateMatch = html.match(/property="datePosted"[^>]*>([\s\S]*?)<\/span>/)
    const postedDate = postedDateMatch ? stripHtml(postedDateMatch[1]!).replace(/^Posted on\s*/, "") : null

    const validThrough = html.match(/property="validThrough">([^<]*)/)?.[1]?.trim() ?? null
    const modifiedDate = html.match(/property="dateModified">([^<]*)</)?.[1]?.trim() ?? null

    const descriptionRaw = extractBalancedSpan(html, "description") ?? ""
    const description = stripHtml(descriptionRaw)

    const result: JobDetail = {
      jobId: id,
      title: title.trim(),
      originalTitle,
      employer,
      location,
      workLocation,
      salary,
      employmentType,
      postedDate,
      validThrough,
      modifiedDate,
      source,
      url: `${BASE_URL}${DETAIL_PATH}${id}`,
      description,
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title}`)
      if (result.originalTitle && result.originalTitle !== result.title) {
        console.log(`Original title (${result.source ?? "source"}): ${result.originalTitle}`)
      }
      console.log(`Employer: ${result.employer ?? "N/A"}`)
      if (result.location) console.log(`Location: ${result.location}`)
      if (result.workLocation) console.log(`Work location: ${result.workLocation}`)
      if (result.salary) console.log(`Salary: ${result.salary}`)
      if (result.employmentType) console.log(`Employment type: ${result.employmentType}`)
      console.log(`Posted: ${result.postedDate ?? "N/A"}`)
      if (result.validThrough) console.log(`Valid through: ${result.validThrough}`)
      console.log(`URL: ${result.url}`)
      console.log("")
      console.log(result.description)
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
