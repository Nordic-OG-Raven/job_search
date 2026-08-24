---
name: job-scraper
description: Scrapes job portals for new positions matching your profile by driving the dedicated portal-search skills (jobindex, jobnet, jobdanmark, jobbank, jobfinder.lu, jobs.ch, Workforce Australia, Job Bank Canada). Deduplicates across runs. Triggers on: job scrape, find jobs, search jobs, new jobs, job search, scrape jobs, /scrape
allowed-tools: Read, Write, Edit, Glob, Grep, Skill, AskUserQuestion
---

# Job Scraper

## How It Works

This skill runs targeted searches across the dedicated portal-search skills (see
`search-queries.md`) based on your profile, deduplicates against previously seen
jobs and the application tracker, and presents new matches with fit labels.

**This skill does not use WebSearch.** Every search goes through one of the
portal-search skills (`jobindex-search`, `jobnet-search`, `jobdanmark-search`,
`jobbank-search`, `jobfinder-lu-search`, `jobs-ch-search`, `workforce-au-search`,
`jobbank-ca-search`) via the **Skill tool**. Each of those skills already applies the
candidate fit filter and `detail`-call gate from `08-search-fit-filter.md`, so what
comes back is pre-filtered and fit-labeled — don't re-derive that here.

## Invocation

The user triggers this skill by saying things like:
- "Find new jobs"
- "Scrape for jobs"
- "Any new positions?"
- "/scrape"

Optional arguments:
- A focus area, e.g. "/scrape data science" or "/scrape luxembourg"
- "broad" to run all search categories across all portals, e.g. "/scrape broad"
- "catchup" to widen the date filter to 30 days for one run (after a gap of 2+ weeks) — see `search-queries.md`'s Date Filter section

---

## Execution Steps

### Step 0: Load State

1. Read `job_scraper/seen_jobs.json` (create if missing - start with `{"seen": {}}`)
2. Read `job_search_tracker.csv` to extract already-applied companies+roles
3. Read `search-queries.md` (this directory) for the portal table and query terms

### Step 1: Search via portal skills

For each query term in the selected categories, invoke the matching portal-search
skill via the **Skill tool**, using the flag names and recency/sort options from
`search-queries.md`'s portal table, with `--format json`.

- Default: run the top 3 priority categories against all Tier 1 portals — Danish
  (`jobindex-search`, `jobnet-search`, `jobdanmark-search`, `jobbank-search`),
  `jobfinder-lu-search`, and `jobs-ch-search`.
- "broad": run all categories against all portals in the table, including Tier 3
  (`workforce-au-search`, `jobbank-ca-search`).
- "catchup": same portals/categories as default, but with the 30-day date window
  from `search-queries.md`'s "One-time catch-up runs" section instead of the
  standing 14-day filter. Use after being away 2+ weeks so postings from early in
  the gap aren't missed just because they've aged past the normal window.
- A focus area (e.g. "data science", "luxembourg", "switzerland", "canada",
  "australia", "ai", "consulting", "energy"): use the matching entry in
  `search-queries.md`'s "Adapting Queries" section.
- Invoke multiple portal skills in parallel (separate Skill tool calls in the same
  turn) when a category spans more than one portal.

### Step 2: Collect & Pre-filter Results

For each result returned by a portal skill:
- Skip if the URL or company+title combo already exists in `seen_jobs.json`
- Skip if the company+role already appears in `job_search_tracker.csv`
- Classify location using the Location Filter Tiers in `search-queries.md`; skip
  results in the "Exclude" tier
- Apply the Date Filter from `search-queries.md` (last 14 days, or open deadline —
  30 days instead if this is a "catchup" run)

### Step 3: Fit Label

Portal skills already return a fit label/star rating under the
`08-search-fit-filter.md` gate — every rated posting had `detail` called on it
during that skill's run. Carry that label through unchanged. Postings a portal skill
listed under "Not yet checked" stay in a separate "Not yet checked" group here too —
don't upgrade them to a fit label without a `detail` call.

### Step 4: Deduplicate & Store

1. Add ALL results from this run (new and skipped) to `seen_jobs.json` with structure:
```json
{
  "seen": {
    "<url_or_company_title_key>": {
      "title": "...",
      "company": "...",
      "url": "...",
      "first_seen": "YYYY-MM-DD",
      "fit": "high/medium/low",
      "status": "new/skipped/evaluated"
    }
  }
}
```
2. Only present jobs NOT already in the seen list or tracker.

### Step 5: Present Results

Present new jobs in a table sorted by fit (high first):

```
## New Job Matches - YYYY-MM-DD

Found X new positions (Y high, Z medium, W low match).

| # | Fit | Title | Company | Location | Deadline | URL |
|---|-----|-------|---------|----------|----------|-----|
| 1 | High | ... | ... | ... | ... | [Link](...) |

### High-Match Highlights
For each high-match job, add 2-3 bullet points:
- Why it matches your profile
- Key requirements to check
- Any red flags
```

After presenting, ask:
> "Want me to evaluate any of these in detail? Just give me the number(s)."

If the user picks a number, invoke the **job-application-assistant** skill workflow (fit evaluation first, then CV + cover letter if approved).

### Step 6: Update Tracker (Optional)

If the user decides to apply to any job, add a row to `job_search_tracker.csv`.

---

## Important Rules

1. **Never fabricate job postings.** Only present jobs returned by a portal-search
   skill via the Skill tool in this run.
2. **No WebSearch/WebFetch fallback.** If a portal-search skill errors or is denied,
   report that to the user for that portal and continue with the others — do not
   substitute WebSearch or WebFetch results, and do not silently drop the portal
   without telling the user.
3. **Respect deduplication.** Always check seen_jobs.json AND job_search_tracker.csv
   before presenting.
4. **Focus on configured geographic area.** Skip jobs in the "Exclude" location tier
   from `search-queries.md`.
5. **Only open positions.** Skip postings with expired deadlines or marked as closed.
6. **Parallel searches.** Invoke multiple portal-search skills in parallel (separate
   Skill tool calls in the same turn) to speed up the search phase.
7. **Company career pages are out of scope for `/scrape`.** Checking a specific
   company's career page is a separate, explicit WebFetch request from the user —
   see `search-queries.md` — not part of this skill's automatic run.
