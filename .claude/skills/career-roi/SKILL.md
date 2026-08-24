---
name: career-roi
description: Ranks the highest-ROI ways to spend spare time toward landing a role — portfolio projects, certifications, refresher courses, LinkedIn posts, YouTube content, formal education — based on real coverage gaps against the live job market. Triggers on: /career-roi, career-roi, how should I spend my time, highest ROI, what should I do to stand out, portfolio project ideas, should I get a certification
allowed-tools: Read, Write, Glob, Grep, WebSearch, Bash(scripts/bun_guarded.py *), Bash(sqlite3 *)
---

# Career ROI

## Overview

`/career-roi` answers "what's the single highest-value thing I could do with my time right now to land a role?" It is broader than `/upskill`: `/upskill` turns skill gaps into a *learning plan* (courses to take); this turns the same kind of gap analysis, plus visibility and credibility considerations, into a ranked list across every activity type — portfolio projects, certifications, refresher courses, LinkedIn posts, YouTube content, formal education, anything.

It reuses `/upskill`'s gap-diff methodology (Steps 3-4 of `.claude/skills/upskill/SKILL.md`) but sources requirements from `scripts/seen_jobs.db` — the live, continuously-refreshed market you're actually scanning daily — instead of the small, self-selected `job_search_tracker.csv` sample `/upskill` uses. That database is not a sample you'd have to go construct: it already reflects exactly who's currently hiring for roles matching your profile.

## Invocation

- **`/career-roi`** — full run: coverage check against the live market, then ROI-ranked activity plan
- **`/career-roi <company name>`** — same, but adds a focused pass on that specific employer's own stated requirements (career page / recent postings), for a named target company

---

## Step 1: Load Data

1. Read `.claude/skills/job-application-assistant/01-candidate-profile.md` — the candidate's current, synthesized skills and experience (this is the canonical profile; there is no separate "master CV" file to read instead).
2. Read `job_search_tracker.csv` to get the list of companies already applied to — used in Step 4 to avoid recommending effort aimed at an employer already in motion.
3. Pull a sample of recent, relevant postings from the live market:
   ```bash
   sqlite3 -separator '|' scripts/seen_jobs.db "
     SELECT portal, job_id, title, company, fit_rating, first_seen
     FROM seen_jobs
     WHERE fit_rating IN ('Strong Fit', 'Good Fit')
     ORDER BY first_seen DESC
     LIMIT 40;
   "
   ```
   40 postings is enough for a real frequency signal without re-fetching the whole cache. Weight Strong Fit above Good Fit in every downstream step — those are the roles you're most competitive for already, so their requirements matter most.
4. `seen_jobs.db` stores ratings and reasoning but not full description text (only used transiently during evaluation, not persisted). For each sampled posting, fetch the real description via the portal's own CLI, routed through the shared concurrency-capped wrapper — same pattern every portal-search skill uses:
   ```bash
   scripts/bun_guarded.py .claude/skills/<portal>-search/cli/src/cli.ts detail <job_id> --format plain
   ```
   Do this sequentially, not in a burst of parallel Bash calls — the wrapper caps concurrency at 3, but firing 40 at once in one turn still means queuing 40 processes back to back. A handful of sequential calls per turn keeps this fast without repeating the memory-pressure incident from the backlog clear.
5. If a company name was given as an argument, additionally WebFetch that company's own careers/jobs page (and WebSearch if no direct URL is obvious) for their current listed requirements — treat this as a second, higher-weight source in Step 2, since it reflects that specific employer's own language rather than an aggregate.

## Step 2: Coverage Check

Follow the same **Hard Skill Diff** (Step 3) and **LLM Synthesis** (Step 4) methodology described in `.claude/skills/upskill/SKILL.md`, applied to the postings gathered in Step 1 instead of the tracker:

- Build the skill frequency map from the fetched descriptions, weighted by fit tier (Strong Fit = 1.0, Good Fit = 0.6 — inverted from `/upskill`'s applied-fit weighting, since here a *higher* fit-worthy posting demanding a skill is stronger evidence that skill matters, not weaker).
- Run the same LLM synthesis pass for domain, soft, tooling, and credential gaps.
- Diff against the candidate profile the same way — generous matching, no false positives.
- Produce the same Priority heatmap (Critical / High / Medium / Low) `/upskill` uses, for consistency between the two reports.

Print this heatmap before continuing, same as `/upskill` does.

## Step 3: Generate Candidate Activities

This is the part `/upskill` doesn't do. For each Critical/High gap from Step 2, **and** independent of gaps, generate 1-3 concrete candidate activities spanning these types:

- **Portfolio project** — something buildable and demonstrable, ideally closing a gap *and* producing public evidence (a repo, a deployed demo, a write-up). Prefer these over pure study when a gap allows it — proof beats a claim on a CV.
- **Certification** — a recognized, verifiable credential. Only worth proposing where postings actually ask for it (check the gap source) — a certification nobody's requesting is a checkbox, not a signal.
- **Refresher / course** — closes a gap without external proof. Cheapest time cost, weakest signal; good for gaps that are prerequisites for something else rather than end goals.
- **LinkedIn post(s)** — visibility/network-effect activity, not gap-driven. Worth proposing when the candidate has real, demonstrable strength that isn't currently visible externally (e.g. a finished project, a strong opinion backed by experience). Suggest concrete post angles, not just "post more."
- **YouTube / content** — same visibility logic as LinkedIn but higher time cost and higher signal ceiling (a well-made technical video is harder to fake than a post). Only propose when there's a genuinely strong, specific angle — not as a default option.
- **Formal education** (part-time program, evening course, degree-adjacent) — highest time cost. Only propose when a Critical gap is structural (e.g. a domain the candidate has zero foothold in) and lighter options wouldn't credibly close it.

Use WebSearch to ground certification and course suggestions in real, current options (same rule as `/upskill`: never fabricate a resource, name, or URL).

## Step 4: Score and Rank

For each candidate activity, judge (don't compute a fake precise number — reason qualitatively against these criteria, same spirit as `/upskill`'s priority tiers):

- **Impact** — how directly this closes a Critical/High gap, or how much untapped strength it surfaces
- **Signal strength** — how credible/visible this is to an employer skimming a CV or LinkedIn in 30 seconds (a deployed project > a certificate > "I read about it")
- **Time cost** — realistic hours to a genuinely presentable result, not just "started"

Combine into a single **ROI tier**: Critical / High / Medium / Low. A short time cost with strong signal beats a long time cost with the same signal, even if raw impact is equal — the point of this whole exercise is spare time, so cheap wins that compound matter more here than they would in a normal priority list.

If a candidate activity targets a specific company already in `job_search_tracker.csv` (Step 1.2), lower its priority one tier and note why — that company is already in motion; effort is better spent widening reach than doubling down where you're already known.

## Step 5: Output

Present a single ranked list (Critical first), each entry with: activity, type, target gap or rationale, estimated time, and 1-2 concrete next actions to actually start it (not just "learn Kubernetes" — the specific first thing to do this week).

Save the report to `career-roi/report-YYYY-MM-DD.md` using the Write tool. If a previous report exists in `career-roi/`, add a short "Since last report" section noting what moved (gap closed, activity done) — same pattern as `/upskill`'s diff section.

After saving, print:
> "Report saved to `career-roi/<filename>.md`."

---

## Important Rules

1. **Never fabricate resources, certifications, or companies.** Only cite what WebSearch/WebFetch actually returned.
2. **Don't duplicate `/upskill`'s job.** If the honest answer to a gap is "take this course," say so and stop there — don't invent a portfolio project just to fill out the activity-type spread.
3. **Respect the concurrency cap.** All portal detail-fetches go through `scripts/bun_guarded.py`, sequentially within a turn, never as a burst of parallel Bash calls.
4. **Print the heatmap and the ranked list to the terminal**, not just the saved file — the user should see the reasoning, not just the output.
5. **Always save the report**, even if the conversation continues past it.
