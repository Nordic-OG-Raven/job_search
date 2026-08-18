import { createCLI } from "@bunli/core"
import { search } from "./commands/search.js"
import { detail } from "./commands/detail.js"

const cli = await createCLI({
  name: "jobbank-ca-cli",
  version: "1.0.0",
  description: "CLI for Job Bank (jobbank.gc.ca), the Government of Canada job search portal",
})

cli.command(search)
cli.command(detail)

await cli.run()
