---
name: jobbank-ca-search
version: 1.0.0
description: >
  Make sure to use this skill whenever the user mentions anything related to job
  listings in Canada, job search in Canada, finding work in Canada, or vacancies on
  Job Bank — even if they don't explicitly mention jobbank.gc.ca. Also invoke this
  skill for questions about provinces, territories, or employers in a Canadian
  job-search context. Trigger phrases include: canada jobs, jobs in canada, find job
  canada, job search canada, canadian job listings, job bank canada, jobbank.gc.ca,
  jobs toronto, jobs vancouver, jobs montreal, jobs calgary, jobs ottawa, jobs
  edmonton, jobs winnipeg, IT job canada, software developer job canada, work in
  canada, employment canada, canadian vacancies, full time job canada, part time job
  canada, Ontario job, Quebec job, British Columbia job, Alberta job, Manitoba job,
  Saskatchewan job, Nova Scotia job, New Brunswick job, Newfoundland job, PEI job,
  Yukon job, Northwest Territories job, Nunavut job.
context: fork
allowed-tools: Bash(scripts/bun_guarded.py .claude/skills/jobbank-ca-search/cli/src/cli.ts *), Read(CLAUDE.md), Read(.claude/skills/job-application-assistant/08-search-fit-filter.md)
disallowed-tools: WebSearch WebFetch Agent
---

# Job Bank (Canada) Search Skill

## If the CLI command fails

If the `bun run` command above returns a non-zero exit code, an `{"error": ...}` JSON
payload, or gets denied by a permission prompt: **stop and report the exact error to
the user verbatim**. Do not substitute results from WebSearch, WebFetch, the Indeed
MCP tools, or any other source — a silent fallback mixes data sources and misleads
the user about where results came from.

## Before presenting results: candidate fit filter

Read `CLAUDE.md` and `.claude/skills/job-application-assistant/08-search-fit-filter.md`
first, and apply the experience-level filter described there. Raw search results
include postings well outside the candidate's seniority level (e.g. "Senior",
"Manager", "Director") — these must not be presented as good/strong fits for an
early-career candidate.

Access live Canadian job listings from [Job Bank](https://www.jobbank.gc.ca), the
Government of Canada's national job search portal (Employment and Social Development
Canada). No authentication needed — the CLI scrapes Job Bank's own public search and
job-posting pages (server-rendered HTML/RDFa), in English only.

## When to use this skill

Invoke this skill when the user wants to:

- Search for job listings in Canada (by keyword, province/territory, recency)
- Search specifically within a province or territory (Ontario, Quebec, British
  Columbia, Alberta, Manitoba, Saskatchewan, Nova Scotia, New Brunswick, Newfoundland
  and Labrador, Prince Edward Island, Yukon, Northwest Territories, Nunavut)
- Look up the full details of a specific job posting including description, employer,
  location, salary, employment type, and posting dates
- Browse jobs in a specific Canadian region (e.g. "jobs in Toronto", "jobs in BC")

## Commands

### Search job listings

```bash
scripts/bun_guarded.py .claude/skills/jobbank-ca-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--search-text <text>` — free-text search, e.g. `python developer`, `registered nurse`
- `--province <code>` — restrict to a province/territory, a real server-side filter.
  One of: `ab`, `bc`, `mb`, `nb`, `nl`, `ns`, `nt`, `nu`, `on`, `pe`, `qc`, `sk`, `yt`
- `--days <n>` — only show jobs posted within the last N days
- `--sort relevance|date` — default `relevance` (best match); `date` sorts most recent first
- `--page <n>` / `--limit <n>` — pagination; 25 results per page, default limit 10
- `--format json|table|plain`

### Full job detail

```bash
scripts/bun_guarded.py .claude/skills/jobbank-ca-search/cli/src/cli.ts detail <jobId> [--format json|plain]
```

`jobId` is the numeric ID returned as `jobId` in `search` results. Returns title,
employer, location, work location, salary, employment type, posting/validity dates,
and full description.

---

## How to use effectively

**For a specific province/territory**, always pass `--province <code>`. This maps to
Job Bank's own `fprov` location filter (a single server-side request) — `totalCount`
reflects the full province-wide count and every result's location ends in `(<code>)`.
There is no finer per-city filter; province/territory is the most specific geographic
filter available.

**Natural workflow: `search` → `detail`.**
1. Use `search` to get matching jobs with their `jobId`, employer, and location.
2. Call `detail <jobId>` for the full posting.

**Description completeness**: many listings on Job Bank are aggregated from external
job boards (notably Talent.com, Indeed.com). For these, `detail` includes
`originalTitle` and `source` showing the posting's original title and source site —
the `description` is still the full text Job Bank has indexed. Listings posted
directly to Job Bank (`source: null`) come straight from the employer or Service Canada.

---

## Usage examples

### Python developer jobs in Ontario

```bash
scripts/bun_guarded.py .claude/skills/jobbank-ca-search/cli/src/cli.ts search \
  --search-text "python developer" --province on --limit 25 --format table
```

### Most recent jobs nationwide, posted in the last week

```bash
scripts/bun_guarded.py .claude/skills/jobbank-ca-search/cli/src/cli.ts search \
  --days 7 --sort date --limit 25 --format table
```

### Full details for a specific job posting

```bash
scripts/bun_guarded.py .claude/skills/jobbank-ca-search/cli/src/cli.ts detail 49701738 --format plain
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

- All data comes from `https://www.jobbank.gc.ca/jobsearch/`, Job Bank's own public
  search and job-posting pages — no credentials required. Results and descriptions are
  in English only (`sort`/`page`/`fprov` etc. are passed without a language switch, and
  Job Bank defaults to English for unauthenticated English-locale requests).
- `search` results include `employer`, `location`, `salary`, `postedDate`, and `source`
  (the aggregator site, e.g. `"Talent.com"`, or `"Job Bank"`/`null` for direct postings).
- The job posting page on the live site is `https://www.jobbank.gc.ca/jobsearch/jobposting/<jobId>`.
