import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, DETAIL_PATH, apiFetch, writeError } from "../helpers.js"

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
  contractType: string | null
  salary: CodedLabel | null
  industry: CodedLabel | null
  occupation: CodedLabel | null
  positionsAvailable: number | null
  isNewJob: boolean
  isExternalJob: boolean
  isApplyOnlineJob: boolean
  howToApplyCode: string | null
  creationDate: string | null
  displayFromDate: string | null
  expiryDate: string | null
  modifiedDate: string | null
  logoUrl: string | null
}

interface VacanciesResponse {
  totalCount: number
  results: { score: number; result: RawResult }[]
}

interface JobDetail {
  vacancyId: number
  title: string
  employer: string | null
  location: string | null
  state: string | null
  suburb: string | null
  postCode: string | null
  jobType: string | null
  workType: string | null
  tenure: string | null
  contractType: string | null
  salary: string | null
  industry: string | null
  occupation: string | null
  positionsAvailable: number | null
  isNew: boolean
  isExternal: boolean
  descriptionIsFull: boolean
  description: string
  postedDate: string | null
  expiryDate: string | null
  logoUrl: string | null
  url: string
}

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job posting on Workforce Australia",
  options: {
    format: option(z.enum(["json", "plain"]).default("json"), {
      description: "Output format: json, plain",
    }),
  },
  handler: async ({ flags, positional }) => {
    const id = positional[0]
    if (!id) {
      writeError("Vacancy id is required", "MISSING_REQUIRED")
      process.exit(1)
    }
    if (!/^\d+$/.test(id)) {
      writeError("Vacancy id must be numeric", "INVALID_ID")
      process.exit(1)
    }

    let data: VacanciesResponse
    try {
      data = await apiFetch<VacanciesResponse>({ vacancyIds: id })
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const raw = data.results[0]?.result
    if (!raw) {
      writeError("Job not found", "NOT_FOUND")
      process.exit(1)
    }

    const result: JobDetail = {
      vacancyId: raw.vacancyId,
      title: raw.title,
      employer: raw.employerName || raw.organisation?.label || null,
      location: raw.location?.label ?? null,
      state: raw.state,
      suburb: raw.suburb,
      postCode: raw.postCode,
      jobType: raw.jobType?.label ?? null,
      workType: raw.workType?.label ?? null,
      tenure: raw.tenure?.label ?? null,
      contractType: raw.contractType,
      salary: raw.salary?.label ?? null,
      industry: raw.industry?.label ?? null,
      occupation: raw.occupation?.label ?? null,
      positionsAvailable: raw.positionsAvailable,
      isNew: !!raw.isNewJob,
      isExternal: !!raw.isExternalJob,
      // Internal (non-external) listings carry the full job description in this
      // field. External/aggregated listings (e.g. Adzuna-sourced) only ever carry
      // a ~250-char teaser ending in "View more detail / apply" — Workforce
      // Australia itself doesn't hold a fuller description for those, so the only
      // way to read the full posting is via the employer's original listing.
      descriptionIsFull: !raw.isExternalJob,
      description: raw.description.replace(/\s+/g, " ").trim(),
      postedDate: raw.creationDate,
      expiryDate: raw.expiryDate,
      logoUrl: raw.logoUrl ? `${BASE_URL}${raw.logoUrl}` : null,
      url: `${BASE_URL}${DETAIL_PATH}${raw.vacancyId}`,
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title}`)
      console.log(`Employer: ${result.employer ?? "N/A"}`)
      const loc = [result.location, result.state].filter(Boolean).join(", ")
      if (loc) console.log(`Location: ${loc}`)
      if (result.workType) console.log(`Work type: ${result.workType}`)
      if (result.tenure) console.log(`Tenure: ${result.tenure}`)
      if (result.salary) console.log(`Salary: ${result.salary}`)
      if (result.occupation) console.log(`Occupation: ${result.occupation}`)
      if (result.industry) console.log(`Industry: ${result.industry}`)
      console.log(`Posted: ${result.postedDate ?? "N/A"}`)
      console.log(`Expires: ${result.expiryDate ?? "N/A"}`)
      console.log(`URL: ${result.url}`)
      if (!result.descriptionIsFull) {
        console.log("")
        console.log("(External listing — Workforce Australia only provides a short snippet; follow the URL above to apply and view the full posting)")
      }
      console.log("")
      console.log(result.description)
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
