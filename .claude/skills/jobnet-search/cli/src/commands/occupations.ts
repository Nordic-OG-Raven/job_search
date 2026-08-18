import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, writeError } from "../helpers.js"

interface Occupation {
  conceptUriDa: string
  preferredLabelDa: string
  aliases: { aliasIdentifier: string; conceptUriDa: string; alternativeLabelDa: string }[]
}

export const occupations = defineCommand({
  name: "occupations",
  description: "Search occupation types (for building search filters)",
  options: {
    "search-string": option(z.string().optional(), {
      description: "Search term for occupation, e.g. sygeplejerske",
    }),
    "per-page": option(z.coerce.number().int().positive().default(10), {
      description: "Max results to return",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    if (!flags["search-string"]) {
      writeError("--search-string is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    let data: Occupation[]
    try {
      data = await apiFetch<Occupation[]>("/OccupationSearch", { searchString: flags["search-string"] })
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    const results = data.slice(0, flags["per-page"])

    if (flags.format === "json") {
      console.log(JSON.stringify(results, null, 2))
    } else if (flags.format === "plain") {
      for (const r of results) {
        const id = r.conceptUriDa.split("/").pop()
        console.log(`${r.preferredLabelDa} (${id})`)
      }
    } else {
      for (const r of results) {
        const id = r.conceptUriDa.split("/").pop()
        console.log(`${(id ?? "").padEnd(38)} ${r.preferredLabelDa}`)
      }
    }
  },
})
