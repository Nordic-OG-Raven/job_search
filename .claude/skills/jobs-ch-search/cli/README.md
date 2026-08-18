# jobs.ch CLI

CLI for [jobs.ch](https://www.jobs.ch), the largest Swiss job portal (JobCloud group). No
authentication required.

jobs.ch's search/detail pages are server-rendered with a large `__INIT__ = {...}` JSON object
embedded in the HTML containing the full search results and meta, plus a `JobPosting` JSON-LD
block on detail pages — so this CLI parses those directly rather than scraping rendered HTML
text. The dedicated API subdomains (`job-search-api.jobs.ch`, etc.) are behind AWS WAF/CAPTCHA
and were not used.

## Commands

### `search`

```bash
bun run src/cli.ts search [flags]
```

Searches `https://www.jobs.ch/{en|de}/vacancies/` (server-rendered, 20 results/page).

Flags:
- `--term <text>` — free-text search (job title, skill, company)
- `--employment-grade-min <0-100>` / `--employment-grade-max <0-100>` — filter by % of full time
- `--region central-switzerland` — jobs.ch's own server-side region filter for Zentralschweiz (Lucerne, Zug, Schwyz, Uri, Obwalden, Nidwalden)
- `--page <n>` — upstream page to start from (1-indexed, default 1)
- `--limit <n>` — max results returned, default 10, max 50 (fetches additional upstream pages automatically if `limit` exceeds one page of 20)
- `--lang en|de` — site locale for search and result URLs, default `en`
- `--format json|table|plain`

### `detail`

```bash
bun run src/cli.ts detail <id> [--lang en|de] [--format json|plain]
```

Fetches `https://www.jobs.ch/{en|de}/vacancies/detail/{id}/` and extracts the `JobPosting` and
`BreadcrumbList` JSON-LD blocks: title, full description (HTML stripped), company name/website/
logo, location (street/postal code/city/country), date posted, industry, employment type,
occupational category, and category breadcrumb path.

`id` is the UUID returned as `id` in `search` results.

---

## Region filtering — how it works

jobs.ch's search URL accepts `term`, `employment-grade-min`/`-max`, `page`, and `region` as real
server-side filters (confirmed: changing any of them changes `totalHits`). `region` takes a
numeric `jobs_region` ID from jobs.ch's internal geographic taxonomy (discovered via
`metadata-api.jobs.ch/api/v1/meta/gis/type-ahead?subTypes[]=jobs_region`); `--region
central-switzerland` maps to `region=15` ("Central switzerland" / "Region zentralschweiz"),
which covers Lucerne, Zug, Schwyz, Uri, Obwalden and Nidwalden as a single region. Note: the
`term` query param must always be sent (even empty) — omitting it entirely while `region` is set
causes jobs.ch to 302-redirect and drop the region filter, so the CLI always includes `term=`.

This is a genuine server-side filter: `meta.totalHits` reflects the full region-wide count
(e.g. ~6,500 listings region-wide vs. ~570 for an unfiltered `term=python` search), and it
includes listings regardless of whether their `locations[]` field is populated. There is no
finer per-canton `jobs_region` (canton names like "Zug" or "Luzern" don't have their own
region IDs) — `central-switzerland` is the most specific geographic filter jobs.ch supports.

Each result item *may* additionally carry structured location data
(`locations: [{ cantonCode, city, postalCode, countryCode }]`, surfaced as `cantons` in the
CLI output) for roughly half of listings — this is informational only and is not used for
filtering.

---

## Notes

- All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.
- `detail` returns `NOT_FOUND` for a 404 (job no longer listed / invalid id).
- Job descriptions are in whatever language the employer posted in (mostly German, some English/French) — the `--lang` flag only changes the site UI locale and result/detail URLs, not the posting content.
