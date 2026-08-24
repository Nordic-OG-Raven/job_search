#!/usr/bin/env python3
"""
Morning job scan.

Runs daily via cron/launchd to find new listings across all configured
portals, deduplicates against a SQLite cache, evaluates fit via
`claude --print` against the profile in candidate_profile.txt (see
candidate_profile.example.txt), and writes a daily digest to
scripts/daily_digests/YYYY-MM-DD.md.
"""

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ============================================================
#  PATHS
# ============================================================

BASE_DIR   = Path(__file__).parent.parent        # ~/job_search
SCRIPTS    = Path(__file__).parent
DB_PATH    = SCRIPTS / "seen_jobs.db"
DIGESTS    = SCRIPTS / "daily_digests"
STATE_PATH = SCRIPTS / "run_state.json"
LOCK_PATH  = SCRIPTS / ".morning_scan.lock"
CANDIDATE_PROFILE_PATH = SCRIPTS / "candidate_profile.txt"

# shutil.which() first so this works out of the box on any machine where these
# are on PATH; falls back to this machine's known install location only if not.
CLAUDE_BIN = shutil.which("claude") or "/opt/homebrew/bin/claude"
BUN_BIN    = shutil.which("bun") or "/Users/jonas/.bun/bin/bun"
BUN_GUARD  = str(SCRIPTS / "bun_guarded.py")  # concurrency-capped, --smol wrapper — see that file

# Flush stdout/stderr line-by-line unconditionally — even when piped (not a
# real terminal) or launched via launchd, which sets no PYTHONUNBUFFERED.
# Without this, recent output sits in a buffer and is lost entirely if the
# process or the machine dies before the buffer flushes — exactly the
# scenario a crash-forensics log needs to survive.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# launchd/cron invoke this script with a minimal PATH (no /opt/homebrew/bin),
# but `claude` is a `#!/usr/bin/env node` script and needs node on PATH —
# without this, every claude --print call fails silently (empty stdout, no
# exception raised) and gets misrecorded as "Unknown" fit instead of erroring.
os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

def _arg_value(flag: str, default: str) -> str:
    """Read `--flag value` from sys.argv, falling back to `default` if absent."""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

# --since-days N: widen the lookback window for a one-off catch-up run
# (e.g. after time away). Default of 1 reproduces exactly today's normal
# daily-cron behavior — nothing changes for the scheduled run.
SINCE_DAYS = int(_arg_value("--since-days", "1"))

# --max-evals N: raise the per-run cap on `claude --print` evaluations for a
# catch-up run, since a wider window surfaces far more new listings than the
# default budget can evaluate in one pass. Default of 150 = today's behavior.
MAX_EVALUATIONS = int(_arg_value("--max-evals", "150"))

TODAY      = date.today().isoformat()
SINCE_DATE = (date.today() - timedelta(days=SINCE_DAYS)).isoformat()

# jobindex's --jobage only accepts discrete steps (1/7/14/30/9999) — snap up
# to the smallest step that still covers the full requested window.
_JOBINDEX_STEPS = [1, 7, 14, 30, 9999]
JOBINDEX_JOBAGE = str(next((s for s in _JOBINDEX_STEPS if s >= SINCE_DAYS), 9999))

# Portals with no native date filter (jobbank, jobs-ch, workforce-au) rely on
# --limit plus the post-fetch is_stale() cutoff below — widen both when the
# window is wider, or a longer catch-up would still only see ~15 most recent
# results per term and then discard anything older than the old fixed 48h.
_WIDE_LIMIT = "15" if SINCE_DAYS <= 2 else "40"

# Hard cutoff: reject any listing posted more than this many hours ago.
# Scales with --since-days so catch-up runs don't discard what they just
# widened the search to find.
MAX_AGE_HOURS = max(48, SINCE_DAYS * 24)
_CUTOFF_DT = datetime.now(tz=timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

# ============================================================
#  PORTAL CONFIGURATIONS
# ============================================================
# Each portal entry:
#   cli       - path to cli.ts relative to BASE_DIR
#   id_field  - JSON field name for the unique job ID in search results
#   searches  - list of arg-lists to pass to the CLI (each is one search call)
#   detail    - callable(job_id) -> arg-list for the detail command
#
# Each portal's search-term list is hand-maintained, not generated from one
# canonical term set — a term added for one portal doesn't automatically
# propagate to the others (e.g. "machine learning" as a standalone term
# currently only exists under jobindex). That's sometimes deliberate (not
# every portal's regional job market or query syntax matches), but it also
# means coverage can silently drift. If you're relying on this for a specific
# search term, verify it's actually present under every portal you care about.
# ============================================================

PORTALS = [
    {
        "name": "jobindex",
        "cli":  ".claude/skills/jobindex-search/cli/src/cli.ts",
        "id_field": "id",
        "searches": [
            ["search", "--query", "data engineer",         "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "analytics engineer",    "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "data analyst",          "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "data scientist",        "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "data consultant",       "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "BI developer",          "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "BI consultant",         "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "Power BI developer",    "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "business intelligence", "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "AI developer",          "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "AI engineer",           "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "ML engineer",            "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "machine learning",      "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobnet",
        "cli":  ".claude/skills/jobnet-search/cli/src/cli.ts",
        "id_field": "jobAdId",
        "searches": [
            # --per-page 10 keeps response small (avoids 65 KB JSON truncation)
            ["search", "--search-string", "data engineer",         "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "analytics engineer",    "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "data analyst",          "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "data scientist",        "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "data consultant",       "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "BI developer",          "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "BI consultant",         "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "Power BI developer",    "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "business intelligence", "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "AI developer",         "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "AI engineer",          "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
            ["search", "--search-string", "ML engineer",           "--since", SINCE_DATE, "--per-page", "10", "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobbank",
        "cli":  ".claude/skills/jobbank-search/cli/src/cli.ts",
        "id_field": "id",
        # No date filter on jobbank; limit to _WIDE_LIMIT most recent per query,
        # sorted by date. SQLite dedup handles any re-appearing jobs.
        "searches": [
            ["search", "--key", "data engineer",         "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "analytics engineer",    "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "data analyst",          "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "data scientist",        "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "data consultant",       "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "BI developer",          "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "BI consultant",         "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "Power BI developer",    "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "business intelligence", "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            # These 3 deliberately omit --work-area 43 ("Data & Analyse") — AI/ML
            # postings are often categorized under "IT-Software" (31) or left
            # unfiled in jobbank's own taxonomy, so scoping to 43 here risks
            # missing real postings rather than just narrowing noise. Revisit
            # if this proves too broad in practice.
            ["search", "--key", "AI developer",          "--location", "8", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "AI engineer",           "--location", "8", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "ML engineer",            "--location", "8", "--limit", _WIDE_LIMIT, "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobdanmark",
        "cli":  ".claude/skills/jobdanmark-search/cli/src/cli.ts",
        "id_field": "slug",
        "searches": [
            ["search", "--text", "data engineer",         "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "analytics engineer",    "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "data analyst",          "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "data scientist",        "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "data consultant",       "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "BI developer",          "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "BI consultant",         "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "Power BI developer",    "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "business intelligence", "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "AI engineer",           "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "ML engineer",            "--since", SINCE_DATE, "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobfinder-lu",
        "cli":  ".claude/skills/jobfinder-lu-search/cli/src/cli.ts",
        "id_field": "id",
        "searches": [
            ["search", "--query", "data engineer",         "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "analytics engineer",    "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "data analyst",          "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "data scientist",        "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "data consultant",       "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "BI developer",          "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "BI consultant",         "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "Power BI developer",    "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "business intelligence", "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "AI engineer",           "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "ML engineer",            "--since", SINCE_DATE, "--format", "json"],
            # Category browse (IT; Banking & Finance) — the free-text --query above only
            # matches literal English phrases against title/description, which misses
            # French/German-titled postings and returns near-zero hits for compound
            # phrases (verified live: "data scientist"/"AI engineer"/etc return 0).
            # Filtering by the site's own category taxonomy sidesteps that unreliable
            # text matching entirely. IDs from `filters --group categories`.
            ["search", "--filter", "63e0110df1bf6ae542db6973", "--since", SINCE_DATE, "--limit", "50", "--format", "json"],  # IT
            ["search", "--filter", "63e0110df1bf6ae542db6965", "--since", SINCE_DATE, "--limit", "50", "--format", "json"],  # Banking & Finance
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobs-ch",
        "cli":  ".claude/skills/jobs-ch-search/cli/src/cli.ts",
        "id_field": "id",
        "searches": [
            # Zentralschweiz region filter (Zug, Luzern, Schwyz, Uri, Obwalden, Nidwalden)
            ["search", "--term", "data engineer",         "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "analytics engineer",    "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "data analyst",          "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "data scientist",        "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "BI developer",          "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "Power BI developer",    "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "business intelligence", "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "ML engineer",            "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            # Zürich (no canton filter available on jobs.ch; include city in term)
            ["search", "--term", "data engineer zürich",         "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "analytics engineer zürich",    "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "data analyst zürich",          "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "data scientist zürich",        "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "business intelligence zürich", "--limit", _WIDE_LIMIT, "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "workforce-au",
        "enabled": False,
        "cli":  ".claude/skills/workforce-au-search/cli/src/cli.ts",
        "id_field": "vacancyId",
        "searches": [
            ["search", "--search-text", "data engineer",         "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "analytics engineer",    "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "data analyst",          "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "data scientist",        "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "BI developer",          "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "Power BI developer",    "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "business intelligence", "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--search-text", "ML engineer",            "--sort", "date-desc", "--limit", _WIDE_LIMIT, "--format", "json"],
        ],
        "detail": lambda jid: ["detail", str(jid), "--format", "plain"],
    },
    {
        "name": "jobbank-ca",
        "enabled": False,
        "cli":  ".claude/skills/jobbank-ca-search/cli/src/cli.ts",
        "id_field": "jobId",
        "searches": [
            ["search", "--search-text", "data engineer",         "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
            ["search", "--search-text", "analytics engineer",    "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
            ["search", "--search-text", "data analyst",          "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
            ["search", "--search-text", "data scientist",        "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
            ["search", "--search-text", "BI developer",          "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
            ["search", "--search-text", "business intelligence", "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
            ["search", "--search-text", "ML engineer",            "--days", str(SINCE_DAYS), "--sort", "date", "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
]
PORTALS = [cfg for cfg in PORTALS if cfg.get("enabled", True)]

# --portal <name>: restrict this run to one or more specific portals
# (repeatable or comma-separated), e.g. for a targeted backfill after fixing
# a single portal's search logic. Default (no flag) runs all configured
# portals, matching the standard daily behavior.
_portal_filter_raw = _arg_value("--portal", "")
if _portal_filter_raw:
    _portal_filter = {p.strip() for p in _portal_filter_raw.split(",") if p.strip()}
    _unknown = _portal_filter - {cfg["name"] for cfg in PORTALS}
    if _unknown:
        print(f"[ERROR] unknown --portal value(s): {', '.join(sorted(_unknown))}", file=sys.stderr)
        print(f"        valid portals: {', '.join(cfg['name'] for cfg in PORTALS)}", file=sys.stderr)
        sys.exit(1)
    PORTALS = [cfg for cfg in PORTALS if cfg["name"] in _portal_filter]

# ============================================================
#  FIT EVALUATION PROMPT
# ============================================================

# Jobs are evaluated in batches of this size per `claude --print` call rather
# than one call per job. Each `claude --print` spawn costs ~400MB RSS regardless
# of prompt size — that per-process overhead, multiplied by up to MAX_EVALUATIONS
# (150) sequential spawns, is what actually drove the recurring memory-pressure
# aborts, not concurrency. Batching cuts spawn count (and therefore that
# cumulative overhead) by ~EVAL_BATCH_SIZE times.
EVAL_BATCH_SIZE = 5

# A job whose detail-fetch came back empty or near-empty (removed listing,
# dead job_id, portal CLI error) must never enter a batch: caught via a real
# production run where one such job made claude refuse to rate the entire
# batch of 5, since it had nothing to evaluate for that one job and wouldn't
# guess. Filter these out before they can spoil otherwise-good jobs sharing
# their batch.
MIN_DESCRIPTION_CHARS = 30

def _load_candidate_profile() -> str:
    """
    The fit-evaluation prompt needs a real candidate bio, location rules, and
    exclusion criteria — this is personal by nature, so it lives in a
    gitignored file rather than hardcoded in this script. See
    candidate_profile.example.txt for the format; copy it to
    candidate_profile.txt and fill in your own details before running this.
    """
    if not CANDIDATE_PROFILE_PATH.exists():
        example = CANDIDATE_PROFILE_PATH.with_name("candidate_profile.example.txt")
        sys.exit(
            f"[SETUP] {CANDIDATE_PROFILE_PATH} not found.\n"
            f"Copy {example} to {CANDIDATE_PROFILE_PATH} and fill in your own "
            f"background, location preferences, and exclusion rules."
        )
    return CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8").strip()


CANDIDATE_PROFILE = _load_candidate_profile()

FIT_PROMPT_BATCH_TEMPLATE = """\
You are evaluating {n} job postings for this candidate. For EACH job below, reply \
with a block in EXACTLY this format, one per job, in the same order, and \
nothing else:

### JOB <number>
RATING: <Strong Fit|Good Fit|Borderline|No Fit>
REASON: <one sentence, max 20 words>

""" + CANDIDATE_PROFILE + """

{jobs}
"""

FIT_PROMPT_JOB_BLOCK = """\
--- JOB {n} ---
Title: {title}
Company: {company}
Portal: {portal}
Description:
{description}
"""

# ============================================================
#  DATABASE
# ============================================================

def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            portal       TEXT NOT NULL,
            job_id       TEXT NOT NULL,
            title        TEXT,
            company      TEXT,
            url          TEXT,
            first_seen   TEXT NOT NULL,
            fit_rating   TEXT,
            fit_notes    TEXT,
            status       TEXT DEFAULT 'new',
            PRIMARY KEY (portal, job_id)
        )
    """)
    conn.commit()


def is_seen(conn: sqlite3.Connection, portal: str, job_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_jobs WHERE portal=? AND job_id=?", (portal, str(job_id))
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, portal: str, job_id: str,
              title: str, company: str, url: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO seen_jobs (portal, job_id, title, company, url, first_seen)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (portal, str(job_id), title, company, url, TODAY)
    )
    conn.commit()


def update_fit(conn: sqlite3.Connection, portal: str, job_id: str,
               rating: str, notes: str) -> None:
    conn.execute(
        "UPDATE seen_jobs SET fit_rating=?, fit_notes=? WHERE portal=? AND job_id=?",
        (rating, notes, portal, str(job_id))
    )
    conn.commit()


def find_existing_rating(conn: sqlite3.Connection, title: str, company: str,
                          exclude_portal: str, exclude_job_id: str) -> tuple[str, str] | None:
    """
    The same posting often reappears under a new job_id after a portal
    re-indexes it (confirmed on real data: one job existed under 3 separate
    job_ids across June, July, and August). Look up whether this exact
    title+company already has a real rating elsewhere so it can be copied
    instead of spending a fetch_detail + evaluate_fit_batch call re-deciding
    something already decided. Returns (rating, notes) to copy, or None if
    this is genuinely unseen.
    """
    row = conn.execute(
        "SELECT fit_rating, fit_notes FROM seen_jobs "
        "WHERE title = ? AND company = ? AND fit_rating NOT IN ('', 'Unknown') "
        "AND fit_rating IS NOT NULL AND NOT (portal = ? AND job_id = ?) "
        "LIMIT 1",
        (title, company, exclude_portal, str(exclude_job_id)),
    ).fetchone()
    return (row[0], row[1]) if row else None


def cache_size(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]

# ============================================================
#  PORTAL CLI HELPERS
# ============================================================

def _extract_results_from_text(text: str) -> list[dict]:
    """
    Fallback for portals whose JSON output is truncated (e.g. jobnet's huge
    facets section hits a pipe/buffer limit at ~64 KB).  Finds the first
    "results": [...] array in the text and parses as much of it as is valid.
    """
    m = re.search(r'"results"\s*:\s*(\[)', text)
    if not m:
        return []
    start = m.start(1)
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(text[start:]):
        if escape:            escape = False; continue
        if ch == "\\" and in_str: escape = True; continue
        if ch == '"':         in_str = not in_str; continue
        if in_str:            continue
        if ch in ("[", "{"):  depth += 1
        elif ch in ("]", "}"):
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : start + i + 1])
                except json.JSONDecodeError:
                    pass
    return []


def _run_with_group_kill(cmd: list[str], *, input: str | None = None,
                          cwd: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """
    Like subprocess.run(), but on timeout kills the whole process group,
    not just the direct child. Plain subprocess.run(timeout=...) only kills
    the top-level process it launched — if that process (e.g. the `claude`
    CLI, which is a Node program) has spawned children of its own, those
    survive the kill, get reparented to launchd, and keep running orphaned
    and unsupervised. Over hundreds of invocations with some hitting the
    timeout, that accumulates real memory pressure with nothing left to
    account for it. start_new_session=True puts the child in its own
    process group so killpg reaches every descendant at once.
    """
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # process group already gone
        proc.communicate()  # reap the killed process, avoid a zombie
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


# ============================================================
#  RUN STATE — crash forensics, resumption, resource guardrail
# ============================================================

_LOCK_FD: int | None = None


def _acquire_single_instance_lock() -> None:
    """
    Refuse to start if another morning_scan.py is already running (e.g. a cron
    re-trigger firing before the previous run finished, or a manual
    --redo-unknown overlapping the scheduled run). Two copies running at once
    double every source of memory pressure in this file at exactly the moment
    that's worst. flock ties the lock to this process's open file descriptor,
    so the OS releases it automatically on exit, crash, or kill -9 — no
    stale-lock file to clean up by hand.
    """
    global _LOCK_FD
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = ""
        try:
            holder = f" (pid {os.read(fd, 32).decode().strip()})"
        except OSError:
            pass
        print(f"[ERROR] another morning_scan.py is already running{holder} — "
              f"exiting rather than run concurrently and double memory pressure.",
              file=sys.stderr)
        sys.exit(1)
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    _LOCK_FD = fd  # held for the process lifetime; released explicitly before
                   # an auto-resume re-exec, or automatically by the OS on exit


def _release_single_instance_lock() -> None:
    global _LOCK_FD
    if _LOCK_FD is not None:
        os.close(_LOCK_FD)
        _LOCK_FD = None


def _write_state(**fields) -> None:
    """
    Overwrite scripts/run_state.json with the given fields merged into
    whatever's already there, plus a fresh heartbeat timestamp. Written
    atomically (write to a temp file, then rename) so a crash mid-write
    never leaves a corrupt state file behind. Call this after every
    meaningful step, not just at the end — the whole point is that it's
    readable *while* the run is still going, and left behind if it dies.
    """
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            state = {}
    state.update(fields)
    state["last_heartbeat_at"] = datetime.now(tz=timezone.utc).isoformat()
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def _report_previous_run_if_crashed() -> None:
    """
    On startup, check whether the last run left the state file in a
    non-"done" phase — that means it never reached a clean exit, i.e. it
    crashed, was killed, or the machine went down. Report exactly what it
    was doing at last heartbeat, so there's something concrete to look at
    instead of reconstructing it from OS crash logs.
    """
    if not STATE_PATH.exists():
        return
    try:
        prev = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if prev.get("phase") in ("done", None):
        return
    print(
        f"[RECOVERY] Previous run (pid {prev.get('pid')}, started {prev.get('started_at')}) "
        f"never finished cleanly.\n"
        f"  Last phase:     {prev.get('phase')}\n"
        f"  Last action:    {prev.get('last_action')}\n"
        f"  Last portal:    {prev.get('current_portal')}\n"
        f"  Evals done:     {prev.get('eval_count')}\n"
        f"  Last heartbeat: {prev.get('last_heartbeat_at')}\n"
        f"  If evaluations were in progress, run with --redo-unknown to pick up "
        f"anything left rated Unknown from that run.",
        file=sys.stderr,
    )


def _swap_usage_fraction() -> float | None:
    """Return current swap-used / swap-total as a fraction, or None if unavailable."""
    try:
        out = subprocess.run(
            ["sysctl", "vm.swapusage"], capture_output=True, text=True, timeout=5
        ).stdout
        # vm.swapusage: total = 3072.00M  used = 1987.25M  free = 1084.75M  (encrypted)
        m = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", out)
        if not m:
            return None
        total, used = float(m.group(1)), float(m.group(2))
        return used / total if total > 0 else None
    except Exception:
        return None


# Tiered response to swap pressure: shrink the unit of work (batch size)
# before ever fully stopping. A full pause used to trigger at 85% swap with
# nothing in between "normal" and "stopped" — which meant ordinary background
# load (other apps, other Claude sessions) could halt the whole pipeline even
# though there was still real, safe headroom for smaller steps. Real pause is
# now reserved for genuinely critical pressure, not merely elevated pressure.
SWAP_COMFORTABLE_THRESHOLD = 0.75  # below this: full EVAL_BATCH_SIZE
SWAP_ELEVATED_THRESHOLD    = 0.85  # below this: half batch size
SWAP_CRITICAL_THRESHOLD    = 0.95  # below this: batch size 1 (minimal footprint,
                                    # still makes forward progress); at/above
                                    # this, even one more ~400MB spawn is a real
                                    # risk (established: near-total swap
                                    # exhaustion on this machine risks kernel-
                                    # level instability) — only here do we abort.
SWAP_ABORT_THRESHOLD = SWAP_CRITICAL_THRESHOLD


def _adaptive_batch_size(ceiling: int) -> int:
    """
    How many jobs is it safe to send to claude --print in one call right now?
    Scales down as swap pressure rises instead of the pipeline just stopping —
    the actual lever a batch pipeline has against memory pressure is how much
    work it attempts per step, not how long it waits. Returns 0 only when
    swap is critical enough that even a single evaluation is unsafe; the
    caller falls back to the retry-then-abort path in that case.
    """
    frac = _swap_usage_fraction()
    if frac is None:
        return ceiling
    if frac <= SWAP_COMFORTABLE_THRESHOLD:
        return ceiling
    if frac <= SWAP_ELEVATED_THRESHOLD:
        return max(1, ceiling // 2)
    if frac <= SWAP_CRITICAL_THRESHOLD:
        return 1
    return 0


def _notify(title: str, body: str, subtitle: str = "") -> None:
    """Fire a macOS notification banner. Best-effort — a failure here must
    never be the reason a run aborts."""
    script = (
        f'display notification {json.dumps(body, ensure_ascii=False)} '
        f'with title {json.dumps(title, ensure_ascii=False)} '
        + (f'subtitle {json.dumps(subtitle, ensure_ascii=False)} ' if subtitle else '')
        + 'sound name "Glass"'
    )
    try:
        subprocess.run(["osascript", "-e", script], timeout=10)
    except Exception as e:
        print(f"  [WARN] notification failed: {e}", file=sys.stderr)


# How long to wait and how many times to recheck before actually giving up —
# rides out short transient spikes (another app briefly hogging memory)
# instead of aborting on the first high reading, which is the common case.
# Persistent pressure (like a multi-hour episode) will still exhaust these
# retries and abort, same as before.
MEMORY_RETRY_ATTEMPTS = 5
MEMORY_RETRY_DELAY_SECONDS = 60


def _check_memory_pressure_or_abort(context: str) -> bool:
    """
    Swap-usage check with retry-and-backoff. Returns True if it's safe to
    continue. On sustained high swap usage — not just a momentary reading —
    logs a warning, fires a macOS notification so this is discovered the
    same day rather than by chance days later, and returns False so the
    caller can stop the run cleanly (write final state, close the DB)
    instead of continuing blind and risking exactly the kind of
    system-wide resource exhaustion that can end in a kernel panic.
    Fails open — a broken check should never itself be the reason a run
    stops.
    """
    for attempt in range(MEMORY_RETRY_ATTEMPTS):
        frac = _swap_usage_fraction()
        if frac is None:
            return True
        if frac <= SWAP_ABORT_THRESHOLD:
            return True
        if attempt < MEMORY_RETRY_ATTEMPTS - 1:
            print(
                f"  [WARN] swap usage at {frac:.0%} ({context}) — waiting "
                f"{MEMORY_RETRY_DELAY_SECONDS}s and rechecking "
                f"({attempt + 1}/{MEMORY_RETRY_ATTEMPTS}) before giving up.",
                file=sys.stderr,
            )
            time.sleep(MEMORY_RETRY_DELAY_SECONDS)
        else:
            print(
                f"  [WARN] swap usage still at {frac:.0%} after "
                f"{MEMORY_RETRY_ATTEMPTS} checks over "
                f"{MEMORY_RETRY_ATTEMPTS * MEMORY_RETRY_DELAY_SECONDS}s ({context}) "
                f"— stopping run early rather than continuing under memory "
                f"pressure. Use --redo-unknown to pick up where this left off "
                f"once memory frees up.",
                file=sys.stderr,
            )
            _notify(
                "Job scan paused — low memory",
                f"Stopped after {context} — swap at {frac:.0%}. "
                f"Run --redo-unknown once memory frees up.",
            )
            return False
    return True


AUTO_RESUME_MAX_WAIT_SECONDS = 1800  # give memory up to 30 min to recover
AUTO_RESUME_POLL_SECONDS     = 300   # ...checking every 5 min


def _auto_resume_after_pause() -> None:
    """
    A run that paused for memory pressure used to just sit there until a
    human noticed the notification and remembered to run --redo-unknown by
    hand — which is exactly what let 227 jobs across two separate days go
    silently unevaluated. This waits (bounded) for swap to actually recover,
    then launches exactly ONE follow-up --redo-unknown pass automatically.

    Bounded to a single attempt by construction: the follow-up run is invoked
    with --no-auto-resume, so even if IT also pauses, nothing chains further.
    A chronically memory-starved machine still ends up needing a human, same
    as before — this only closes the gap for the common case where memory
    was just transiently tight and would have recovered anyway.
    """
    if "--no-auto-resume" in sys.argv:
        return
    print(
        f"\n[auto-resume] waiting up to {AUTO_RESUME_MAX_WAIT_SECONDS}s for "
        f"memory to recover before retrying automatically...",
        file=sys.stderr,
    )
    waited = 0
    recovered = False
    while waited < AUTO_RESUME_MAX_WAIT_SECONDS:
        time.sleep(AUTO_RESUME_POLL_SECONDS)
        waited += AUTO_RESUME_POLL_SECONDS
        frac = _swap_usage_fraction()
        if frac is None or frac <= SWAP_ABORT_THRESHOLD:
            recovered = True
            break
        print(f"  [auto-resume] still at {frac:.0%} swap after {waited}s...", file=sys.stderr)

    if not recovered:
        print(
            f"[auto-resume] memory never recovered after {AUTO_RESUME_MAX_WAIT_SECONDS}s "
            f"— giving up. Run --redo-unknown by hand once memory frees up.",
            file=sys.stderr,
        )
        return

    print("[auto-resume] memory recovered — launching one --redo-unknown pass...", file=sys.stderr)
    _release_single_instance_lock()
    try:
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--redo-unknown", "--no-auto-resume"],
            cwd=str(BASE_DIR),
        )
    except Exception as e:
        print(f"[auto-resume] follow-up run failed to launch: {e}", file=sys.stderr)


def run_cli(portal_cfg: dict, args: list[str]) -> list[dict]:
    """Run a portal CLI command and return the results list, or [] on error."""
    cmd = [sys.executable, BUN_GUARD, portal_cfg["cli"]] + args
    try:
        result = _run_with_group_kill(cmd, cwd=str(BASE_DIR), timeout=60)
        if result.returncode != 0:
            print(f"  [WARN] {portal_cfg['name']} CLI error: {result.stderr[:200]}", file=sys.stderr)
            return []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Partial JSON (e.g. jobnet truncates at 64 KB) — salvage results array
            salvaged = _extract_results_from_text(result.stdout)
            if salvaged:
                print(f"  [INFO] {portal_cfg['name']}: partial JSON, salvaged {len(salvaged)} results", file=sys.stderr)
            return salvaged
        # Normalise: results list may live under different keys
        if isinstance(data, list):
            return data
        for key in ("results", "jobs", "listings", "jobAds"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
    except subprocess.TimeoutExpired:
        print(f"  [WARN] {portal_cfg['name']} timed out", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [WARN] {portal_cfg['name']} error: {e}", file=sys.stderr)
        return []


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def extract_posted_date(text: str) -> datetime | None:
    """
    Try to extract a posting date from plain-text job detail.
    Returns an aware datetime (UTC) or None if unparseable.
    Patterns handled:
      - ISO: 2026-05-19T10:21:02+02:00  or  2026-05-19
      - ISO with microseconds: 2026-05-19T10:21:02.000000+00:00 (jobfinder-lu "Online since:")
      - jobs.ch description: "Date published 19-May-2026"
      - Danish: "Oprettet: 19-05-2026" / "19.05.2026"
    """
    # ISO datetime with timezone offset (most reliable) — microseconds optional
    m = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2})', text)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            pass

    # ISO date-only  YYYY-MM-DD
    m = re.search(r'(?:datePosted|Date published|posted|oprettet)[^0-9]{0,10}(\d{4}-\d{2}-\d{2})', text, re.IGNORECASE)
    if m:
        try:
            return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # "19-May-2026" style (jobs.ch description text)
    m = re.search(r'Date published\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})', text)
    if m:
        day, mon_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mon = _MONTH_MAP.get(mon_str)
        if mon:
            return datetime(year, mon, day, tzinfo=timezone.utc)

    # DD-MM-YYYY or DD.MM.YYYY after keyword
    m = re.search(r'(?:oprettet|publiceret|posted)[^0-9]{0,10}(\d{1,2})[.\-](\d{1,2})[.\-](\d{4})', text, re.IGNORECASE)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def is_stale(detail_text: str, portal_name: str) -> bool:
    """
    Return True if the job is older than MAX_AGE_HOURS.
    Portals with server-side date filters are trusted and skipped here.
    """
    # These portals already filter server-side — trust them.
    # jobfinder-lu is deliberately NOT in this set: its detail plain-text output
    # includes a parseable "Online since: <ISO datetime>" line, so the real
    # staleness check below can run instead of skipping the check entirely.
    TRUSTED_PORTALS = {"jobindex", "jobnet", "jobdanmark", "jobbank-ca"}
    if portal_name in TRUSTED_PORTALS:
        return False

    dt = extract_posted_date(detail_text)
    if dt is None:
        return False  # can't determine age — give it the benefit of the doubt

    # Ensure aware comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < _CUTOFF_DT


def fetch_detail(portal_cfg: dict, job_id: str) -> str:
    """Fetch full job description as plain text."""
    args = portal_cfg["detail"](job_id)
    cmd  = [sys.executable, BUN_GUARD, portal_cfg["cli"]] + args
    try:
        result = _run_with_group_kill(cmd, cwd=str(BASE_DIR), timeout=60)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""

# ============================================================
#  FIT EVALUATION
# ============================================================

def _parse_fit_block(block_text: str) -> tuple[str, str]:
    rating, notes = "Unknown", (block_text.strip()[:200] or "No response for this job.")
    for line in block_text.splitlines():
        line = line.strip()
        if line.startswith("RATING:"):
            raw = line.split(":", 1)[1].strip()
            low = raw.lower()
            if "strong" in low:
                rating = "Strong Fit"
            elif "good" in low:
                rating = "Good Fit"
            elif "borderline" in low:
                rating = "Borderline"
            elif "no fit" in low:
                rating = "No Fit"
            else:
                rating = raw
        elif line.startswith("REASON:"):
            notes = line.split(":", 1)[1].strip()
    return rating, notes


_JOB_BLOCK_RE = re.compile(r"^###\s*JOB\s*(\d+)\s*$", re.MULTILINE)


def evaluate_fit_batch(jobs: list[dict]) -> list[tuple[str, str]]:
    """
    Call `claude --print` ONCE for up to EVAL_BATCH_SIZE jobs instead of once
    per job — each `claude --print` spawn costs ~400MB RSS regardless of how
    much is in the prompt, so batching is the main lever against the per-run
    memory pressure this pipeline kept tripping on.

    jobs: list of {"title", "company", "portal", "description"}
    Returns a list of (rating, notes) in the same order as `jobs`. Ratings are
    one of: Strong Fit | Good Fit | Borderline | No Fit | Unknown
    """
    if not jobs:
        return []

    # Defense in depth: both call sites already filter these out before they
    # ever reach here, but a job with no real description must never be sent
    # to the model regardless — a real production run showed claude will
    # refuse to rate a job it has nothing to evaluate, which silently killed
    # the rating for every OTHER job sharing that batch too.
    results: list[tuple[str, str] | None] = [None] * len(jobs)
    evaluable_idx = []
    for i, j in enumerate(jobs):
        if len(j["description"].strip()) < MIN_DESCRIPTION_CHARS:
            results[i] = ("No Fit", "Detail fetch returned empty — listing likely removed/expired.")
        else:
            evaluable_idx.append(i)

    if not evaluable_idx:
        return results  # every job in this batch had nothing to evaluate

    evaluable_jobs = [jobs[i] for i in evaluable_idx]
    safe = lambda s: s.replace('{', '{{').replace('}', '}}')
    job_blocks = "\n".join(
        FIT_PROMPT_JOB_BLOCK.format(
            n=n, title=safe(j["title"][:200]), company=safe(j["company"][:100]),
            portal=j["portal"], description=safe(j["description"][:3000]),
        )
        for n, j in enumerate(evaluable_jobs, 1)
    )
    prompt = FIT_PROMPT_BATCH_TEMPLATE.format(n=len(evaluable_jobs), jobs=job_blocks)

    try:
        result = _run_with_group_kill(
            [CLAUDE_BIN, "--print", "--output-format", "text",
             "--model", "claude-haiku-4-5-20251001"],
            input=prompt,
            timeout=40 + 20 * len(evaluable_jobs),
            cwd=str(BASE_DIR),
        )
    except Exception as e:
        print(f"  [WARN] claude --print (batch of {len(evaluable_jobs)}) failed: {e}", file=sys.stderr)
        for i in evaluable_idx:
            results[i] = ("Unknown", "Batch evaluation failed.")
        return results

    if result.returncode != 0:
        err = result.stderr.strip()[:200]
        out = result.stdout.strip()[:200]
        print(f"  [WARN] claude --print (batch of {len(evaluable_jobs)}) exited {result.returncode}: "
              f"stderr={err!r} stdout={out!r}", file=sys.stderr)
        for i in evaluable_idx:
            results[i] = ("Unknown", f"claude exited {result.returncode}: {err or out}")
        return results

    output = result.stdout.strip()
    matches = list(_JOB_BLOCK_RE.finditer(output))
    parsed: dict[int, tuple[str, str]] = {}
    for idx, m in enumerate(matches):
        job_num = int(m.group(1))
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(output)
        parsed[job_num] = _parse_fit_block(output[start:end])

    for n, i in enumerate(evaluable_idx, 1):
        results[i] = parsed.get(n, ("Unknown", "Batch response missing this job's block."))
    return results

# ============================================================
#  DIGEST WRITER
# ============================================================

def write_digest(new_jobs: list[dict], n_portals: int, n_new: int, total_cache: int) -> Path:
    DIGESTS.mkdir(parents=True, exist_ok=True)
    path = DIGESTS / f"{TODAY}.md"

    buckets: dict[str, list[dict]] = {
        "Strong Fit":    [],
        "Good Fit":      [],
        "Borderline":    [],
        "No Fit":        [],
        "Unknown":       [],
        "Not Evaluated": [],  # fit_rating == "" — search found it, but it never got a detail-fetch + evaluate_fit call (e.g. run paused for memory pressure)
    }
    for job in new_jobs:
        key = job["fit_rating"] or "Not Evaluated"
        buckets.setdefault(key, []).append(job)

    evaluated_count = sum(len(v) for k, v in buckets.items() if k != "Not Evaluated")
    not_evaluated = buckets["Not Evaluated"]

    lines = [f"# Morning Job Scan — {TODAY}", ""]

    if n_new == 0:
        lines += ["*No new listings found today.*", ""]
    else:
        if not_evaluated:
            lines.append(
                f"**⚠ {len(not_evaluated)} listing(s) found but never evaluated** "
                f"(run paused before reaching them). Run `scripts/morning_scan.py "
                f"--redo-unknown` to evaluate them — see below."
            )
            lines.append("")

        for bucket_name in ("Strong Fit", "Good Fit", "Borderline"):
            jobs = buckets[bucket_name]
            if not jobs:
                continue
            lines.append(f"## {bucket_name} ({len(jobs)})")
            lines.append("")
            lines.append("| Portal | Title | Company | URL | Notes |")
            lines.append("|--------|-------|---------|-----|-------|")
            for j in jobs:
                title   = j["title"].replace("|", "\\|")
                company = j["company"].replace("|", "\\|")
                notes   = j["fit_notes"].replace("|", "\\|")
                url     = j["url"]
                lines.append(f"| {j['portal']} | {title} | {company} | [link]({url}) | {notes} |")
            lines.append("")

        if not_evaluated:
            lines.append(f"## Not Yet Reviewed ({len(not_evaluated)} — found but never evaluated)")
            lines.append("")
            for j in not_evaluated:
                lines.append(f"- {j['portal']} · {j['title']} @ {j['company']}")
            lines.append("")

        no_fit = buckets["No Fit"] + buckets["Unknown"]
        if no_fit:
            lines.append(f"## Excluded ({len(no_fit)} — No Fit / Unknown)")
            lines.append("")
            for j in no_fit:
                lines.append(f"- {j['portal']} · {j['title']} @ {j['company']}")
            lines.append("")

    lines.append("---")
    lines.append(
        f"*Searched {n_portals} portals · {n_new} new listings found · "
        f"{evaluated_count} evaluated · {len(not_evaluated)} not yet reviewed · "
        f"{total_cache} total in cache*"
    )
    lines.append("")

    path.write_text("\n".join(lines))
    return path


def send_notification(strong: list[dict], good: list[dict], digest_path: Path) -> None:
    """Fire a macOS notification banner summarising today's matches."""
    if strong:
        title = f"{len(strong)} Strong Fit job(s) today"
        names = ", ".join(f"{j['title']} @ {j['company']}" for j in strong[:3])
        body = names if len(strong) <= 3 else f"{names}, +{len(strong) - 3} more"
    elif good:
        title = f"{len(good)} Good Fit job(s) today"
        body = ", ".join(f"{j['title']} @ {j['company']}" for j in good[:3])
    else:
        title = "Morning job scan complete"
        body = "No Strong/Good fits today."

    _notify(title, body, digest_path.name)


def _should_flush(pending: list[dict]) -> bool:
    """
    Whether to actually run a batch now. Under comfortable memory, wait to
    accumulate a full EVAL_BATCH_SIZE first — that's the whole point of
    batching, amortising the ~400MB fixed cost of a claude --print spawn
    across several jobs. Under any elevated pressure, don't wait to
    accumulate further — flush whatever's pending immediately (in a reduced,
    adaptively-sized chunk) so the run keeps making progress in small safe
    steps instead of sitting on unflushed work while conditions might be
    getting worse.
    """
    if not pending:
        return False
    if len(pending) >= EVAL_BATCH_SIZE:
        return True
    return _adaptive_batch_size(EVAL_BATCH_SIZE) < EVAL_BATCH_SIZE


def _flush_eval_batch(
    conn: sqlite3.Connection,
    pending: list[dict],
    eval_count: int,
    context: str,
) -> tuple[int, bool, list[dict], list[dict]]:
    """
    Evaluate as much of `pending` as is currently safe — up to
    _adaptive_batch_size(), which shrinks as swap pressure rises instead of
    the pipeline just refusing to proceed. Only when even a single evaluation
    is unsafe (swap at/above SWAP_CRITICAL_THRESHOLD, sustained through
    retries) does this actually pause the run.

    Returns (new_eval_count, stopped_for_memory, evaluated_jobs, leftover).
    `pending`/`leftover` entries carry "portal", "job_id", "title", "company",
    "description", and optionally "url"; evaluated_jobs is the subset that
    was actually processed, with "fit_rating"/"fit_notes" merged in.
    """
    if not pending:
        return eval_count, False, [], pending

    size = _adaptive_batch_size(len(pending))
    if size == 0:
        if not _check_memory_pressure_or_abort(f"{context} (before batch of {len(pending)})"):
            _write_state(phase="paused-memory-pressure", eval_count=eval_count)
            return eval_count, True, [], pending
        size = 1  # recovered during retries — proceed at the minimal safe size

    to_process, leftover = pending[:size], pending[size:]
    if size < len(pending):
        print(f"  [scale-down] swap pressure — evaluating {len(to_process)}/{len(pending)} "
              f"this round instead of the full batch", file=sys.stderr)

    print(f"  → evaluating batch of {len(to_process)}...")
    results = evaluate_fit_batch([
        {"title": j["title"], "company": j["company"], "portal": j["portal"],
         "description": j["description"]}
        for j in to_process
    ])

    evaluated = []
    for j, (rating, notes) in zip(to_process, results):
        update_fit(conn, j["portal"], j["job_id"], rating, notes)
        eval_count += 1
        print(f"  [{j['portal']}] → evaluated: {j['title'][:60]} -> {rating}")
        j2 = dict(j)
        j2["fit_rating"] = rating
        j2["fit_notes"] = notes
        evaluated.append(j2)

    _write_state(
        phase="evaluating", current_portal=to_process[-1]["portal"], eval_count=eval_count,
        last_action=f"batch-evaluated {len(to_process)}: last={to_process[-1]['title'][:60]} @ {to_process[-1]['portal']}",
    )
    time.sleep(0.5)
    return eval_count, False, evaluated, leftover


def _drain_pending(
    conn: sqlite3.Connection,
    pending: list[dict],
    eval_count: int,
    stopped_for_memory: bool,
    context: str,
    collect_into: list[dict] | None = None,
) -> tuple[int, bool]:
    """
    Flush whatever's left in `pending` until it's empty or a flush pauses for
    memory pressure — the identical tail both the redo and main-pass loops
    need after their own iteration ends, extracted so the pattern only has
    one place to be kept correct. `collect_into`, if given, is extended with
    each flushed job trimmed to the digest-row keys (the main pass needs this
    to build `new_jobs`; the redo pass re-queries the DB instead and doesn't).
    """
    while not stopped_for_memory and pending:
        eval_count, stopped_for_memory, evaluated, pending = _flush_eval_batch(conn, pending, eval_count, context)
        if collect_into is not None:
            for j in evaluated:
                collect_into.append({k: j[k] for k in
                                      ("portal", "job_id", "title", "company", "url", "fit_rating", "fit_notes")})
    return eval_count, stopped_for_memory


def _finish_run(conn: sqlite3.Connection, mode: str, run_count: int, stopped_for_memory: bool) -> None:
    """
    Shared tail for both the --redo-unknown and normal scan+evaluate code
    paths: regenerate today's full digest from the DB — never from just this
    run's own results, since a partial-scope run (e.g. --portal jobfinder-lu)
    must never clobber a fuller digest an earlier run wrote the same day —
    print the summary and top matches, notify, and update run state.

    Extracted after the two paths were found to have drifted in practice:
    the redo branch was silently missing the "No Strong/Good fits today"
    print that the main branch had, because the two were hand-copied instead
    of sharing this logic.
    """
    all_rows = conn.execute(
        "SELECT portal, job_id, title, company, url, fit_rating, fit_notes "
        "FROM seen_jobs WHERE first_seen >= ?", (TODAY,)
    ).fetchall()
    all_jobs = [
        {"portal": p, "job_id": jid, "title": t or "", "company": c or "",
         "url": u or "", "fit_rating": r or "", "fit_notes": n or ""}
        for p, jid, t, c, u, r, n in all_rows
    ]
    total_cache = cache_size(conn)
    conn.close()

    digest_path = write_digest(all_jobs, len(PORTALS), len(all_jobs), total_cache)
    if mode == "redo":
        print(f"\n=== Done [redo]: {run_count} re-evaluated, digest → {digest_path} ===")
    else:
        print(f"\n=== Done: {run_count} evaluated this run ({len(all_jobs)} total today), digest → {digest_path} ===")

    strong = [j for j in all_jobs if j["fit_rating"] == "Strong Fit"]
    good   = [j for j in all_jobs if j["fit_rating"] == "Good Fit"]
    if strong or good:
        print("\n★ TOP MATCHES:")
        for j in strong + good:
            print(f"  [{j['fit_rating']}] {j['title']} @ {j['company']} ({j['portal']})")
            print(f"    {j['url']}")
    else:
        print("No Strong/Good fits today.")

    send_notification(strong, good, digest_path)
    if stopped_for_memory:
        _auto_resume_after_pause()
    else:
        _write_state(phase="done")


# ============================================================
#  MAIN
# ============================================================

def main() -> None:
    populate_only = "--populate-cache" in sys.argv
    redo_mode     = "--redo-unknown" in sys.argv
    mode = "POPULATE CACHE (no evaluation)" if populate_only else ("redo Unknown/unevaluated" if redo_mode else "scan + evaluate")
    print(f"=== Morning scan {TODAY} [{mode}] ===")
    DIGESTS.mkdir(parents=True, exist_ok=True)

    _acquire_single_instance_lock()
    _report_previous_run_if_crashed()
    _write_state(
        pid=os.getpid(),
        started_at=datetime.now(tz=timezone.utc).isoformat(),
        mode=mode,
        since_days=SINCE_DAYS,
        max_evaluations=MAX_EVALUATIONS,
        phase="starting",
        eval_count=0,
        current_portal=None,
        last_action=None,
    )

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    new_jobs: list[dict] = []
    total_new = 0
    eval_count = 0

    if redo_mode:
        portal_by_name = {cfg["name"]: cfg for cfg in PORTALS}
        # No first_seen filter: this used to be scoped to `>= TODAY`, which
        # meant backlog from any day but today was permanently invisible to
        # --redo-unknown — a job that missed evaluation once could never be
        # picked up again. Confirmed via the DB this had been silently
        # accumulating since June 18 (1111 unevaluated rows across 2 months
        # by the time this was caught).
        rows = conn.execute(
            "SELECT portal, job_id, title, company, url FROM seen_jobs "
            "WHERE fit_rating IN ('Unknown', '') OR fit_rating IS NULL"
        ).fetchall()
        print(f"\n[redo] {len(rows)} Unknown/unevaluated jobs (all dates) to re-evaluate")
        stopped_for_memory = False
        pending: list[dict] = []
        for portal_name, job_id, title, company, url in rows:
            if (eval_count + len(pending)) >= MAX_EVALUATIONS:
                print(f"\n[limit] MAX_EVALUATIONS={MAX_EVALUATIONS} reached in redo pass")
                break
            portal_cfg = portal_by_name.get(portal_name)
            if not portal_cfg:
                print(f"  [redo] unknown portal '{portal_name}', skipping")
                continue
            existing = find_existing_rating(conn, title or "", company or "", portal_name, job_id)
            if existing:
                rating, notes = existing
                update_fit(conn, portal_name, job_id, rating,
                           f"{notes} (duplicate posting — rating copied from an earlier listing)")
                continue
            description = fetch_detail(portal_cfg, job_id)
            if len(description.strip()) < MIN_DESCRIPTION_CHARS:
                update_fit(conn, portal_name, job_id, "No Fit",
                           "Detail fetch returned empty — listing likely removed/expired.")
                continue
            if is_stale(description, portal_name):
                update_fit(conn, portal_name, job_id, "No Fit", "Stale listing (posted >48h ago).")
                continue
            pending.append({"portal": portal_name, "job_id": job_id, "title": title or "",
                             "company": company or "", "description": description})
            if _should_flush(pending):
                eval_count, stopped_for_memory, _, pending = _flush_eval_batch(conn, pending, eval_count, "redo pass")
                if stopped_for_memory:
                    break
        eval_count, stopped_for_memory = _drain_pending(
            conn, pending, eval_count, stopped_for_memory, "redo pass (final partial batch)")
        _finish_run(conn, "redo", eval_count, stopped_for_memory)
        return

    # Pass 1: search every portal and mark new listings seen, but don't
    # evaluate yet — this lets us round-robin the eval budget across portals
    # afterward instead of letting a high-volume portal (jobindex) drain the
    # MAX_EVALUATIONS cap before smaller/later portals (jobbank-ca) get a turn.
    portal_queues: list[tuple[dict, list[str]]] = []  # (portal_cfg, queue of job_ids)
    found_by_portal: dict[str, dict[str, dict]] = {}

    for portal_cfg in PORTALS:
        portal_name = portal_cfg["name"]
        id_field    = portal_cfg["id_field"]
        print(f"\n[{portal_name}]")
        _write_state(phase="searching", current_portal=portal_name, last_action=f"searching {portal_name}")

        # Collect unique job IDs across all search queries for this portal
        found: dict[str, dict] = {}  # job_id -> raw result dict
        for search_args in portal_cfg["searches"]:
            results = run_cli(portal_cfg, search_args)
            for r in results:
                jid = str(r.get(id_field, ""))
                if jid and jid not in found:
                    found[jid] = r

        # Deduplicate against cache
        new_ids = [jid for jid in found if not is_seen(conn, portal_name, jid)]
        print(f"  {len(found)} found, {len(new_ids)} new")

        found_by_portal[portal_name] = found
        portal_queues.append((portal_cfg, new_ids))

        for jid in new_ids:
            r       = found[jid]
            title   = r.get("title", "")
            company = r.get("company", r.get("companyName", r.get("employer", r.get("hiringOrgName", ""))))
            url     = r.get("url", "")
            # Mark seen immediately — re-runs will skip even if evaluation fails
            mark_seen(conn, portal_name, jid, title, company, url)
            total_new += 1

    if populate_only:
        pass  # cache-only mode: skip detail fetch and evaluation entirely
    else:
        # Pass 2: round-robin SELECT one job per portal per round (unchanged
        # fairness), but accumulate into `pending` and flush as a batch every
        # EVAL_BATCH_SIZE jobs instead of calling evaluate_fit per job. A batch
        # can span jobs from different portals — that's fine, batching is purely
        # a transport optimisation, each job's own portal travels with it.
        stopped_for_memory = False
        pending: list[dict] = []
        while (eval_count + len(pending)) < MAX_EVALUATIONS and any(queue for _, queue in portal_queues) and not stopped_for_memory:
            for portal_cfg, queue in portal_queues:
                if (eval_count + len(pending)) >= MAX_EVALUATIONS:
                    break
                if not queue:
                    continue
                portal_name = portal_cfg["name"]
                jid = queue.pop(0)
                r       = found_by_portal[portal_name][jid]
                title   = r.get("title", "")
                company = r.get("company", r.get("companyName", r.get("employer", r.get("hiringOrgName", ""))))
                url     = r.get("url", "")

                existing = find_existing_rating(conn, title, company, portal_name, jid)
                if existing:
                    rating, notes = existing
                    print(f"  [{portal_name}] → duplicate of an already-rated listing, copying: {title[:60]}")
                    update_fit(conn, portal_name, jid, rating,
                               f"{notes} (duplicate posting — rating copied from an earlier listing)")
                    continue

                description = fetch_detail(portal_cfg, jid)
                if len(description.strip()) < MIN_DESCRIPTION_CHARS:
                    print(f"  [{portal_name}] → empty detail fetch, skipping: {title[:60]}")
                    update_fit(conn, portal_name, jid, "No Fit",
                               "Detail fetch returned empty — listing likely removed/expired.")
                    continue
                if is_stale(description, portal_name):
                    print(f"  [{portal_name}] → stale (>48h), skipping: {title[:60]}")
                    update_fit(conn, portal_name, jid, "No Fit", "Stale listing (posted >48h ago).")
                    continue

                pending.append({"portal": portal_name, "job_id": jid, "title": title,
                                 "company": company, "url": url, "description": description})

                if _should_flush(pending):
                    eval_count, stopped_for_memory, evaluated, pending = _flush_eval_batch(conn, pending, eval_count, "main pass")
                    for j in evaluated:
                        new_jobs.append({k: j[k] for k in
                                          ("portal", "job_id", "title", "company", "url", "fit_rating", "fit_notes")})
                    if stopped_for_memory:
                        break
            if stopped_for_memory:
                break

        eval_count, stopped_for_memory = _drain_pending(
            conn, pending, eval_count, stopped_for_memory, "main pass (final partial batch)", collect_into=new_jobs)

        if eval_count >= MAX_EVALUATIONS:
            print(f"\n[limit] MAX_EVALUATIONS={MAX_EVALUATIONS} reached, remaining listings stay unevaluated until next run")

    if populate_only:
        total_cache = cache_size(conn)
        conn.close()
        print(f"\n=== Done: {total_new} jobs added to cache (no evaluation). Cache size: {total_cache} ===")
        print("Run without --populate-cache tomorrow for the first live scan.")
        _write_state(phase="done")
        return

    _finish_run(conn, "scan", len(new_jobs), stopped_for_memory)


if __name__ == "__main__":
    main()
