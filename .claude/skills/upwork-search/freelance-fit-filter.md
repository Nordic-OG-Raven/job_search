# Upwork Freelance Fit Filter — MANDATORY PROTOCOL

Applies to the `upwork-search` skill and any use of the `mcp__claude_ai_Upwork__upwork__*`
job tools. This is the freelance analogue of `job-application-assistant/08-search-fit-filter.md`.
Employment-seniority/location/relocation logic does NOT apply here; freelance economics do.

## The gate (same discipline as the employment filter)

`find_jobs action=search` / `smart_search` returns summaries. **Do not attach a fit label to
any gig without calling `find_jobs action=get` on that exact job in this run.** A gig with no
`get` call may only be listed under a separate "Not yet checked" heading with title + URL and
nothing else — no fit rating, no client-quality claim, no rate judgement.

Every claim in the output table must trace to this run's tool output for that specific job.

## Step 1 — Search
`smart_search` (mode=best_match) when the candidate wants work for himself; `search` with `title` (not
`query`) when he names a specific kind of work, to cut noise. Pre-filter by title/skill against
his service lines before spending `get` calls.

## Step 2 — Get (the gate)
Call `find_jobs action=get` for every gig that will carry a fit label. From the `get` response,
judge against the axes below.

## Fit axes (freelance)

1. **Deliverability** — does the scope map to his service lines in `freelance-profile.md`
   (data engineering / BI / LLM-RAG)? If it needs a tool he is only Familiar-tier in, cap the
   fit and say so; never bluff competence.
2. **Economics** — `job_type` fixed vs hourly; compare against the floor in
   `freelance-profile.md` (~$30/hr weak, $37–50 target). Flag underpriced scope and any
   "free test task" ask.
3. **Client quality** — from `get`'s `client_record`: `hire_rate_percent`, `total_spent`,
   feedback score/count, `verification_status`. Flag unverified-payment or zero-spend/zero-hire
   clients as higher-risk. Note: `client_record.rating` is the score freelancers gave the
   client (`client_rating_basis` says so) — a low number is a warning about the client, not
   about their success.
4. **Competition & liveness** — `proposals_tier` or exact `proposal_count` (Plus only), and
   `activityStat.jobActivity` (invitesSent / totalHired / totalOffered). A job that has already
   hired or made offers is a weaker bet. Many proposals + low budget = skip.
5. **Connects economics** — `connects_cost` is what applying spends. **the Connects balance may be 0** (check `get_profile action=connects_balance` live). If balance < cost,
   `can_apply` is false: present the gig as a find but state plainly he cannot apply until he
   adds Connects. Never recommend a low-value gig that burns scarce Connects.
6. **Already applied** — if `applied` is true, never recommend applying again; say so.
7. **Red flags** — scope/budget mismatch, vague one-liner posts, off-platform payment or
   contact requests (also an Upwork policy violation), scope-creep bait.

## Language
English gigs default-OK. German fine (he is fluent). Skip or flag gigs requiring a language he
does not have professionally (French beyond elementary, etc.).

## Output
Group by fit (Strong / Worth a look / Weak or risky / Not yet checked). For each rated gig show:
title, client-quality one-liner (spend/hire-rate/verified), budget or rate, proposals/competition,
connects_cost, and the ready-to-use `url`. If balance is 0, put a one-line banner at the top.

## Self-check before sending
- [ ] Every rated gig had a `get` call this run.
- [ ] Connects cost shown for anything suggested as applyable; 0-balance banner present if so.
- [ ] No gig with `applied=true` recommended for application.
- [ ] Underpriced / unverified-client / already-hired gigs flagged, not buried.
- [ ] No non-deliverable gig rated Strong by bluffing a Familiar-tier tool.
