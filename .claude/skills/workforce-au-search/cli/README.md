# Workforce Australia CLI

CLI for [Workforce Australia](https://www.workforceaustralia.gov.au), the Australian
government's national job search portal (Department of Employment and Workplace
Relations). No authentication required.

Workforce Australia exposes a public, unauthenticated JSON API at
`GET /api/v1/global/vacancies/` that backs its own search page — this CLI calls that
API directly rather than scraping HTML. Note: `curl` gets a TLS connection reset on
`www.workforceaustralia.gov.au` (a TLS-fingerprinting block against curl's TLS stack);
`fetch` from Node or Bun works fine.

## Commands

### `search`

```bash
bun run src/cli.ts search [flags]
```

Flags:
- `--search-text <text>` — free-text search (job title, skill, employer), e.g. `python developer`
- `--city <name>` — restrict to a capital-city region via Workforce Australia's own `locationCodes` filter. One of: `sydney`, `melbourne`, `brisbane`, `perth`, `adelaide`, `hobart`, `canberra`, `darwin`
- `--sort none|title-asc|title-desc|date-asc|date-desc` — sort order, default `date-desc` (most recent first)
- `--page <n>` — page number (1-indexed), default 1
- `--limit <n>` — results per page, max 100, default 10
- `--format json|table|plain`

### `detail`

```bash
bun run src/cli.ts detail <vacancyId> [--format json|plain]
```

Fetches `GET /api/v1/global/vacancies/?vacancyIds={id}` and returns title, employer,
location, work type, tenure, salary, occupation, industry, dates, and description.

`vacancyId` is the numeric ID returned as `vacancyId` in `search` results.

---

## Location filtering — how it works

`--city` maps to `locationCodes`, a real server-side geographic filter (confirmed:
changing it changes `totalCount`, and every result's `location.label` matches the
expected city/region). The 8 supported values are Workforce Australia's "capital city
(ALL)" region codes — the finest granularity exposed by the search API; there is no
per-suburb code list. `--search-text` is always sent (even empty) alongside
`locationCodes` so results aren't unexpectedly restricted.

---

## Description completeness

Each result's `description` field comes directly from the API and is **not always the
full posting**:

- **Internal listings** (`isExternal: false` / `isExternal` omitted) — `description`
  is the complete job description as submitted to Workforce Australia (plain text).
- **External/aggregated listings** (`isExternal: true`, typically sourced via Adzuna)
  — `description` is only a ~250-character teaser ending in "View more detail / apply".
  Workforce Australia itself does not hold a fuller description for these; the `detail`
  command surfaces this via `descriptionIsFull: false` and a note in `--format plain`
  output, with `url` pointing to the listing page to view/apply for the full posting.

---

## Notes

- All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.
- `detail` returns `NOT_FOUND` if the vacancy ID doesn't exist or has expired.
- `employer` falls back to `organisation.label` (e.g. `"Adzuna ORG"`) when `employerName` is blank — common for external/aggregated listings where Workforce Australia doesn't have the employer's name.
