import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { BASE_URL, htmlFetch, decodeHtmlEntities, stripTags, writeError } from "../helpers.js"

interface JobDetail {
  id: string
  title: string | null
  company: string | null
  companyUrl: string | null
  location: string | null
  date: string | null
  deadline: string | null
  employmentType: string | null
  hours: string | null
  applyUrl: string | null
  url: string
  description: string | null
}

export const detail = defineCommand({
  name: "detail",
  description: "Fetch full detail for a single job listing",
  options: {
    format: option(z.enum(["json", "plain"]).default("json"), {
      description: "Output format: json, plain",
    }),
  },
  handler: async ({ flags, positional }) => {
    const arg = positional[0]
    if (!arg) {
      writeError("Job id or URL is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    let id: string
    let url: string
    if (arg.startsWith("http")) {
      url = arg
      const m = arg.match(/\/(?:vis-job|jobannonce)\/(\w+)/)
      id = m ? m[1] : arg
    } else {
      id = arg
      url = `${BASE_URL}/vis-job/${id}`
    }

    let html: string
    try {
      html = await htmlFetch(url)
    } catch (err) {
      writeError((err as Error).message, "NOT_FOUND")
      process.exit(1)
    }

    const mainMatch = html.match(/<main[\s\S]*?<\/main>/)
    const main = mainMatch ? mainMatch[0] : html

    const innerMatch = main.match(/class="(?:PaidJob|jix_robotjob)-inner"[^>]*>([\s\S]*?)<div class="jix_toolbar/)
    const inner = innerMatch ? innerMatch[1] : main

    if (!inner) {
      writeError("Failed to parse job listing HTML", "PARSE_ERROR")
      process.exit(1)
    }

    const titleMatch = inner.match(/<h4[^>]*>[\s\S]*?<[Aa][^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/[Aa]>/i)
    const title = titleMatch ? decodeHtmlEntities(stripTags(titleMatch[2])) : null

    let company: string | null = null
    let companyUrl: string | null = null
    const companySection = main.match(/class="jix-toolbar-top__company"[^>]*>([\s\S]*?)<\/div>/i)
    if (companySection) {
      const companyLinkMatch = companySection[1].match(/<[Aa][^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/[Aa]>/i)
      if (companyLinkMatch) {
        companyUrl = companyLinkMatch[1] || null
        company = decodeHtmlEntities(stripTags(companyLinkMatch[2])) || null
      }
    }

    const locMatch = inner.match(/<span[^>]+class="jix_robotjob--area"[^>]*>([\s\S]*?)<\/span>/i)
    const location = locMatch ? decodeHtmlEntities(stripTags(locMatch[1])) || null : null

    const dateMatch = main.match(/jix-toolbar__pubdate[\s\S]*?<time[^>]+datetime="([^"]+)"/i)
    const date = dateMatch ? dateMatch[1] : null

    let applyUrl: string | null = null
    const applyMatch = main.match(/class="btn btn-sm btn-primary seejobdesktop"[^>]*href="([^"]+)"/i)
    if (applyMatch) {
      applyUrl = decodeHtmlEntities(applyMatch[1])
    }

    let description: string | null = null
    const pMatches = [...inner.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/gi)]
    const paragraphs = pMatches
      .map((pm) => decodeHtmlEntities(stripTags(pm[1])))
      .filter((text) => text.length > 0)
    if (paragraphs.length > 0) {
      description = paragraphs.join("\n\n")
    }

    const result: JobDetail = {
      id,
      title,
      company,
      companyUrl,
      location,
      date,
      deadline: null,
      employmentType: null,
      hours: null,
      applyUrl,
      url,
      description,
    }

    if (flags.format === "plain") {
      console.log(`Title: ${result.title ?? "N/A"}`)
      console.log(`Company: ${result.company ?? "N/A"}`)
      console.log(`Location: ${result.location ?? "N/A"}`)
      console.log(`Posted: ${result.date ?? "N/A"}`)
      console.log(`Apply URL: ${result.applyUrl ?? "N/A"}`)
      console.log(`URL: ${result.url}`)
      console.log("")
      console.log(result.description ?? "")
    } else {
      console.log(JSON.stringify(result, null, 2))
    }
  },
})
