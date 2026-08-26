# CV Templates and Tailoring Guide

<!-- SETUP: Profile statements and section ordering are personalized by running /setup -->

## Template: LaTeX moderncv (Classic Style)

All CVs use the moderncv LaTeX package with the "classic" style and "blue" color scheme.

**Output file:** `cv/main_<company>.tex`
**Compile with:** **lualatex** on MiKTeX/TeX Live. pdflatex often fails on modern MiKTeX installs with `fontawesome5` font-expansion errors; lualatex handles the same sources cleanly.
**Master reference:** `cv/main_master.tex` (comprehensive CV with all competencies, experience, and achievements - use as source when building targeted CVs)

### Compile command

```bash
cd cv && lualatex -interaction=nonstopmode main_<company>.tex
```

Expected output: `Output written on main_<company>.pdf (1 page, ...)`. Any page count other than 1 is a failure that must be fixed before presenting to the user.

## Document Structure

```latex
% Tailored CVs (1-page target): use 9pt + scale=0.85, tight geometry margins, enumitem
% Master CV (no page limit):    use 11pt + scale=0.77
\documentclass[9pt,a4paper,sans]{moderncv}
\moderncvstyle{classic}
\moderncvcolor{blue}
% No \renewcommand* color overrides needed — classic style renders names and
% section headings in the correct colors natively on lualatex+MiKTeX.

\usepackage[utf8]{inputenc}
\usepackage{hyperref}
\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    filecolor=magenta,
    urlcolor=blue,
    pdftitle={[YOUR_NAME] - CV},
    pdfpagemode=FullScreen,
}
\usepackage[scale=0.85, top=0.9cm, bottom=0.9cm]{geometry}
\usepackage{import}
\usepackage{needspace}
\usepackage{enumitem}
\setlist{noitemsep, topsep=1pt, parsep=0pt, partopsep=0pt, leftmargin=*}
% enumitem's tight defaults are what make the 1-page target achievable at 9pt —
% do not remove \setlist or reintroduce manual \vspace between \item entries.

% Personal data
\name{[FIRST_NAME]}{[LAST_NAME]}
\address{[CITY], [COUNTRY]}{}{}
\phone[mobile]{[YOUR_PHONE]}
\email{[YOUR_EMAIL]}
\extrainfo{\href{[YOUR_LINKEDIN_URL]}{LinkedIn}, \href{[YOUR_GITHUB_URL]}{GitHub}}
\photo[56pt][0.4pt]{[YOUR_NAME]_photo.jpg}
% Photo: a neutral-background professional headshot is standard on Danish CVs.
% The file must be in the same directory as the .tex file.

\begin{document}
\makecvtitle
\vspace{-8pt}

% 1. Profile statement (2-3 sentences, tailored per role — trimmed vs. the old
%    2-page 5-7 line version; see Profile Statement section below)
% 2. "Snapshot" two-column band: Core Competencies (left, ~55% width) |
%    Certifications + Languages + Honors & Awards stacked (right, ~40% width)
%    — see "The Snapshot Band" below for why this is the ATS-safe place to
%    use columns and everything else stays single-column
% 3. Professional Experience section (single column)
% 4. Education section (single column)
% 5. Selected Projects (if applicable, single column)
% 6. References (single line: "Available upon request.")
% 7. Closing line: \textit{Thank you for taking the time to consider my application.}

\end{document}
```

### The Snapshot Band (two-column — the one exception to single-column)

Fitting a 2-page CV onto 1 page needs real space, not just smaller margins — the fix is a
compact two-column band (`\section{Snapshot}` with two `minipage[t]`s side by side, ~0.54 and
~0.42 `\linewidth`, separated by `\hfill`) that folds Core Competencies, Certifications,
Languages, and Honors \& Awards into the vertical space three stacked one-line sections used
to take.

**Why only this band, and not the whole CV:** two-column layouts are the single most common
cause of a CV getting mangled by ATS parsers — text is extracted roughly line-by-line across
columns, so multi-sentence content in adjacent columns can interleave into garbage before a
human ever reads it. The Snapshot band is safe because every line inside it is short and
self-contained (a skill name, a cert title, a language list) — there's no sentence for a
misordered read to break. **Professional Experience, Education, and Selected Projects must
stay single-column** — these have multi-line, date-ordered, narrative content where column
interleaving would actually corrupt the reading order and is the section a human or ATS most
needs to parse correctly.

Do not extend the two-column pattern to Experience/Education/Projects even under space
pressure — cut content instead (see "Relevance-weighted cutting" below).

### Spacing inside itemize lists (important)

**Do not place `\vspace{...}` between `\item` entries in an `itemize` list.** Even though the source looks symmetric, this pattern occasionally produces a noticeably oversized gap before a single item: the inter-item `\vspace` creates a paragraph break that interacts unpredictably with the list's internal `\itemsep`, so LaTeX renders one of the gaps wider than the rest. Remove the inter-item `\vspace` and let `itemize` use its native uniform spacing — the preamble's `\setlist{noitemsep, ...}` (from `enumitem`) already makes that native spacing tight, which is what makes the 1-page target achievable.

```latex
% WRONG - intermittently produces an oversized gap before one bullet
\begin{itemize}
\item \textbf{Foo}: ...
\vspace{1pt}
\item \textbf{Bar}: ...
\vspace{1pt}
\item \textbf{Baz}: ...
\end{itemize}

% RIGHT - uniform spacing using the list's native itemsep (tight, via enumitem)
\begin{itemize}
\item \textbf{Foo}: ...
\item \textbf{Bar}: ...
\item \textbf{Baz}: ...
\end{itemize}
```

Two related patterns are fine and should be kept:
- `\vspace{1pt}` immediately after `\section{...}` (between section heading and first item) - this is between the heading and the list, not between list items.
- `\vspace{-2pt}` between top-level `\cventry` blocks in Professional Experience or Education — pulls the classic style's default inter-entry spacing in slightly tighter; adding positive `\vspace` will push tailored CVs over the 1-page limit.

## Section-by-Section Tailoring

### Personal Information (Danish Norms)
Danish CVs include less personal information than US/some international CVs:
- **Include**: full name, city + country (e.g., "Aarhus, Denmark" - not a full street address), phone, professional email, LinkedIn/portfolio links.
- **Leave out**: full street address, date of birth, nationality, marital status, whether you have children, hobbies (unless directly relevant to the role, e.g. a hobby that demonstrates a skill or value the posting calls for).
- A full street address is considered excessive personal information for Danish hiring and can be left off entirely - city/country is sufficient for location context.

### Profile Statement / Elevator Pitch (Best Practice)
This is the most important section to customize. It appears right after `\makecvtitle`.

Write a 2-3 line "elevator pitch": a concise, compelling introduction explaining why you're qualified for *this specific role*. Focus on what the employer gains from hiring you. (The 1-page budget only allows 2-3 rendered lines — the fuller 5-7 line templates below are the source material to condense from, not what goes on the page verbatim. Cut sentences that restate what Snapshot/Experience will already show, keep the one line that's most specific to *this* posting.)

**Create 2-3 profile statement templates for your main role types:**

<!-- SETUP: These are populated based on your background -->
**For [YOUR_PRIMARY_ROLE_TYPE] roles:**
> [YOUR_PROFILE_STATEMENT_TEMPLATE_1]

**For [YOUR_SECONDARY_ROLE_TYPE] roles:**
> [YOUR_PROFILE_STATEMENT_TEMPLATE_2]

<!-- Run /setup to populate additional role-specific profile statement templates from your background. -->

### Core Competencies / Skills Section (Best Practice)
Reorder and emphasize based on the role. Use bold category labels.

List **5-7 key competencies** in bullet format, tailored to the specific job. For each competency, briefly explain how it adds value to the position.

Group logically rather than as a flat list: separate **Technical/Professional Skills** (tools, languages, platforms named in the posting) from **Collaborative/Team Methods** (e.g. "Agile/Scrum", "Cross-functional Teamwork", "Stakeholder Management") when the posting emphasizes teamwork - this maps directly onto what Danish employers screen for (see Critical Rule 8 in `03-writing-style.md`).

### Languages Section
Use standard proficiency terms: **Beginner, Intermediate, Advanced, Fluent, Native Speaker.** Avoid Danish-course module numbering ("Module 3") or vague terms ("elementary", "basic") - Danish employers don't reliably map course-module levels, and "Beginner"/"Intermediate" read as more concrete. Listing an in-progress Danish course (even at Beginner level) signals integration commitment and is worth including.

### Education
- Always include your highest degrees
- For senior roles, keep education brief (dates and titles only)
- Include thesis topics when relevant to the target role

### Professional Experience
- Rewrite bullet points to emphasize aspects most relevant to the target role
- Use 4-6 bullets for most recent role, 3-4 for previous, 2-3 for older
- **Emphasize measurable results** where possible: "Reduced processing time by X%", "Model adopted by the team"

### Handling Employment Gaps (Best Practice)
Danish hiring culture has a notably higher tolerance for non-linear career paths (parental leave, sabbaticals, further study) than e.g. US hiring - a gap is not inherently a red flag, but an unexplained one looks careless. If there is a gap:
- State it directly with dates and a short label, don't try to disguise it with fudged dates: `2022 -- 2023: Personal Sabbatical`
- One line on what the time was used for, framed as deliberate: "Took a planned break to focus on [language study / a specific project / etc.]"
- If unpaid work, volunteering, or self-directed projects happened during the gap and are relevant to the target role, list them as a real entry (with dates and a 1-2 line description) - don't omit them as "not real work".

### Publications
- Include Google Scholar link if applicable
- Select 3-4 most relevant publications (not always all of them)
- For non-academic roles, keep brief

### Honors and Awards
- Keep format brief, one line each

### References
- List 2-4 references with name, title, company, and contact
- End with: "More references are available upon request."
- **Do not attach reference letters** - employers typically contact references directly

## Compile-and-Inspect Loop (MANDATORY)

After writing the CV and before presenting to the user, always compile and visually inspect the PDF. Iterate until the layout is clean. Workflow:

1. Run `lualatex -interaction=nonstopmode main_<company>.tex`
2. Check the output page count: must be exactly 1
3. Read the PDF via the Read tool and visually inspect the page
4. Check for **orphaned entries**: a `\cventry` title line must never sit alone at the bottom with its bullets pushed past the page edge; also check the Snapshot band didn't force an overfull-hbox line wrap that clips text (check the compile log for "Overfull \hbox" warnings above ~15pt, which usually means a Snapshot column line is too long)

### Fixing common page-break problems

**Problem: entry title cut off, bullets pushed past the page edge**
Add `\needspace{4\baselineskip}` immediately before the problematic `\cventry` (4 is enough at 9pt/scale=0.85 — larger values consume too much space and push other content off the 1-page limit):
```latex
\needspace{4\baselineskip}
\item{\cventry{YEAR--YEAR}{Role Title}{Organization}{Location}{}{...}}
```
Include `\usepackage{needspace}` in the preamble. Only add it for the specific entry that actually orphans — do not add it to every entry as a precaution.

**Problem: content overflows to a second page**
The standard tailored CV settings (9pt, scale=0.85, `enumitem` tight spacing, Snapshot band) leave very little layout slack — if it still overflows, cut content first. See "Relevance-weighted cutting" below for the rule. Only as a last resort for a near-miss overflow (a couple of lines), tighten `top=`/`bottom=` in the geometry package by another ~0.1cm — do not go below `top=0.6cm` or the header starts crowding the page edge.

**Problem: content finishes with noticeable empty space at the bottom (feels thin)**
Restore the highest-relevance item that was previously cut — a CV that leaves a visible empty band looks incomplete.

## Page Budget - Hard 1-Page Limit

The CV **must** fit on exactly 1 page when compiled. Use these content limits as a guide:

| Section | Max budget |
|---------|-----------|
| Profile statement | 2-3 lines |
| Snapshot: Core Competencies | 5 items, one line each |
| Snapshot: Certifications / Languages / Awards | 1 line each |
| Most recent role | 3-4 bullets |
| Previous role | 2 bullets |
| Older roles | 1-2 bullets |
| Education | 2 entries (older entry: title line only, no thesis detail) |
| Selected Projects | 3 entries, 1-2 lines each |
| Awards | folded into Snapshot, not a separate section |
| References | "Available upon request." (single line) |

**If in doubt, cut rather than squeeze.** The 9pt/scale=0.85/enumitem settings are already calibrated for 1 page — there is no further layout slack to exploit. Any remaining overflow must be addressed by cutting content, not adjusting spacing or geometry further.

## Relevance-weighted cutting (the right way to shrink a CV)

**Cut by signal, not by section.** Static priority lists ("remove oldest education first, then shorten the earliest role...") are wrong when a relevant "lower-priority" item is competing with an irrelevant "higher-priority" item. An older-role bullet that speaks directly to the posting is worth more than a recent-role bullet that does not.

For every candidate line, score three things:

1. **Relevance to THIS posting** — does the line hit a named tool, keyword, or stated responsibility in the job ad?
2. **Uniqueness** — is it the only place this claim appears, or is it duplicated elsewhere in the CV?
3. **Narrative load** — does the cover letter depend on it? If cutting the line would force you to rewrite a cover-letter paragraph, it is load-bearing.

Cut the lowest-total-score line first, regardless of which section it sits in.

### Practical order of cuts (easiest → last resort)

1. **Redundancy.** If an achievement appears in both Core Competencies AND a role bullet, the Core Competencies version is usually the cleaner cut (the experience bullet is more concrete evidence).
2. **Profile-statement fluff.** A sentence that just restates what Publications or Skills will show. ("Peer-reviewed publications on X..." is already a Publications entry — profile can claim it once and stop.)
3. **Low-relevance experience bullets.** A bullet about work that does not touch posting keywords, wherever it sits. This cuts across sections before touching the structural list.
4. **Low-relevance supporting content.** An older-role bullet that does not speak to the target role. A certification that does not touch the posting's stack. A language entry that can be condensed to one line.
5. **Low-relevance publications.** Keep 1-2 publications that best match the posting. Cut the rest before touching experience bullets.
6. **Last-resort structural cuts.** Oldest education entry, tightening an older role to 2 bullets, collapsing Certifications into a single line. These only happen if the relevance-weighted cuts above have already been exhausted.

### Pitfalls to avoid

- Do not mechanically cut from the bottom of a static section list without checking relevance. "Cut the oldest role first" is wrong if that role is literally about the skill the posting asks for.
- Do not cut the one concrete example the cover letter leans on. Relevance is measured against the cover letter you wrote, not just the job posting — interviewers will have read both.
- Do not cut to fit if the fit is a near-miss (a couple of lines over). Prefer the geometry micro-tightening described in "Fixing common page-break problems" for near-misses; reserve content cuts for genuine overflow (a paragraph or more spilling to a second page).

## Recommended Section Order

The section order varies by role type:

**For technical / data science / ML roles:**
1. Profile statement / elevator pitch
2. Snapshot (Core Competencies | Certifications, Languages, Awards)
3. Professional Experience (reverse chronological)
4. Education (reverse chronological)
5. Selected Projects
6. References

**For domain-specific / specialist roles:**
1. Profile statement / elevator pitch
2. Snapshot (Core Competencies | Certifications, Languages, Awards)
3. Education (reverse chronological) - credentials are a key qualifier
4. Professional Experience (reverse chronological)
5. Selected Projects
6. References

**Danish-market note on Education vs. Experience ordering:** Danish convention places Education before Experience for candidates with under ~1 year of professional experience (the degree is effectively their most recent "experience"). [YOUR_EXPERIENCE_SUMMARY] - default to Experience-first (as above) given sufficient combined professional history, but switch to Education-first for postings that explicitly prioritize academic credentials (e.g. roles requiring a specific MSc specialization) or for graduate/trainee programmes.
