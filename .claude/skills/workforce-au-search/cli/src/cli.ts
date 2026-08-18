import { createCLI } from "@bunli/core"
import { search } from "./commands/search.js"
import { detail } from "./commands/detail.js"

const cli = await createCLI({
  name: "workforce-au-cli",
  version: "1.0.0",
  description: "CLI for Workforce Australia (workforceaustralia.gov.au) job search",
})

cli.command(search)
cli.command(detail)

await cli.run()
