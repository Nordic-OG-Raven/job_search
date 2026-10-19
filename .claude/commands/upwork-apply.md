# /upwork-apply - Draft and submit an Upwork proposal

Freelance analogue of `/apply`. Produces a plain-text Upwork proposal (no LaTeX, no PDF),
screening-question answers, and a bid recommendation, then submits ONLY through the Upwork
connector's draft→confirm flow with explicit approval. Input: an Upwork job id / URL, or a gig
surfaced by the `upwork-search` skill.

Account: all calls need `org_uid` from `list_accounts` (the candidate = freelancer).

## Sources (ground everything in real data — never invent)
- `.claude/skills/upwork-search/freelance-profile.md` — service lines, rate floor, honest scope
  (the freelance brand, no inflated history; 0 Upwork track record — do not imply one).
- `.claude/skills/job-application-assistant/03-writing-style.md` — no em-dashes, no clichés,
  every claim backed, interview-backtrack test.
- `get_profile` (work history, aggregates), `get_profile action=list_highlights` (portfolio
  projects + certificates), `list_freelancer_proposals action=list` (prior Accepted/Hired
  proposals as tone templates).

## Step 1 — Load the job and gate
1. `find_jobs action=get` on the job. Read scope, `preferred_qualifications`, `client_record`,
   `connects_cost`, `connects_balance`, `can_apply`, `applied`, `client_feedback`,
   `screening_questions`.
2. Apply `freelance-fit-filter.md`. If it is a weak/risky fit, say so and ask before spending
   Connects.
3. **Blockers (stop and tell the user):**
   - `applied` is true → already applied; do not create again.
   - `connects_balance` < `connects_cost` (e.g. a 0 balance) → cannot submit until
     Connects are added; still offer to draft so it is ready.
4. **MANDATORY existence check before `create`:** call `list_freelancer_proposals
   action=invitations` (is there an invite for this job? → use `manage_proposals
   action=accept_invitation`, NOT create) and `action=list` (is there already a proposal?).
   Skipping this causes Upwork error VJ-JA-10.

## Step 2 — Draft (plain text)
- **Cover letter** (max 5000 chars; aim ~120–180 words): hook tied to THIS job → specific,
  real proof from your experience and portfolio → concrete approach
  → clear next step. Personalize from `client_feedback` only when a review actually names the
  contact or project; never guess a name. If the client writes in German, provide the letter in
  English and German.
- **Screening answers** — draft an answer to each `screening_questions` item.
- **Bid** — recommend amount + hourly/fixed against the rate floor in `freelance-profile.md`
  ($37/hr anchor, ~$30 weak-floor); state the rationale.
- Drop all Danish-employment rules (subsidy, a-kasse, relocation, CV-language). Not applicable.

## Step 3 — Review (optional but default-on)
Spawn a reviewer agent with the draft inline (like `/apply` step 3): check honesty (no implied
Upwork history, no inflated freelance scale, no unbacked claim), client-fit, and concision.
Revise.

## Step 4 — Prepare the submission (draft-confirm)
1. Ask the user, in these words, whether they want to **attach any files** (CV, work sample).
   If yes: `start_attachment_upload` context='proposals' → wait → pass returned file_uids.
   Never skip this question.
2. Offer to highlight portfolio projects / certificates (`get_profile action=list_highlights`
   → pass chosen `portfolio_project_ids` / `certificate_ids`).
3. `manage_proposals action=create` with `job_reference` (numeric id), `cover_letter`,
   `charged_amount`, and `answers` if there are screening questions. This returns a PREVIEW.
4. Present the preview in full: **state `connects_cost` and `connects_balance` explicitly**,
   the bid, any `unmet_preferred_qualifications`, and the boost block. Explain boosting is a
   Connects BID for a top slot, charged only if it wins a paid slot or the client engages;
   offer it only if `boost.available` and `boost.recommendation` is not 'skip', noting
   `boost.recommended_connects`. Never exceed `boost.max_boost_connects`.
5. **Submit ONLY after explicit approval:** `confirm_preview type='proposal'` with the
   `preview_id`. Never auto-submit. After submit, status is Pending (`list_freelancer_proposals
   action=list status=Pending` to verify).

## Step 5 — Record
- Save the gig: `gig_postings/<client>_<slug>.md` with YAML frontmatter (client, title,
  job_type, budget/rate, url, connects_cost, date, proposal_file).
- Save the proposal text: `proposals/<client>_<slug>.md`.
- Append a row to `job_scraper/upwork_tracker.csv`:
  `date,client,gig_title,category,rate_type,bid,connects_spent,client_spend,status,proposal_file,gig_file,notes`
  (status = proposed, or "drafted (no connects)" if not submitted).
- End the final message with the gig `url` on its own line (per the always-end-with-URL rule).
