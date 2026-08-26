# Job Search Fit Filter — MANDATORY PROTOCOL

Applies to: `jobindex-search`, `jobnet-search`, `jobdanmark-search`, `jobbank-search`,
`jobfinder-lu-search`, `jobs-ch-search`, `workforce-au-search`, `jobbank-ca-search`,
and the `mcp__claude_ai_Indeed__*` tools.

This is not background reading — it is a gate. **Step 2 cannot be skipped, no matter
how many postings there are.** If presenting results for 10 postings means 10 `detail`
calls, make 10 `detail` calls. Doing fewer and writing a shorter, honestly-labeled
table is correct. Doing fewer and writing a full table anyway is not.

## Step 1 — Search

Run `search` / `search_jobs`. This output gives you ONLY: title, company, location,
posted date, URL. Nothing else. Do not write any assessment from this step alone.

Pre-filter by title against the candidate's level (see "Experience level" below) to
narrow the list before Step 2 — but do not drop ambiguous titles, send them to Step 2.

## Step 2 — Detail (the gate)

For every posting that will appear in the output with a fit label, language note,
experience note, or skills-match bullet, call `detail` / `get_job_details` for that
exact posting **in this conversation, this run**. No exceptions for "obvious" titles,
"similar" postings seen earlier, or postings seen on a different platform.

A posting that has NOT had `detail` called on it in this run may only be listed under
a separate "Not yet checked" section with title/company/URL and nothing else — no
star rating, no date claim beyond what `search` returned, no skills/language note.

## Step 3 — Write the table, sourced only from Step 2 output

Every cell in the results table must trace to text you can point to in this run's
`detail`/`get_job_details` output for that specific posting:

- **Posted date**: use the date from THIS posting's own `search` or `detail` result.
  Never reuse a date seen for a same/similar-titled posting on another platform or in
  an earlier run — different platforms have independent listings with independent
  dates, even for "the same" job.
- **Skills match / "no strict minimum" / "targets recent grads" / experience
  requirement**: must paraphrase or quote something actually present in the `detail`
  output. If the description doesn't mention it, don't claim it either way.
- **Star rating / "Strong fit" / "Borderline"**: a conclusion drawn from the above,
  not an independent claim — don't assign one to a posting without `detail` output.

## Experience level

<!-- SETUP: populate your actual experience level and career goal summary -->
[YOUR_EXPERIENCE_LEVEL_SUMMARY — e.g. degree status, professional tenure by role type,
and reference to your career goal in `04-job-evaluation.md`]

- **Baseline (all portals/sources)**: exclude or clearly flag postings whose title
  signals a seniority level above entry/junior — "Senior", "Expert", "Lead",
  "Principal", "Head of", "Director", "Chef de...", "Manager",
  "Économiste/Economist" — unless explicitly entry-level/graduate/assistant. If a
  title is ambiguous, Step 2's `detail` call resolves it (check the stated
  years-of-experience requirement).
- **Student-only roles — hard exclude**: roles that explicitly require current
  student enrollment: "Student Worker", "Student Assistant", "Studentermedhjælper",
  "Studentenjob", "Werkstudent", "Elev". These are restricted to enrolled students
  and the candidate holds an MSc. Internships ("Praktikant", "Intern", "Praktikum",
  "Stagiaire") are fine — include them normally.
- **Jobfinder.lu (`jobfinder-lu-search`) — additional pre-filter**: the `experience`
  filter group has explicit IDs that can narrow results at the API level before the
  title check. Default to **"No experience (<1 year)"**
  (`63e0b4960fcdc9a958f58083`) and **"Junior (1-2 years)"**
  (`63e0b4960fcdc9a958f58084`). Only include "Experienced (2-5 years)"
  (`63e0b4960fcdc9a958f58085`) or "Senior (5 years+)" (`63e0b4960fcdc9a958f58086`) if
  the user explicitly asks for those levels.

## Language

<!-- SETUP: populate your actual languages and fluency levels -->
Candidate languages: [YOUR_LANGUAGES_WITH_FLUENCY_LEVELS].

If a posting's description (from Step 2's `detail` output) requires or is written in
a language the candidate doesn't speak fluently (French, Luxembourgish, Portuguese,
Italian), do not present it as a strong fit. Either exclude it, or include it with an
explicit note, e.g. "Requires fluent French — candidate's French is elementary,
likely a barrier."

## Before sending the message — self-check

- [ ] Every posting with a star rating / fit label had `detail` called on it in this run.
- [ ] Every posted date shown came from this run's tool output for that exact posting
      on that exact platform — not memory, not another platform's listing.
- [ ] No "Senior"/"Expert"/etc. title is presented as a fit without an explicit note
      explaining why it's still relevant.
- [ ] Every French/Luxembourgish-required posting is flagged.
- [ ] Postings without a `detail` call are in a separate "Not yet checked" list, not
      mixed into the rated table.
