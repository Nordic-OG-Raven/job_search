---
name: workforce-au-search
version: 1.0.0
description: >
  Make sure to use this skill whenever the user mentions anything related to job
  listings in Australia, job search in Australia, finding work in Australia, or
  vacancies on Workforce Australia — even if they don't explicitly mention
  workforceaustralia.gov.au. Also invoke this skill for questions about occupations,
  industries, work types, or tenure in an Australian job-search context. Trigger
  phrases include: australia jobs, jobs in australia, find job australia, job search
  australia, australian job listings, workforce australia, jobsearch.gov.au, jobs
  sydney, jobs melbourne, jobs brisbane, jobs perth, jobs adelaide, jobs hobart, jobs
  canberra, jobs darwin, IT job australia, software developer job australia, work in
  australia, employment australia, australian vacancies, full time job australia,
  part time job australia, casual job australia, NSW job, VIC job, QLD job, WA job,
  SA job, TAS job, ACT job, NT job.
context: fork
allowed-tools: Bash(bun run skills/workforce-au-search/cli/src/cli.ts *), Read(CLAUDE.md), Read(.claude/skills/job-application-assistant/08-search-fit-filter.md)
---

# Workforce Australia Search Skill

## Before presenting results: candidate fit filter

Read `CLAUDE.md` and `.claude/skills/job-application-assistant/08-search-fit-filter.md`
first, and apply the experience-level filter described there. Raw search results
include postings well outside the candidate's seniority level (e.g. "Senior",
"Manager", "Director") — these must not be presented as good/strong fits for an
early-career candidate.

Access live Australian job listings from
[Workforce Australia](https://www.workforceaustralia.gov.au), the federal government's
national job search portal (Department of Employment and Workplace Relations). No
authentication needed — the CLI calls Workforce Australia's own public JSON API.

## When to use this skill

Invoke this skill when the user wants to:

- Search for job listings in Australia (by keyword, work type, location)
- Search specifically in a capital city region (Sydney, Melbourne, Brisbane & Gold
  Coast, Perth, Adelaide, Hobart, Canberra & Queanbeyan, Darwin)
- Look up the full details of a specific job posting including description, employer,
  location, salary, occupation, and industry
- Browse jobs in a specific Australian city (e.g. "jobs in Perth", "jobs in Melbourne")

## Commands

### Search job listings

```bash
bun run skills/workforce-au-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--search-text <text>` — free-text search, e.g. `python`, `registered nurse`, `data analyst`
- `--city <name>` — restrict to a capital-city region, a real server-side filter. One
  of: `sydney`, `melbourne`, `brisbane`, `perth`, `adelaide`, `hobart`, `canberra`, `darwin`
- `--sort none|title-asc|title-desc|date-asc|date-desc` — default `date-desc` (newest first)
- `--page <n>` / `--limit <n>` — pagination; max 100 results per page, default 10
- `--format json|table|plain`

### Full job detail

```bash
bun run skills/workforce-au-search/cli/src/cli.ts detail <vacancyId> [--format json|plain]
```

`vacancyId` is the numeric ID returned as `vacancyId` in `search` results. Returns
title, employer, location, work type, tenure, salary, occupation, industry, dates, and
description.

---

## How to use effectively

**For a specific city**, always pass `--city <name>`. This maps to Workforce
Australia's own `locationCodes` region filter (a single server-side request) —
`totalCount` reflects the full region-wide count and every result's location matches
the city. There is no finer per-suburb filter; the 8 capital-city regions are the most
specific geographic filter available.

**Natural workflow: `search` → `detail`.**
1. Use `search` to get matching jobs with their `vacancyId`, employer, and location.
2. Call `detail <vacancyId>` for the full posting.

**Description completeness**: most listings on Workforce Australia are sourced from
external job boards (notably Adzuna). For these (`isExternal: true`), the
`description`/`snippet` is only a short teaser — the `detail` command flags this with
`descriptionIsFull: false` and points to the listing `url` to view the full posting and
apply. Listings posted directly to Workforce Australia (`isExternal: false`) include the
complete description.

---

## Usage examples

### Python jobs in Sydney

```bash
bun run skills/workforce-au-search/cli/src/cli.ts search \
  --search-text python --city sydney --limit 25 --format table
```

### Most recent jobs nationwide

```bash
bun run skills/workforce-au-search/cli/src/cli.ts search \
  --sort date-desc --limit 25 --format table
```

### Full details for a specific job posting

```bash
bun run skills/workforce-au-search/cli/src/cli.ts detail 2350265551 --format plain
```

---

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, data processing, passing IDs between commands |
| `table` | Quick human-readable overviews and comparisons |
| `plain` | Single-record detail views (`detail`), or simple listings |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

---

## Notes

- All data is from `https://www.workforceaustralia.gov.au/api/v1/global/vacancies/`, the public API behind Workforce Australia's own search page — no credentials required.
- `search` results include `employer` (falls back to the source feed name, e.g. `"Adzuna ORG"`, when the employer's name isn't supplied), `location`, `workType`, `salary`, and `isExternal`.
- The job posting page on the live site is `https://www.workforceaustralia.gov.au/individuals/jobs/details/<vacancyId>`.
