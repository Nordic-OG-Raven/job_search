# Jobfinder.lu CLI

CLI for the public Jobfinder.lu (Luxembourg) job board API at `https://api.jobfinder.lu`. No authentication required.

Jobfinder.lu exposes a documented FastAPI/OpenAPI backend (`https://api.jobfinder.lu/openapi.json`), so this CLI talks to it directly rather than scraping HTML.

## Commands

### `search`

```bash
bun run src/cli.ts search [flags]
```

Searches live job offers via `POST /offer/search`.

Flags:
- `--query <text>` — free-text search (job title, skill, company)
- `--filter <id>` — filter ID from the `filters` command (category, contract type, working time, experience, education level). Repeatable, e.g. `--filter <id1> --filter <id2>` (AND semantics on the API side)
- `--sort <date|relevance|initial_online>` — sort order, default `relevance`
- `--status <draft|pending|online|archived>` — offer status, default `online`. Repeatable
- `--since <YYYY-MM-DD>` — only offers first online on/after this date
- `--offset <n>` — pagination offset, default 0
- `--limit <n>` — number of results, default 10, max 50
- `--format json|table|plain`

### `detail`

```bash
bun run src/cli.ts detail <id> [--format json|plain]
```

Fetches `GET /offer/{id}` and returns full job details: title, full HTML description, hours per week, contract/category/experience/education tags (resolved to human-readable labels via `/filters`), apply-via website/email, and company contact/address.

`id` is the offer ID returned as `id` in `search` results (a 24-character hex string).

### `filters`

```bash
bun run src/cli.ts filters [--group <name>] [--format json|table|plain]
```

Returns the filter taxonomy from `GET /filters`: five groups — **Contract**, **Working time**, **Categories** (sector, ~80 values), **Experience**, **Educational level** — each with filter IDs and English labels. Use `--group` to narrow to one group by code or label substring, e.g. `--group contract` or `--group categories`.

Use the `id` values from this command as `--filter` arguments to `search`.

---

## Notes

- All data comes from the public `api.jobfinder.lu` API — no credentials required.
- Title and description fields are multi-language objects (`en`, `fr`, `de`, `lb`, `pt`); the CLI picks English first, falling back to French, German, Luxembourgish, Portuguese, then any available language.
- Jobfinder.lu does not expose a location/region filter group — Luxembourg is small enough that company address (in `detail`) carries location info instead.
- `search` results don't include the job's filter tags or description (lightweight search view) — call `detail <id>` for the full posting.
- All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.
