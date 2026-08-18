import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, writeError } from "../helpers.js"

export const suggestions = defineCommand({
  name: "suggestions",
  description: "Typeahead suggestions for job title / keyword search",
  options: {
    query: option(z.string().min(1), {
      description: "Partial search string to complete",
    }),
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap number of suggestions returned",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    if (!flags.query) {
      writeError("--query is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    let data: string[]
    try {
      data = await apiFetch<string[]>("/FindJob/GetTypeaheadSuggestions", { query: flags.query })
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    let results = data ?? []
    if (flags.limit) {
      results = results.slice(0, flags.limit)
    }

    if (flags.format === "json") {
      console.log(JSON.stringify(results, null, 2))
    } else {
      for (const r of results) {
        console.log(r)
      }
    }
  },
})
