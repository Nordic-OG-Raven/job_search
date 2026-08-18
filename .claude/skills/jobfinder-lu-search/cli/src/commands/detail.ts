import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, pickLang, stripHtml, writeError, type LangMap } from "../helpers.js"

interface RawFilter {
  id: string
  title: LangMap
  code?: string | null
  filters: RawFilter[]
}

interface ApplicationProcedure {
  on_site: boolean
  mail: string | null
  website: string | null
  postal: boolean | null
  hr_office: boolean
}

interface Job {
  title: LangMap
  reference: string
  description: LangMap
  application_procedure: ApplicationProcedure
  hours_per_week: number | null
  fixed_term_months: number | null
  filters: string[]
}

interface UserOfferView {
  id: string
  job: Job
  visible_online: string | null
  status: string
  apply_before: string | null
  allowed_continents: string[]
}

interface CompanyAddress {
  address: string | null
  city: string | null
  postal_code: string | null
  country: string | null
}

interface UserCompanyViewForOffer {
  id: string
  name: string
  slug: string
  contact: {
    address: CompanyAddress | null
    phone: string | null
    mail: string | null
    fax: string | null
  } | null
  profile: {
    website: string | null
    description: LangMap
  } | null
}

interface OfferPageView {
  offer: UserOfferView
  company: UserCompanyViewForOffer
}

interface JobDetail {
  id: string
  url: string
  title: string | null
  reference: string | null
  status: string
  visibleOnline: string | null
  applyBefore: string | null
  hoursPerWeek: number | null
  fixedTermMonths: number | null
  tags: string[]
  applyVia: { onSite: boolean; mail: string | null; website: string | null }
  company: {
    name: string
    slug: string
    website: string | null
    address: string | null
  }
  description: string | null
}

async function buildFilterLabelMap(): Promise<Map<string, string>> {
  const map = new Map<string, string>()
  try {
    const groups = await apiFetch<RawFilter[]>("/filters")
    const walk = (items: RawFilter[]) => {
      for (const f of items) {
        const label = pickLang(f.title)
        if (label) map.set(f.id, label)
        if (f.filters?.length) walk(f.filters)
      }
    }
    walk(groups)
  } catch {
    // Best-effort: if the filter taxonomy can't be fetched, fall back to raw IDs
  }
  return map
}

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job posting on Jobfinder.lu (Luxembourg)",
  options: {
    format: option(z.enum(["json", "plain"]).default("json"), {
      description: "Output format: json, plain",
    }),
  },
  handler: async ({ flags, positional }) => {
    const id = positional[0]
    if (!id) {
      writeError("Offer id is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    let data: OfferPageView
    try {
      data = await apiFetch<OfferPageView>(`/offer/${id}`)
    } catch (err) {
      const message = (err as Error).message
      if (message.includes("404") || message.includes("422")) {
        writeError("Job not found", "NOT_FOUND")
      } else {
        writeError(message, "API_ERROR")
      }
      process.exit(1)
    }

    const labelMap = await buildFilterLabelMap()
    const { offer, company } = data
    const address = company.contact?.address
    const addressParts = address
      ? [address.address, address.postal_code, address.city, address.country?.toUpperCase()].filter(Boolean)
      : []

    const result: JobDetail = {
      id: offer.id,
      url: `https://jobfinder.lu/en/jobs/${offer.id}`,
      title: pickLang(offer.job.title),
      reference: offer.job.reference || null,
      status: offer.status,
      visibleOnline: offer.visible_online,
      applyBefore: offer.apply_before,
      hoursPerWeek: offer.job.hours_per_week,
      fixedTermMonths: offer.job.fixed_term_months,
      tags: offer.job.filters.map((f) => labelMap.get(f) ?? f),
      applyVia: {
        onSite: offer.job.application_procedure.on_site,
        mail: offer.job.application_procedure.mail,
        website: offer.job.application_procedure.website,
      },
      company: {
        name: company.name,
        slug: company.slug,
        website: company.profile?.website ?? null,
        address: addressParts.length > 0 ? addressParts.join(", ") : null,
      },
      description: pickLang(offer.job.description),
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title ?? "N/A"}`)
      console.log(`Company: ${result.company.name}`)
      if (result.company.address) console.log(`Location: ${result.company.address}`)
      if (result.hoursPerWeek) console.log(`Hours/week: ${result.hoursPerWeek}`)
      if (result.tags.length > 0) console.log(`Tags: ${result.tags.join(", ")}`)
      console.log(`Online since: ${result.visibleOnline ?? "N/A"}`)
      console.log(`Apply before: ${result.applyBefore ?? "N/A"}`)
      if (result.applyVia.website) console.log(`Apply at: ${result.applyVia.website}`)
      if (result.applyVia.mail) console.log(`Apply via email: ${result.applyVia.mail}`)
      console.log(`URL: ${result.url}`)
      console.log("")
      console.log(stripHtml(result.description ?? ""))
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
