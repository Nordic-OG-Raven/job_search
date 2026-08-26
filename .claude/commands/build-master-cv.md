# /build-master-cv - Mine Historical CVs into the Candidate Profile

You are running `/build-master-cv` for the AI Job Search framework. Your goal is to
mine `documents/all_cvs/` — an archive of the user's historical CVs — for content
(work history, projects, skills, achievements, and profile-statement framing) that
should be added to the candidate profile skill files under
`.claude/skills/job-application-assistant/`.

This command processes files in small groups and is designed to be **run repeatedly**
until everything is processed. It runs autonomously — do not ask for per-group
confirmation. The user reviews everything afterward via the changelog.

If `$ARGUMENTS` contains `--limit <N>`, use that as the max number of files to process
this run. Otherwise default to 20.

---

## Step 0: Discover and scope source files

1. Use Glob to find `documents/all_cvs/**/*.pdf` and `documents/all_cvs/**/*.docx`,
   excluding any path containing `/_processed/`. Also discard any file whose name
   starts with `~$` — these are Word lock/temp files, not real documents.
2. Group results by their immediate year-folder (e.g. `2023-24`, `2025-26`) and sort
   folders in ascending name order. This is the rough chronological order to process
   in.
3. **Dedupe exact format pairs**: within each folder, if both `<name>.pdf` and
   `<name>.docx` exist (same filename, different extension), drop the `.docx` — keep
   only the `.pdf`. This is a pure format-redundancy removal (same document, two
   formats), not a content decision.
4. **No filename-based type filtering.** CV vs. cover letter vs. other document is
   often not reliable from the filename alone (e.g. `Backup of Company X
   2024.docx` could be a CV; `Company Y Manager CL.pdf` could be a cover letter).
   Every remaining file is read in Step 2, which classifies it by actual content.
5. If, after step 3, there are **no files left across any folder** (i.e. everything
   has already been processed), skip groups in Step 2 entirely, but still run Step 3
   (regenerate the master CV) and proceed to **Step 4 (Final Pruning Pass)**.
6. Otherwise, take files in folder order (oldest folder first) up to `--limit`
   (default 20), and split them into groups of 5 for processing.

---

## Step 1: Load current profile state (once per run)

Read these files in parallel and hold their contents in context for the rest of this
run — do not re-read them between groups:

- `.claude/skills/job-application-assistant/01-candidate-profile.md`
- `.claude/skills/job-application-assistant/05-cv-templates.md`
- `.claude/skills/job-application-assistant/07-interview-prep.md`
- `.claude/skills/job-application-assistant/00-merge-changelog.md` (if it doesn't
  exist, create it when you write the first batch entry, with this header):

```markdown
# Master CV Merge Changelog

Running log of what `/build-master-cv` has added to the candidate profile from
`documents/all_cvs/`. Conflicts and possibly-outdated items are flagged here for
manual review — nothing in this file is applied automatically.
```

**Important — placeholder handling:** `01-candidate-profile.md` etc. may still
contain template placeholders like `[JOB_TITLE]`, `[COMPANY]`, `[YOUR_NAME]`. Treat
any section that is still all-placeholder as **empty** — anything found in a CV for
that section is purely additive, not a conflict.

---

## Step 2: Process each group of 5 files

For each file:

- **`.docx`**: convert to text first:
  ```bash
  mkdir -p /tmp/build-master-cv && textutil -convert txt -output "/tmp/build-master-cv/<safe-name>.txt" "<original path>"
  ```
  then Read the resulting `.txt`. (`textutil` is a built-in macOS tool — lossless
  text extraction, just unlocks the format.)
- **`.pdf`**: Read directly.

After reading, first classify the document: **CV**, **cover letter**, or **other**
(e.g. planning notes, transcripts). If it's not a CV, or a CV with no content beyond
what's already captured, record it in the changelog as "no new content (cover letter)"
/ "no new content (other)" / "no new content (already captured)" and move on — don't
force an extraction.

For CVs with new content, compare it against the profile state held in context and make
these updates:

### a. Factual content -> `01-candidate-profile.md`

Look for: job titles/employers/dates, education entries, projects, certifications,
technical skills, awards, publications.

- **New** (not represented in any form in the current profile) -> add it to the
  relevant section as a genuine addition. Never delete or rewrite existing entries.
- **Conflicting** (something already in the profile, but this CV states it
  differently — e.g. a different end date for the same role, a different job title
  for the same employer/period) -> do NOT pick one. Instead add an entry under
  `## Open Conflicts (Review Needed)` in the changelog (create this section on first
  use) showing both versions and their sources.
- **Matches existing content** -> do nothing.

### b. Profile statement / framing -> `05-cv-templates.md`

Look at the "Profile Statement / Elevator Pitch" section. If this CV's opening
summary/profile statement expresses something substantively different from what's
already there (a different angle, a passion or framing not yet captured) -> add it as
a new tagged variant:

```markdown
**For [ROLE_TYPE] roles:**
> [the new profile statement text]
*[Source: <filename>, <year-folder>]*
```

If it's just a reworded version of a variant that's already there, skip it — don't add
near-duplicate phrasings.

### c. Achievements -> `07-interview-prep.md`

If the CV describes a concrete achievement (a project, a quantified result, a notable
responsibility) that isn't yet covered by an existing STAR example or STAR-candidate
stub, add a stub under `## STAR Candidates (Complete Manually)` (create this section
if it doesn't exist yet, same format `/setup` uses):

```markdown
### [Achievement title]
**Source:** [filename, year-folder]
**What happened:** [one sentence]
**Why it matters:** [interview question types this could answer]
**S/T/A/R stub:**
- Situation:
- Task:
- Action:
- Result:
```

Apply all edits with `Edit` (targeted, additive edits — not full-file rewrites).

---

## Step 2.5: Log and archive the group

1. Append one entry to `00-merge-changelog.md`:

```markdown
## Batch <n> — <year-folder> — <ISO date/time>

**Files processed:**
- <filename> — <one-line summary of what was added, or "no new content">
- ...

**Added to 01-candidate-profile.md:**
- ... (or "none")

**Added to 05-cv-templates.md:**
- ... (or "none")

**Added to 07-interview-prep.md:**
- ... (or "none")

**Conflicts flagged:** (or "none")
- ...
```

2. Move **every** file in the group into `documents/all_cvs/<year-folder>/_processed/`,
   keeping the original filename. Use `mkdir -p` then `mv`. This is how re-running the
   command knows what's left to do; Step 0's Glob excludes `_processed/`. Nothing is
   deleted.

Repeat Step 2 / 2.5 for each group until you've processed `--limit` files or run out
of files.

---

## Step 3: Regenerate the master CV reference document

Once per invocation, after Step 2's groups are done for this run (regardless of
whether files remain for future runs), regenerate `cv/main_master.tex` so it stays a
single, comprehensive, up-to-date snapshot of everything in `01-candidate-profile.md`
and `05-cv-templates.md`. This is the "one reference point" document — the framework
already designates it as the "Master reference... comprehensive CV with all
competencies, experience, and achievements" that `/apply` uses as raw material for
tailored per-application CVs. **Unlike tailored CVs, there is no 2-page limit here** —
comprehensive is the goal, not concise.

Fully regenerate the file (don't hand-edit incrementally) using the LaTeX skeleton
from `05-cv-templates.md`'s "Document Structure" section:

1. **Personal data**: `\name`, `\address`, `\phone`, `\email`, `\extrainfo` (LinkedIn /
   GitHub) from `01-candidate-profile.md`'s Identity section.
2. **Profile statement**: use the first non-placeholder variant from
   `05-cv-templates.md`'s "Profile Statement / Elevator Pitch" section (if several
   exist, pick the most general/primary one — this is a representative snapshot;
   `/apply` does per-role selection for tailored CVs).
3. **Core Competencies**: 5-7 bullets with bold category labels, derived from
   `01-candidate-profile.md`'s Technical Skills section (Programming & ML, Domain
   Expertise, Software & Tools, APIs/Misc). **Respect the proficiency tiers**:
   - Build each category bullet primarily from that category's **Proficient** and
     **Working Knowledge** items — these are the headline content.
   - Do **not** list individual **Familiar / Exposure** items as headline content
     within a category bullet (e.g. don't put "Attention Mechanisms, Graph Databases,
     RLHF" alongside "RandomForest, XGBoost" with equal weight).
   - If Familiar/Exposure items are worth surfacing at all on this comprehensive
     reference document, group them into a single trailing bullet such as
     `\textbf{Additional Exposure}: ...` so they're visibly lower-weight — never
     interleave them into the Proficient/Working Knowledge bullets.
   - This mirrors the framing rules in `03-writing-style.md` rule 7: Familiar-tier
     skills should never be presented as primary qualifiers.
4. **Professional Experience**: one `\cventry` per role in
   `01-candidate-profile.md`, reverse-chronological, with all bullets — include
   every role, not just the most recent.
5. **Projects**: add a `\section{Projects}` (after Professional Experience) with one
   entry per item in `01-candidate-profile.md`'s "Portfolio Projects" section — never
   pull from "Personal Interests & Volunteering" (hobbies/volunteering are not CV
   projects). For each entry, render `\item \textbf{Name} (Stack, omit parens if
   Stack is "—"): Summary. Impact (if not "—"). Link, if any, via \href{}{}` — pulling
   only from the entry's structured fields, not paraphrasing beyond them. (Not
   present in the original template — this section is added because
   `/build-master-cv` surfaces project content the original template didn't account
   for.)
6. **Education**: one `\cventry` per row in the Education table, reverse-chronological.
7. **Languages**, **Publications**, **Honors and Awards**, **References**: from the
   corresponding `01-candidate-profile.md` sections.

**Omit any section that is still entirely placeholder** (e.g. Publications, if none
exist yet) rather than rendering bracketed placeholder text into the PDF.

After writing the file, compile it:
```bash
cd cv && lualatex -interaction=nonstopmode main_master.tex
```
Check for LaTeX errors and note the resulting page count for the Step 5 summary —
multi-page output is expected and fine here (the 2-page rule applies only to tailored
per-application CVs in `cv/main_<company>.tex`).

---

## Step 4: Final pruning pass (only when Step 0 found nothing left)

Read `01-candidate-profile.md` and `05-cv-templates.md` in full (if not already in
context). Using the changelog's batch history (which year-folder each item's source
came from), identify entries that:

- Only ever appeared in `2023-24` (or earlier) sources, AND
- Were never reinforced/repeated by any `2025-26` (or later) source

These are candidates for being outdated (e.g. an old tool, an old skill, an old
framing that's since been superseded). Append a section to `00-merge-changelog.md`:

```markdown
## Possibly Outdated — Review

These items only appeared in older (2023-24) sources and were never repeated in newer
ones. Confirm whether to keep or remove each:

- [item] — from <source filename, year-folder>
- ...
```

Do not edit `01-candidate-profile.md` or `05-cv-templates.md` in this step — flag
only, the user decides.

---

## Step 5: Summary

Report to the user:
- How many files were processed this run, grouped by year-folder
- A short summary of what was added to each of the three skill files
- The regenerated master CV: `cv/main_master.pdf` (and page count) from Step 3
- How many conflicts were flagged this run (point to the changelog)
- If files remain: how many, and that re-running `/build-master-cv` will continue with
  the next group
- If Step 4 ran: mention the "Possibly Outdated — Review" section was added and
  everything has now been processed
