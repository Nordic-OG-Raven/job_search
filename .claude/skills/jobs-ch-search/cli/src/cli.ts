import { createCLI } from "@bunli/core"
import { search } from "./commands/search.js"
import { detail } from "./commands/detail.js"

const cli = await createCLI({
  name: "jobs-ch-cli",
  version: "1.0.0",
  description: "CLI for jobs.ch (Switzerland) job search, server-rendered search/detail pages",
})

cli.command(search)
cli.command(detail)

await cli.run()
