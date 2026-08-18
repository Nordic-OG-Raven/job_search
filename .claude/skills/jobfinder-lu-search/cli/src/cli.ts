import { createCLI } from "@bunli/core"
import { search } from "./commands/search.js"
import { detail } from "./commands/detail.js"
import { filters } from "./commands/filters.js"

const cli = await createCLI({
  name: "jobfinder-lu-cli",
  version: "1.0.0",
  description: "CLI for the Jobfinder.lu (Luxembourg) public job search API",
})

cli.command(search)
cli.command(detail)
cli.command(filters)

await cli.run()
