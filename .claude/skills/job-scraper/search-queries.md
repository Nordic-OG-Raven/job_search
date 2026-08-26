# Search Queries for Job Scraper

<!-- Populated by /setup for [YOUR_NAME] — June 2026 -->
<!-- Updated July 2026: Luxembourg and Switzerland promoted to significantly higher focus. -->
<!-- Home base: Aarhus. Also targeting Luxembourg and Switzerland (Zürich/Zug/Luzern). North of Vejle = acceptable. East of Vejle = borderline. -->

## Search skills

Each portal below has a dedicated CLI skill under `.claude/skills/<name>/`. Invoke
these via the **Skill tool** — do not use WebSearch/WebFetch for portal searches.
Each skill applies its own candidate-fit filter and `detail`-call gate
(`08-search-fit-filter.md`) before returning results, so what comes back is already
pre-filtered and fit-labeled.

| Tier | Portal | Skill | Query flag | Recency / sort | Useful location flag |
|------|--------|-------|-----------|----------------|----------------------|
| 1 | jobindex.dk | `jobindex-search` | `--query "<term>"` | `--jobage 14 --sort date` | include city in query, e.g. `"data engineer aarhus"` |
| 1 | jobnet.dk | `jobnet-search` | `--search-string "<term>"` | `--order PublicationDate` (default) | `--region Midtjylland` |
| 1 | jobdanmark.dk | `jobdanmark-search` | `--text "<term>"` | no recency flag — rely on dedup against `seen_jobs.json` | `--municipality Aarhus` or `--region Midtjylland` |
| 1 | jobbank.dk (Akademikernes) | `jobbank-search` | `--key "<term>"` | `--since <YYYY-MM-DD>` (today − 14 days) | `--location 8` (Østjylland/Aarhus) or `--location 7` (Midtjylland) |
| 1 | jobfinder.lu | `jobfinder-lu-search` | `--query "<term>"` | `--sort date --since <YYYY-MM-DD>` (today − 14 days) | n/a (small market) |
| 1 | jobs.ch | `jobs-ch-search` | `--term "<term>"` | no recency flag — rely on dedup | `--region central-switzerland` for Zug/Luzern; add `zürich` to `--term` for Zürich (no canton filter available) |
| 3 | Workforce Australia | `workforce-au-search` | `--search-text "<term>"` | `--sort date-desc` (default) | `--city <name>` |
| 3 | Job Bank Canada | `jobbank-ca-search` | `--search-text "<term>"` | `--days 14` | `--province <code>` |

Always pass `--format json` so results can be parsed and deduplicated.

---

## Query categories

### Priority 1: Data Engineering / BI Development
*Strongest experience match. Most realistic first full-time role.*

**Danish portals** (jobindex-search, jobnet-search, jobdanmark-search, jobbank-search):
- `data engineer aarhus`
- `BI developer aarhus`
- `BI konsulent aarhus`
- `business intelligence udvikler aarhus`
- `Microsoft Fabric danmark`
- `data engineer midtjylland`

**Luxembourg** (jobfinder-lu-search):
- `data engineer`
- `business intelligence`
- `data engineer luxembourg`
- `BI developer luxembourg`
- `data platform engineer`
- `analytics engineer`

**Switzerland** (jobs-ch-search — run both `--region central-switzerland` for Zug/Luzern and `--term "... zürich"` for Zürich, per the portal table):
- `data engineer`
- `BI developer`
- `business intelligence developer`
- `data engineer zürich`
- `data platform engineer`
- `analytics engineer zürich`

---

### Priority 2: AI Engineering / LLM Development
*Strong interest and growing skill set. Competitive but worth targeting.*

**Danish portals:**
- `AI engineer danmark`
- `LLM udvikler danmark`
- `kunstig intelligens udvikler aarhus`
- `AI developer danmark`
- `generative AI danmark`

**Luxembourg:**
- `AI engineer`
- `machine learning`
- `machine learning engineer`
- `AI developer luxembourg`

**Switzerland:**
- `AI engineer`
- `machine learning engineer`
- `AI engineer zürich`
- `LLM engineer`

---

### Priority 3: Data Analysis / Digital Transformation / Consulting
*Adjacent roles — good fit given your consulting/BI background (see `01-candidate-profile.md`).*

**Danish portals:**
- `dataanalytiker aarhus`
- `data analyst aarhus`
- `digital transformation konsulent aarhus`
- `teknologikonsulent aarhus`
- `it konsulent data aarhus`
- `BI konsulent danmark` (jobbank-search `--key`)

**Luxembourg:**
- `data analyst`
- `digital transformation consultant`
- `technology consultant`

**Switzerland:**
- `data analyst`
- `digital transformation consultant zürich`
- `technology consultant`

---

### Priority 4: Broader Net / Energy Sector / FinTech
*Domain-specific roles where background in energy or finance adds differentiation.*

**Energy sector (Danish portals):**
- `data engineer energi danmark`
- `analytiker energihandel danmark`
- `data energi aarhus`

**FinTech / Finance data (Danish portals):**
- `data engineer finans danmark`
- `dataanalytiker bank aarhus`

**Also consider (proactively suggested):**
- "Technical Consultant" / "Solutions Engineer" roles — bridges business and tech fluently
- "Data Platform Engineer" — strong Azure/Fabric/PySpark stack matches this title
- "Analytiker" / "Business Analyst" roles in data-heavy teams — entry point into more senior analytics work

---

## Location Filter Tiers

When evaluating results, classify job location as:

| Tier | Areas | Action |
|------|-------|--------|
| **Ideal** | Aarhus + surrounding municipalities; Luxembourg City + Greater Region | Include automatically |
| **Acceptable** | Anywhere in Jutland north of Vejle (Silkeborg, Randers, Viborg, Herning, Aalborg); Switzerland: **Zürich, Zug, Luzern only** (Zentralschweiz triangle + Kanton Zürich) | Include, note location |
| **Borderline** | East of Vejle (Kolding, Fredericia, Odense, Copenhagen direction); fully remote with English-speaking international employer | Include with flag: "location: borderline" |
| **Exclude** | South Jutland / Sønderjylland (unless remote); non-remote roles anywhere else | Skip |

---

## Date Filter

Only include jobs posted within the last **14 days**, or with an application deadline
not yet passed. If a portal doesn't support a recency filter, rely on dedup against
`seen_jobs.json` to avoid re-presenting old postings. If date cannot be determined,
include with flag: "date unknown".

### One-time catch-up runs (e.g. after time away)

`/scrape catchup` widens this to **30 days** for that run only — the standing 14-day
default above is not changed. Use this after any gap longer than ~2 weeks (vacation,
busy period, etc.) where postings could otherwise have aged out of the normal window
before ever being seen. 30 days (not an exact match to the gap) is deliberate:
`jobindex-search`'s `--jobage` flag only accepts discrete steps (`1`/`7`/`14`/`30`/`9999`),
so 30 is the smallest supported step that guarantees full coverage of any gap up to a
month. For portals using `--since <date>` (`jobbank-search`, `jobfinder-lu-search`),
compute the actual `today − 30 days` date. Expect substantially more results and a
slower run — most of the overlap with the normal 14-day zone will already be in
`seen_jobs.json` and gets deduped out as usual, so this is safe to run without
producing duplicate presentations.

After a catch-up run, resume normal `/scrape` (back to the standing 14-day window) —
don't leave the wide window running by default, it's meaningfully slower for no
ongoing benefit once you're caught up.

---

## Company career pages (optional, on request only)

If the user explicitly asks to check a specific company's career page (e.g. "check
Netcompany's careers page"), use `WebFetch` directly on that URL. This is a
deliberate, user-directed lookup — not part of the automatic `/scrape` run, and not
a substitute when a portal-search skill fails.

Relevant companies: Netcompany, Trifork, Systematic, KMD, Atea, EG, Ørsted, Vestas,
Energinet, Saxo Bank, Nykredit, Danske Bank, Deloitte DK, IBM DK, Accenture DK.

---

## Adapting Queries

If the user specifies a focus area, use terms from the matching priority category
plus 2-3 custom terms against the relevant portal(s). Examples:

- `/scrape catchup` → all Priority 1-3 terms against all Tier 1 portals (Danish, Luxembourg, Switzerland) with the 30-day window from the Date Filter section above, instead of the standing 14-day default. Use after a gap of 2+ weeks.
- `/scrape energy` → Priority 4 energy terms against Danish portals + `data scientist energihandel`, `quantitative analyst energi`
- `/scrape luxembourg` → jobfinder-lu-search with all Priority 1-3 Luxembourg terms
- `/scrape switzerland` → jobs-ch-search with all Priority 1-3 Switzerland terms, two passes per term: `--region central-switzerland` (Zug/Luzern) + `--term "... zürich"` (no canton filter for Zürich on jobs.ch)
- `/scrape canada` → jobbank-ca-search with Priority 1-3 terms in English (`data engineer`, `data analyst`, `business intelligence`)
- `/scrape australia` → workforce-au-search with Priority 1-3 terms in English
- `/scrape ai` → Priority 2 terms + `prompt engineer`, `AI product`, `LLM danmark`
- `/scrape consulting` → Priority 3 + `management consulting data`, `ERP data consultant`
