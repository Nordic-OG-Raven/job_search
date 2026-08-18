import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, pickLang, writeError, type LangMap } from "../helpers.js"

interface RawFilter {
  id: string
  title: LangMap
  code?: string | null
  filters: RawFilter[]
}

interface FilterItem {
  id: string
  code: string | null
  label: string | null
}

interface FilterGroup {
  id: string
  code: string | null
  label: string | null
  filters: FilterItem[]
}

function mapFilter(f: RawFilter): FilterItem {
  return { id: f.id, code: f.code ?? null, label: pickLang(f.title) }
}

export const filters = defineCommand({
  name: "filters",
  description: "List the filter taxonomy (categories, contract type, working time, experience, education) with IDs for use with search --filter",
  options: {
    group: option(z.string().optional(), {
      description: "Only show the group matching this code or label (case-insensitive substring), e.g. 'contract', 'categories'",
    }),
    format: option(z.enum(["json", "table", "plain"]).default("json"), {
      description: "Output format: json, table, plain",
    }),
  },
  handler: async ({ flags }) => {
    let data: RawFilter[]
    try {
      data = await apiFetch<RawFilter[]>("/filters")
    } catch (err) {
      writeError((err as Error).message, "API_ERROR")
      process.exit(1)
    }

    let groups: FilterGroup[] = data.map((g) => ({
      id: g.id,
      code: g.code ?? null,
      label: pickLang(g.title),
      filters: g.filters.map(mapFilter),
    }))

    if (flags.group) {
      const needle = flags.group.toLowerCase()
      groups = groups.filter(
        (g) => g.code?.toLowerCase().includes(needle) || g.label?.toLowerCase().includes(needle)
      )
      if (groups.length === 0) {
        writeError(`No filter group matches '${flags.group}'`, "NOT_FOUND")
        process.exit(1)
      }
    }

    if (flags.format === "json") {
      console.log(JSON.stringify(groups, null, 2))
    } else if (flags.format === "plain") {
      for (const g of groups) {
        console.log(`${g.label ?? g.code ?? g.id}`)
        for (const f of g.filters) {
          console.log(`  ${f.id}  ${f.label ?? "?"}`)
        }
      }
    } else {
      for (const g of groups) {
        console.log(`== ${g.label ?? g.code ?? g.id} (${g.code ?? "no code"}) ==`)
        for (const f of g.filters) {
          console.log(`  ${f.id}  ${(f.label ?? "?").padEnd(40)} ${f.code ?? ""}`)
        }
        console.log("")
      }
    }
  },
})
