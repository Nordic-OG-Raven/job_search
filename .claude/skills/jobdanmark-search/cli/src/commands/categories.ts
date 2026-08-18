import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, writeError } from "../helpers.js"

interface Category {
  id: number
  title: string
  helpText: string
  count: number
}

export const categories = defineCommand({
  name: "categories",
  description: "List all job categories with live counts",
  options: {
    limit: option(z.coerce.number().int().positive().optional(), {
      description: "Cap number of categories returned",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    let data: Category[]
    try {
      data = await apiFetch<Category[]>("/api/categorycount/getcounts")
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
    } else if (flags.format === "plain") {
      for (const c of results) {
        console.log(`${c.id}: ${c.title} (${c.count})`)
      }
    } else {
      for (const c of results) {
        console.log(`${String(c.id).padEnd(8)} ${c.title.padEnd(45)} ${c.count}`)
      }
    }
  },
})
