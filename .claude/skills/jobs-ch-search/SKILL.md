---
name: jobs-ch-search
version: 1.0.0
description: >
  Make sure to use this skill whenever the user mentions anything related to job
  listings in Switzerland, job search in Switzerland, finding work in Switzerland,
  central Switzerland, Zentralschweiz, or vacancies on jobs.ch — even if they don't
  explicitly mention jobs.ch. Also invoke this skill for questions about cantons,
  employment grade (Pensum), or industries/categories in a Swiss job-search context.
  Trigger phrases include: switzerland jobs, jobs in switzerland, find job switzerland,
  job search switzerland, swiss job listings, jobs.ch, jobs ch, central switzerland
  jobs, zentralschweiz jobs, jobs luzern, jobs lucerne, jobs zug, jobs schwyz, jobs
  zürich, jobs zurich, stellenangebote schweiz, stellen schweiz, arbeit schweiz, job
  schweiz, IT job switzerland, IT job luzern, work in switzerland, employment
  switzerland, swiss vacancies, pensum, vollzeit teilzeit schweiz, kanton luzern job,
  kanton zug job.
context: fork
allowed-tools: Bash(bun run skills/jobs-ch-search/cli/src/cli.ts *), Read(CLAUDE.md), Read(.claude/skills/job-application-assistant/08-search-fit-filter.md)
---

# jobs.ch Search Skill

## Before presenting results: candidate fit filter

Read `CLAUDE.md` and `.claude/skills/job-application-assistant/08-search-fit-filter.md`
first, and apply the experience-level and language filters described there. Raw search
results include postings well outside the candidate's seniority level and
French/Italian-only postings (the candidate's French/Italian is not fluent) — these
must not be presented as good/strong fits.

Access live Swiss job listings from [jobs.ch](https://www.jobs.ch), the largest job
portal in Switzerland (JobCloud group, covers German/French/Italian Switzerland). No
authentication needed — the CLI reads the JSON embedded in jobs.ch's server-rendered
pages.

## When to use this skill

Invoke this skill when the user wants to:

- Search for job listings in Switzerland (by keyword, employment grade/Pensum)
- Search specifically in **central Switzerland (Zentralschweiz)** — Lucerne, Zug,
  Schwyz, Uri, Obwalden, Nidwalden
- Look up the full details of a specific job posting including description, location,
  employment type, industry, and category
- Browse jobs in central Switzerland (e.g. "jobs in Zug", "jobs in Luzern")

## Commands

### Search job listings

```bash
bun run skills/jobs-ch-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--term <text>` — free-text search, e.g. `python`, `data engineer`, `pflegefachperson`
- `--employment-grade-min <0-100>` / `--employment-grade-max <0-100>` — filter by % of full time (Pensum)
- `--region central-switzerland` — jobs.ch's own region filter for Zentralschweiz (Lucerne, Zug, Schwyz, Uri, Obwalden, Nidwalden) — a real server-side filter that covers all listings in the region
- `--page <n>` / `--limit <n>` — pagination; max results, default 10, max 50 (fetches extra pages automatically if needed)
- `--lang en|de` — site locale, default `en`
- `--format json|table|plain`

### Full job detail

```bash
bun run skills/jobs-ch-search/cli/src/cli.ts detail <id> [--lang en|de] [--format json|plain]
```

`id` is the UUID returned as `id` in `search` results. Returns title, full description,
company name/website, location, employment type, industry, and category breadcrumb.

---

## How to use effectively

**For central Switzerland**, always pass `--region central-switzerland`. This maps to
jobs.ch's own region filter (Zentralschweiz: Lucerne, Zug, Schwyz, Uri, Obwalden,
Nidwalden) and is applied server-side in a single request — `meta.totalHits` reflects the
full region-wide count, and results aren't restricted to listings with structured location
data. There is no finer per-canton filter on jobs.ch; `--region central-switzerland` is the
most specific geographic filter available.

**Natural workflow: `search` → `detail`.**
1. Use `search` to get matching jobs with their `id`, place, and canton.
2. Call `detail <id>` for the full posting (description, employment type, how to apply via company site).

**Language**: job descriptions are in whatever language the employer posted in — mostly
German in central Switzerland, sometimes English or French. The `--lang` flag only
changes the site UI locale and result URLs.

---

## Usage examples

### Python jobs in central Switzerland

```bash
bun run skills/jobs-ch-search/cli/src/cli.ts search \
  --term python --region central-switzerland --limit 25 --format table
```

### Full-time jobs in central Switzerland

```bash
bun run skills/jobs-ch-search/cli/src/cli.ts search \
  --region central-switzerland --employment-grade-min 100 --limit 25 --format table
```

### Full details for a specific job posting

```bash
bun run skills/jobs-ch-search/cli/src/cli.ts detail 3181cb45-0899-4c6b-80ad-73504558cc8d --format plain
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

- All data is from the public server-rendered pages of `jobs.ch` — no credentials required.
- `search` results include `place` (free-text location) and `cantons` (canton codes, when known).
- The job posting page on the live site is `https://www.jobs.ch/{en|de}/vacancies/detail/<id>/`.
