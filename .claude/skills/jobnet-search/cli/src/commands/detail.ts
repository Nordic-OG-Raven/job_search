import { defineCommand, option } from "@bunli/core"
import { z } from "zod"
import { apiFetch, writeError, stripHtml } from "../helpers.js"

export const detail = defineCommand({
  name: "detail",
  description: "Full detail for a single job ad on Jobnet.dk",
  options: {
    format: option(z.enum(["json", "plain"]).default("json"), {
      description: "Output format: json, plain",
    }),
  },
  handler: async ({ flags, positional }) => {
    const id = positional[0]
    if (!id) {
      writeError("Job ad id is required", "MISSING_REQUIRED")
      process.exit(1)
    }

    let data: any
    try {
      data = await apiFetch<any>(`/FindJob/JobAdDetails/${id}`, { incrementViews: "false" })
    } catch (err) {
      writeError((err as Error).message, "NOT_FOUND")
      process.exit(1)
    }

    if (flags.format === "plain") {
      console.log(`Title: ${data.title ?? "N/A"}`)
      console.log(`Employer: ${data.employer?.name ?? "N/A"}`)
      const addr = data.job?.address
      if (addr) {
        console.log(`Location: ${[addr.streetName, addr.houseNumber, addr.postalCode, addr.city].filter(Boolean).join(" ")}`)
      }
      console.log(`Published: ${data.publicationDateTime ?? "N/A"}`)
      console.log(`Deadline: ${data.application?.deadlineDate ?? "N/A"}`)
      console.log(`Apply URL: ${data.application?.url || "N/A"}`)
      console.log(`URL: https://jobnet.dk/job/${data.id}`)
      console.log("")
      console.log(stripHtml(data.body ?? ""))
    } else {
      console.log(JSON.stringify(data, null, 2))
    }
  },
})
