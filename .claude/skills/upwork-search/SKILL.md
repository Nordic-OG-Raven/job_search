---
name: upwork-search
version: 1.0.0
description: >
  Search Upwork for freelance gigs matching the candidate's data-engineering / BI / AI profile, via
  the official Upwork MCP connector. Fit-rates each gig (deliverability, client quality, rate,
  competition, Connects cost) before presenting. Trigger phrases: upwork, upwork gigs, freelance
  gig, freelance work, contract work, any upwork jobs, freelance data engineering, freelance BI,
  freelance python, gigs for me, find freelance work, upwork search.
context: fork
allowed-tools: mcp__claude_ai_Upwork__upwork__find_jobs, mcp__claude_ai_Upwork__upwork__find_saved_jobs, mcp__claude_ai_Upwork__upwork__list_freelancer_proposals, mcp__claude_ai_Upwork__upwork__get_profile, mcp__claude_ai_Upwork__upwork__list_accounts, mcp__claude_ai_Upwork__upwork__save_job, Read
disallowed-tools: WebSearch WebFetch Agent
---

# Upwork Freelance Search

Discovery half of the Upwork workflow (the employment-portal analogue is `job-scraper`).
This skill only FINDS and fit-rates gigs. Writing/submitting a proposal is the separate
`/upwork-apply` command.

## If a tool call fails
Stop and report the error verbatim. Do NOT fall back to WebSearch/WebFetch or guess listings.
If the connector is missing, tell the user to restart the session and check `/mcp` shows Upwork.

## Before presenting results: the freelance fit filter
Read and apply `.claude/skills/upwork-search/freelance-fit-filter.md`. It is a hard gate:
**no fit label on any gig without a `find_jobs action=get` call on that gig in this run.**
Use `.claude/skills/upwork-search/freelance-profile.md` for what the candidate can deliver and his rate floor.

## Account
Every call needs `org_uid`. Get it once from `list_accounts` (the candidate = freelancer account).

## Workflow

### 1. Search
- **"find me gigs / what should I apply to"** → `find_jobs action=smart_search` (mode=best_match,
  Upwork's personalized feed). Always tell the user `mode=most_recent` is also available and
  switch to it when they ask for newest/just-posted.
- **User names a role** ("React gigs", "Power BI work") → `find_jobs action=search` with the
  `title` filter (not `query`) to cut noise; add `job_type`, `experience_level`, `rate_min`,
  `verified_payment_only`, `proposals_max` etc. as the user's intent implies.
- Date windows only work on `smart_search mode=most_recent` (`days_posted` or `from_date`/
  `to_date`); `action=search` has no date filter — never claim it was time-narrowed.

### 2. Get (the gate)
`find_jobs action=get` on every gig that will be rated. Surface `preferred_qualifications`,
`client_record` (spend / hire rate / feedback / verification), `connects_cost`, `applied`,
and `activityStat.jobActivity` (already-hired = weaker bet).

### 3. Present
Group by fit (Strong / Worth a look / Weak or risky / Not yet checked), per the fit-filter
output rules. Lead with a one-line banner if the Connects balance is 0 (check
`get_profile action=connects_balance`), since nothing can be applied to until that is topped up.
Each gig shows the ready-to-use `url`. Offer to save interesting gigs (`save_job action=save`)
or to draft a proposal with `/upwork-apply`.

## Notes
- Connects: applying costs Connects. State `connects_cost` for anything suggested; respect the
  0-balance reality.
- Proposal visibility: Basic accounts see a `proposals_tier` band, not an exact count (Plus only).
- Never recommend applying to a gig whose `applied` is already true.
- Language: English default; German fine; flag gigs needing other languages.
