import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, writeError } from "../helpers.js"

interface SuggestionGroup {
  title: string
  items: {
    id: string
    text: string
    value: number | string
    category: string
    slug: string
  }[]
}

export const autocomplete = defineCommand({
  name: "autocomplete",
  description: "Suggest job titles and categories for a query",
  options: {
    query: option(z.string().optional(), {
      description: "Search text to autocomplete",
    }),
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap total suggestions returned",
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

    let data: SuggestionGroup[]
    try {
      data = await apiFetch<SuggestionGroup[]>("/api/search/autocomplete", { q: flags.query })
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    let groups = data ?? []
    if (flags.limit) {
      let remaining = flags.limit
      groups = groups
        .map((g) => {
          if (remaining <= 0) return null
          const items = g.items.slice(0, remaining)
          remaining -= items.length
          return { ...g, items }
        })
        .filter((g): g is SuggestionGroup => g !== null && g.items.length > 0)
    }

    if (flags.format === "json") {
      console.log(JSON.stringify(groups, null, 2))
    } else if (flags.format === "plain") {
      for (const g of groups) {
        for (const item of g.items) {
          console.log(`${item.text} (${item.category}: ${item.value})`)
        }
      }
    } else {
      for (const g of groups) {
        console.log(g.title)
        for (const item of g.items) {
          console.log(`  ${String(item.value).padEnd(10)} ${item.text}`)
        }
      }
    }
  },
})
