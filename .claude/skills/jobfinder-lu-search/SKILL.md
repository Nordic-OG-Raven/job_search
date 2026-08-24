---
name: jobfinder-lu-search
version: 1.0.0
description: >
  Make sure to use this skill whenever the user mentions anything related to job
  listings in Luxembourg, job search in Luxembourg, finding work in Luxembourg, or
  vacancies on Jobfinder.lu — even if they don't explicitly mention jobfinder.lu.
  Also invoke this skill for questions about job categories, contract types, sectors,
  or experience levels in a Luxembourg job-search context. Trigger phrases include:
  luxembourg jobs, jobs in luxembourg, find job luxembourg, job search luxembourg,
  luxembourg job listings, jobfinder.lu, jobfinder lu, emploi luxembourg, travail
  luxembourg, offres d'emploi luxembourg, job opslag luxembourg, jobs luxemburg,
  arbeit luxemburg, stellenangebote luxemburg, IT job luxembourg, finance job
  luxembourg, banking job luxembourg, work in luxembourg, employment luxembourg,
  luxembourg vacancies, CDI luxembourg, CDD luxembourg, freelance luxembourg,
  job esch-sur-alzette, job luxembourg city, job kirchberg, job belval,
  cross-border job luxembourg, frontalier job.
context: fork
allowed-tools: Bash(scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts *), Read(CLAUDE.md), Read(.claude/skills/job-application-assistant/08-search-fit-filter.md)
disallowed-tools: WebSearch WebFetch Agent
---

# Jobfinder.lu Search Skill

## If the CLI command fails

If the `bun run` command above returns a non-zero exit code, an `{"error": ...}` JSON
payload, or gets denied by a permission prompt: **stop and report the exact error to
the user verbatim**. Do not substitute results from WebSearch, WebFetch, the Indeed
MCP tools, or any other source — a silent fallback mixes data sources and misleads
the user about where results came from.

Access live Luxembourg job listings from the Jobfinder.lu public API (`api.jobfinder.lu`),
the documented FastAPI backend behind the jobfinder.lu job board. No authentication needed.

## Before presenting results: candidate fit filter

Read `CLAUDE.md` and `.claude/skills/job-application-assistant/08-search-fit-filter.md`
first, and apply the experience-level and language filters described there. Raw API
results include postings well outside the candidate's seniority level and
French/Luxembourgish-only postings — these must not be presented as good/strong fits.

## When to use this skill

Invoke this skill when the user wants to:

- Search for job listings in Luxembourg (by keyword, category, contract type, experience level, or education level)
- Browse available jobs in a specific sector (IT, Banking & Finance, Engineering, Healthcare, etc.)
- Filter jobs by contract type (Permanent/CDI, Fixed term/CDD, Freelance, Student job) or working time (full-time, part-time)
- Filter jobs by required experience or education level
- Look up the full details of a specific job posting including description, hours per week, and how to apply
- Discover the filter ID taxonomy (categories, contract types, experience/education levels) for precise filtering

## Commands

### Search job listings

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` — free-text search, e.g. `python`, `accountant`, `nurse`
- `--filter <id>` — filter ID from `filters` (repeatable; combine category + contract type + experience etc.)
- `--sort <date|relevance|initial_online>` — default `relevance`
- `--status <draft|pending|online|archived>` — default `online`
- `--since <YYYY-MM-DD>` — only offers first online on/after this date
- `--limit <n>` — default 10, max 50
- `--format json|table|plain`

### Full job detail

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts detail <id> [--format json|plain]
```

`id` is the offer ID returned as `id` in `search` results. Returns title, full HTML description, hours/week, contract/category/experience/education tags, how to apply, and company address.

### Filter taxonomy

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts filters [--group <name>] [--format json|table|plain]
```

Lists filter IDs and English labels across 5 groups: **Contract**, **Working time**, **Categories** (sector), **Experience**, **Educational level**. Use `--group categories` etc. to narrow.

---

## Filter groups

| Group | Code | Examples |
|-------|------|----------|
| Contract | `contract` | Permanent (CDI), Fixed term (CDD), Freelance, Student job, Other |
| Working time | `working-time` | Full time, Part time, Other |
| Categories | (sector taxonomy, ~80 values) | IT, Banking & Finance, Engineering, Health & Care, Sales, Construction, ... |
| Experience | (no code) | No experience (<1 year), Junior (1-2 years), Experienced (2-5 years), Senior (5 years+) |
| Educational level | (no code) | No degree, General & Technical Certificate, Leaving Certificate, Advanced Certificate, Bachelor, Master, PHD |

---

## How to use effectively

**Resolve filter IDs first.** Use `filters --group <name>` to find the ID(s) for what the user wants before passing them to `search`:

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts filters --group categories --format plain
```

**Natural workflow: `search` → `detail`.**
1. Use `search` to get a list of matching jobs with their `id`.
2. Call `detail <id>` to get the full job posting with description, tags, and how to apply.

**Combine filters** — `--filter` is repeatable, so a query + category filter + contract-type filter + experience filter can all be combined in one `search` call.

**Use `--format table` for comparisons**, `--format json` for data processing, and `--format plain` for single-record detail views.

---

## Usage examples

### IT jobs, permanent contract

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts filters --group categories --format plain | grep -i " IT$"
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts filters --group contract --format plain
# then:
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts search \
  --filter 63e0110df1bf6ae542db6973 \
  --filter 63e0b58029de75e381ec85e1 \
  --sort date --format table
```

### Python jobs, most recent first

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts search --query "python" --sort date --format table
```

### Full details for a specific job posting

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts detail 69d5098ee989f572eb8047eb --format plain
```

### Senior-level jobs (5+ years experience), full-time

```bash
scripts/bun_guarded.py .claude/skills/jobfinder-lu-search/cli/src/cli.ts search \
  --filter 63e0b4960fcdc9a958f58086 \
  --filter 63e0b58029de75e381ec85e6 \
  --sort date --format table
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

- All data is from the public `api.jobfinder.lu` API — no credentials required.
- `search` results are a lightweight view (title, company, status, dates). Call `detail <id>` for description, tags, and apply info.
- Title and description are multi-language objects; the CLI prefers English, falling back through French, German, Luxembourgish, Portuguese.
- There is no location/region filter — Luxembourg is geographically small, and `detail` includes the employer's address for location context.
- The job posting page on the live site is `https://jobfinder.lu/en/jobs/<id>`.
