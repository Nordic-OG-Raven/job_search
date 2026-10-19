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
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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

# shutil.which() first so this works out of the box on any machine where it's
# on PATH; falls back to this machine's known install location only if not.
CLAUDE_BIN = shutil.which("claude") or "/opt/homebrew/bin/claude"
# All bun invocations go through BUN_GUARD (bun_guarded.py), which resolves
# its own bun path — there's no direct bun call in this file.
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

# ============================================================
#  RUN HEALTH — surface a degraded/incomplete run loudly
# ============================================================
# Anything that made this run less than a clean, complete pass gets recorded
# here and printed as a prominent banner at the end (and summarised into the
# digest), so a run that "finished" but silently skipped portals, hit the eval
# cap, got throttled for memory, or dropped jobs is never mistaken for a full
# healthy scan. Counters are plain ints/lists; _flag_issue() records a
# human-readable headline problem.
RUN_STATS: dict = {
    "prefiltered": 0,       # jobs dropped by the cheap title pre-filter (no spawn spent)
    "empty_detail": 0,      # detail fetch came back empty (listing removed/expired)
    "stale": 0,             # listing older than the freshness cutoff
    "eval_failed": 0,       # claude --print returned an error / Unknown
    "mem_killed_spawns": 0, # claude --print killed by the per-spawn memory watchdog
    "portals_zero": [],     # portals that returned zero listings this run
    "portals_error": [],    # portals whose CLI errored at least once
    "memory_paused": False, # run stopped early under memory pressure
    "cap_hit": False,       # MAX_EVALUATIONS reached (listings left unevaluated)
    "cap_reduced_to": None, # MAX_EVALUATIONS auto-lowered at launch for low RAM
    "issues": [],           # free-text headline problems
}


def _flag_issue(msg: str) -> None:
    """Record a headline problem to surface in the end-of-run health banner."""
    RUN_STATS["issues"].append(msg)
    print(f"  [ISSUE] {msg}", file=sys.stderr)


def _run_health_problems() -> list[str]:
    """The list of things that made this run less than a clean full pass
    (empty if none). Shared by the console banner and the digest note."""
    s = RUN_STATS
    problems: list[str] = list(s["issues"])
    if s["cap_reduced_to"] is not None:
        problems.append(f"eval cap auto-reduced to {s['cap_reduced_to']} (low RAM at launch)")
    if s["cap_hit"]:
        problems.append("MAX_EVALUATIONS reached — some listings left unevaluated (run --redo-unknown)")
    if s["memory_paused"]:
        problems.append("run paused under memory pressure before finishing (run --redo-unknown)")
    if s["portals_zero"]:
        problems.append(f"portals returning ZERO listings: {', '.join(s['portals_zero'])}")
    if s["portals_error"]:
        problems.append(f"portals with CLI errors: {', '.join(s['portals_error'])}")
    if s["mem_killed_spawns"]:
        problems.append(f"{s['mem_killed_spawns']} evaluation spawn(s) killed by memory watchdog")
    if s["eval_failed"]:
        problems.append(f"{s['eval_failed']} evaluation(s) failed/Unknown")
    return problems


def _run_health_counts() -> str:
    s = RUN_STATS
    return (f"pre-filtered={s['prefiltered']} empty-detail={s['empty_detail']} "
            f"stale={s['stale']}")


def _print_run_health() -> None:
    """
    Print a clear banner describing whether this run was clean or degraded.
    Always prints something — a clean run says so explicitly, so the absence of
    a warning is itself a positive signal rather than just missing output.
    """
    problems = _run_health_problems()
    counts = _run_health_counts()
    if not problems:
        print(f"\n✅ RUN HEALTH: clean — no issues detected. ({counts})")
        return
    print("\n" + "=" * 60)
    print("⚠️  RUN HEALTH: this run was DEGRADED / incomplete:")
    for p in problems:
        print(f"   • {p}")
    print(f"   ({counts})")
    print("=" * 60)

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
            ["search", "--query", "business development analyst", "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "implementation engineer", "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
            ["search", "--query", "forward deployed data engineer", "--jobage", JOBINDEX_JOBAGE, "--sort", "date", "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobnet",
        "cli":  ".claude/skills/jobnet-search/cli/src/cli.ts",
        "id_field": "jobAdId",
        "searches": [
            # --per-page 50: jobnet's --since is ignored server-side (always returns
            # the newest N regardless of date), so the only freshness gate is the
            # post-fetch MAX_AGE_HOURS cutoff. At --per-page 10 that discarded nearly
            # everything (jobnet surfaced ~1 job/day); 50 gives the cutoff enough
            # newest-first results to actually catch all recent postings. Verified
            # ~183 KB JSON parses fine at 50 — no truncation.
            ["search", "--search-string", "data engineer",         "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "analytics engineer",    "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "data analyst",          "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "data scientist",        "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "data consultant",       "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "BI developer",          "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "BI consultant",         "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "Power BI developer",    "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "business intelligence", "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "AI developer",         "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "AI engineer",          "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "ML engineer",           "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "business development analyst", "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "implementation engineer", "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
            ["search", "--search-string", "forward deployed data engineer", "--since", SINCE_DATE, "--per-page", "50", "--format", "json"],
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
            ["search", "--key", "business development analyst", "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "implementation engineer", "--location", "8", "--work-area", "43", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--key", "forward deployed data engineer", "--location", "8", "--limit", _WIDE_LIMIT, "--format", "json"],
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
            ["search", "--text", "business development analyst", "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "implementation engineer", "--since", SINCE_DATE, "--format", "json"],
            ["search", "--text", "forward deployed data engineer", "--since", SINCE_DATE, "--format", "json"],
        ],
        "detail": lambda jid: ["detail", jid, "--format", "plain"],
    },
    {
        "name": "jobfinder-lu",
        "enabled": False,
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
            ["search", "--query", "business development analyst", "--since", SINCE_DATE, "--format", "json"],
            ["search", "--query", "implementation engineer", "--since", SINCE_DATE, "--format", "json"],
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
        "enabled": False,
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
            ["search", "--term", "business development analyst", "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "implementation engineer", "--region", "central-switzerland", "--limit", _WIDE_LIMIT, "--format", "json"],
            # Zürich (no canton filter available on jobs.ch; include city in term)
            ["search", "--term", "data engineer zürich",         "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "analytics engineer zürich",    "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "data analyst zürich",          "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "data scientist zürich",        "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "business intelligence zürich", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "business development analyst zürich", "--limit", _WIDE_LIMIT, "--format", "json"],
            ["search", "--term", "implementation engineer zürich", "--limit", _WIDE_LIMIT, "--format", "json"],
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
_DISABLED_PORTAL_NAMES = {cfg["name"] for cfg in PORTALS if not cfg.get("enabled", True)}
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
        # Distinguish "not a real portal name" from "real but disabled" —
        # checking only the post-filter PORTALS here would misreport a
        # disabled-but-valid name (e.g. workforce-au) as a typo.
        _disabled_hit = _unknown & _DISABLED_PORTAL_NAMES
        _truly_unknown = _unknown - _DISABLED_PORTAL_NAMES
        if _truly_unknown:
            print(f"[ERROR] unknown --portal value(s): {', '.join(sorted(_truly_unknown))}", file=sys.stderr)
        if _disabled_hit:
            print(f"[ERROR] disabled --portal value(s): {', '.join(sorted(_disabled_hit))} "
                  f"(configured but currently disabled — see \"enabled\": False in PORTALS)", file=sys.stderr)
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
#
# NOTE on "reuse one long-lived process": the real fix for the per-spawn 400MB
# would be a single persistent model process fed many prompts. The `claude
# --print` CLI is one-shot by design (it exits after one prompt), and the only
# persistent-process alternative is the Agent SDK / HTTP API — which would move
# this off the Claude Code subscription auth onto metered API billing. So the
# in-CLI equivalent is to maximise jobs-per-spawn: at 10, a 150-job run makes
# ~15 spawns instead of ~30, halving the cumulative memory churn. Haiku's
# context has ample headroom for 10 × MAX_DESCRIPTION_CHARS. Kept at 10 rather
# than higher because very large batches make the model more likely to mis-number
# or drop a job's block (those fall through to Unknown and get redone next run,
# but that wastes the spawn) — 10 is the reliability/efficiency sweet spot.
EVAL_BATCH_SIZE = 10
# The batch ceiling used whenever memory isn't critical (see _adaptive_batch_size):
# amortises the fixed ~400MB spawn cost across more jobs so a run makes fewer
# spawns. Capped below a size where the model starts mis-numbering or dropping
# job blocks (those fall through to Unknown and get redone, wasting the spawn).
EVAL_BATCH_SIZE_MAX = 15

# A job whose detail-fetch came back empty or near-empty (removed listing,
# dead job_id, portal CLI error) must never enter a batch: caught via a real
# production run where one such job made claude refuse to rate the entire
# batch of 5, since it had nothing to evaluate for that one job and wouldn't
# guess. Filter these out before they can spoil otherwise-good jobs sharing
# their batch.
MIN_DESCRIPTION_CHARS = 30

# How much of a job description actually reaches the model. Confirmed on a
# real production posting (Terma, 8,908 chars): a 3000-char limit cut the
# description off BEFORE its stated "3-6 years experience" requirement
# (which sat at char 3948), so the model never saw the one line that should
# have disqualified it — it wasn't a bad judgment call, it was missing
# information. Detailed corporate postings routinely run well past 3000
# chars (company intro + role + responsibilities before the requirements
# section even starts), and Haiku's context window has enormous headroom
# even for a batch of 5 at this size — there was never a real reason for the
# limit to be this tight. Raised with margin over the real case that broke it.
MAX_DESCRIPTION_CHARS = 8000

# Per-spawn RAM ceiling for a single `claude --print` evaluation. One spawn is
# normally ~400MB; a batch rarely tops ~800MB. 1800MB leaves generous room for a
# legitimately large batch while still killing a genuinely runaway spawn long
# before it can drag the whole machine into swap. A killed spawn's jobs fall
# through to Unknown and are picked up by the next --redo-unknown pass.
CLAUDE_SPAWN_MEM_CEILING_MB = 1800

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

{candidate_profile}

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

# Fingerprint of the exact evaluation logic (candidate profile + prompt
# templates) a rating was produced under. A "duplicate posting" cache-copy
# (find_existing_rating) must only pull ratings stamped with the CURRENT
# version — otherwise a bug fix or profile edit (e.g. tightening the
# incomplete-description rule) never reaches postings whose rating was
# already cached under the old, buggier logic, since the copy path skips
# re-evaluation entirely. Confirmed on real data: a "Product Owner &
# Analytics Engineer" posting was rated Strong Fit on 2026-07-06 — before
# the incomplete-description safeguard existed — then silently copied
# forward via the duplicate-match path on 2026-08-27 without ever being
# re-evaluated, even though the underlying prompt had since been fixed.
# Any change to CANDIDATE_PROFILE or these templates changes this hash,
# which makes every previously-cached rating ineligible for copying until
# it's been re-evaluated under the new logic at least once.
EVAL_VERSION = hashlib.sha256(
    (CANDIDATE_PROFILE + FIT_PROMPT_BATCH_TEMPLATE + FIT_PROMPT_JOB_BLOCK).encode("utf-8")
).hexdigest()[:12]

# ============================================================
#  CHEAP PRE-FILTER (title-only; no model spawn)
# ============================================================
# Most scraped listings are obvious non-fits by title alone (kitchen assistant,
# pædagog, svejser, Senior/Head-of roles). Dropping those here — before a
# detail-fetch AND before a ~400MB claude --print spawn — is the single biggest
# lever on how much memory work a run does.
#
# DELIBERATELY HIGH-PRECISION. A wrong exclusion hides a real job (costly); a
# missed exclusion just wastes one spawn (cheap). So: (1) every pre-filtered job
# is still recorded as No Fit and listed in the digest's Excluded section —
# nothing vanishes silently; (2) any data/BI/AI/engineering term ANYWHERE in the
# title cancels the profession filter (a "Data Analyst, Lager & Logistik" is
# never dropped for containing "lager"); (3) the profession list is specific
# role-nouns, not broad stems. "Intern"/"Trainee"/"Student" are intentionally
# NOT pre-filtered — graduate-open internships are in scope (e.g. the Kamstrup
# Data Analyst Intern), so those nuanced cases are left to the model.
_PREFILTER_RESCUE_RE = re.compile(
    r"\b(data|analytics?|analyse|analytiker|business intelligence|bi|power\s?bi|"
    r"machine learning|ml|ai|artificial intelligence|developer|udvikler|engineer|"
    r"scientist|software|python|sql|etl|pipeline|consultant|konsulent|rapportering)\b",
    re.IGNORECASE,
)
_PREFILTER_PROFESSION_RE = re.compile(
    r"\b("
    r"sygeplejerske|sosu|social[- ]?og[- ]?sundhed|pædagog\w*|lærer\w*|underviser|"
    r"lektor|adjunkt|professor|postdoc|ph\.?d\.?[- ]?(?:stipendiat|studerende|scholarship)|"
    r"kok|køkken\w*|tjener|kantine|bartender|barista|svejser|smed|tømrer|snedker|murer|"
    r"maler|elektriker|vvs|mekaniker|montør|chauffør\w*|lastbil\w*|lagermedarbejder|"
    r"warehouse (?:operative|worker|assistant)|rengøring\w*|cleaner|housekeeper|stuepige|"
    r"frisør|kosmetolog|pedel|ejendomsservice|dyrlæge|veterinarian|farmaceut|farmakonom|"
    r"jordemoder|fysioterapeut|ergoterapeut|tandlæge|tandplejer|læge|overlæge|reservelæge|"
    r"sygehjælper|portør|auktionsmægler|ejendomsmægler|dredger|kabinepersonale|flyttemand|"
    r"kitchen (?:assistant|porter)|chef de partie"
    r")\b",
    re.IGNORECASE,
)
_PREFILTER_SENIORITY_RE = re.compile(
    r"^\s*(senior|sr\.?|lead|principal|head of|chief|vp|director|direktør|"
    r"afdelingsleder|afdelingschef)\b",
    re.IGNORECASE,
)


def _prefilter_rating(title: str) -> tuple[str, str] | None:
    """Return ('No Fit', reason) if the title is an unambiguous non-fit that
    needn't cost a detail-fetch + claude spawn, else None. See notes above."""
    t = (title or "").strip()
    if not t:
        return None
    m = _PREFILTER_SENIORITY_RE.match(t)
    if m:
        return ("No Fit",
                f"Pre-filtered: senior-tier title ('{m.group(1)}') — candidate is junior (hard-no).")
    m = _PREFILTER_PROFESSION_RE.search(t)
    if m and not _PREFILTER_RESCUE_RE.search(t):
        return ("No Fit",
                f"Pre-filtered: non-data profession ('{m.group(1)}'), no data/BI/AI term in title.")
    return None


# #6 cheap relevance pre-score: order the evaluation queue best-first so that
# whatever gets evaluated in a partial/early window is the MOST relevant subset,
# not a round-robin that spends the first spawns on "Team Lead for Support". It
# is ordering ONLY — never a drop. Dropping on title alone is unsafe (a real fit
# may not spell a keyword in its title), and loop-to-completion (#3) evaluates
# everything regardless, so ordering captures the benefit with none of the
# false-negative risk.
_RELEVANCE_TERMS = re.compile(
    r"\b(data|analytics?|analyse|analytik\w*|business intelligence|bi|power\s?bi|"
    r"machine learning|ml|ai|artificial intelligence|scientist|engineer|udvikler|"
    r"developer|software|sql|etl|elt|pipeline|warehouse|lakehouse|fabric|azure|"
    r"databricks|snowflake|dbt|bigquery|automation|automatiser\w*|llm|rag|agent\w*|"
    r"mcp|consultant|konsulent|rapporter\w*|dashboard|visualis\w*|forecast\w*|"
    r"python|model\w*|integration)\b",
    re.IGNORECASE,
)


def _relevance_score(title: str, company: str = "") -> int:
    """Number of distinct domain terms the title hits. The cheap, dependency-free
    fallback ranker, and the tiebreaker within equal Groq scores below."""
    return len({m.group(0).lower() for m in _RELEVANCE_TERMS.finditer(title or "")})


# --- #6 upgrade: optional Groq semantic relevance ranking ---------------------
# With a Groq API key available, rank titles with a cheap, fast Llama call rather
# than the keyword count above — a far better sort signal (it understands that
# "Forretningsudvikler der elsker tal" is data-adjacent with no keyword match).
# Still ORDERING ONLY, never a drop. Fail-safe by construction: no key, a bad
# model name, or any network/parse error silently falls back to the keyword
# score, so the open-source default (no key set) and offline runs behave exactly
# as before. No new pip dependency — this uses stdlib urllib against Groq's
# OpenAI-compatible endpoint.
def _load_groq_key() -> str:
    k = os.environ.get("GROQ_API_KEY", "").strip()
    if k:
        return k
    # launchd runs this with a minimal env, so also accept the key from a local,
    # git-ignored file. Two forms:
    #   - .env           : a line  GROQ_API_KEY=gsk_...   (standard dotenv)
    #   - .groq_api_key  : just the raw key on its own line
    for p in (BASE_DIR / ".env", SCRIPTS / ".env"):
        try:
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if line.startswith("GROQ_API_KEY") and "=" in line:
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        except Exception:
            pass
    for p in (SCRIPTS / ".groq_api_key", BASE_DIR / ".groq_api_key"):
        try:
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


GROQ_API_KEY    = _load_groq_key()
# gpt-oss-120b gives clean, well-graded 0-10 scores on this task; the smaller
# gpt-oss-20b returned unparseable output in testing. Override via
# GROQ_RELEVANCE_MODEL if your account exposes different models (list them with
# GET https://api.groq.com/openai/v1/models).
GROQ_MODEL      = os.environ.get("GROQ_RELEVANCE_MODEL", "openai/gpt-oss-120b")
GROQ_RANK_BATCH = 40  # titles per Groq call

# Profile + rubric tuned via scripts/../scratchpad prompt-engineering tests
# (variant "C_graded" won on a labeled set: 1 mismatch vs 2-3 for alternatives).
# The graded 0-3 / 4-7 / 8-10 banding is deliberate: the middle band is where
# genuinely title-ambiguous roles belong (a generic "Business Analyst", or an
# "Intern"/"Student" data role whose title doesn't reveal whether it needs
# current student enrolment) — scoring those ~5 keeps them mid-queue rather than
# buried at 0 or falsely boosted to 10, and the full claude --print evaluation
# (which DOES read the description) then resolves the real fit.
# Generic default — intentionally carries NO user specifics, since this file is a
# public, shared script. Personalise it by putting a single line in your
# (git-ignored) candidate_profile.txt:  RELEVANCE_PROFILE: <one-line description>
# — if present it is used verbatim; otherwise this generic data-roles framing is.
_DEFAULT_RELEVANCE_PROFILE = (
    "A candidate targeting data roles. Fit = roles whose CORE work is data engineering, "
    "BI, analytics, data analyst/scientist, AI/ML/LLM, automation, or software for data "
    "(Python/SQL/cloud). Judge by the core function, not the department or team name."
)


def _load_relevance_profile() -> str:
    try:
        for line in CANDIDATE_PROFILE.splitlines():
            if line.strip().upper().startswith("RELEVANCE_PROFILE:"):
                v = line.split(":", 1)[1].strip()
                if v:
                    return v
    except Exception:
        pass
    return _DEFAULT_RELEVANCE_PROFILE


_RELEVANCE_PROFILE = _load_relevance_profile()

_GROQ_RANK_PROMPT = """\
You rank job-posting titles by fit for ONE candidate. Candidate: {profile}

Score each title 0-10:
- 8-10: core data/BI/AI/analytics/data-engineering role, INCLUDING junior/graduate level.
- 4-7: genuinely AMBIGUOUS from the title alone — reserve this for cases you cannot resolve \
without the full job description, e.g. a generic "Business Analyst", or an "Intern"/"Student" \
data role where the title does not reveal whether it requires current student enrolment.
- 0-3: clearly a different field (healthcare, teaching, trades, kitchen, logistics, pure \
sales/marketing/HR/accounting), OR a senior/lead/head/principal/director title.
Examples: "Data Engineer" -> 9; "Senior Data Analyst" -> 2; "Data Analyst Intern" -> 5; \
"Business Analyst" -> 5; "Sygeplejerske" -> 0; "Studentermedhjælper, data" -> 4.

For each numbered title below, output exactly one line "N: S". Output ONLY those lines.

{titles}"""


def _groq_chat(prompt: str, timeout: int = 30) -> str:
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 1200,
    }
    # gpt-oss models emit hidden reasoning tokens that otherwise ~double the
    # output cost (and can crowd out the answer at a full 40-title batch).
    # 'low' keeps scoring quality while cutting completion tokens ~40%. Guarded
    # to gpt-oss so a non-reasoning model override doesn't get rejected.
    if "gpt-oss" in GROQ_MODEL:
        payload["reasoning_effort"] = "low"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        # A non-default User-Agent is REQUIRED: Groq sits behind Cloudflare, which
        # blocks the stock "Python-urllib/*" UA with a 403 (error 1010).
        headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "morning-scan-relevance/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _groq_relevance_scores(titles: list[str]) -> list[int] | None:
    """0-10 relevance score per title via Groq, batched GROQ_RANK_BATCH at a time.
    Per-chunk fallback to the keyword score on any error, so one failed chunk
    never loses the rest. Returns None only if Groq produced nothing for every
    chunk (caller then uses the pure keyword path)."""
    scores: list[int | None] = [None] * len(titles)
    used_groq = False
    for start in range(0, len(titles), GROQ_RANK_BATCH):
        chunk = titles[start:start + GROQ_RANK_BATCH]
        numbered = "\n".join(f"{i + 1}. {(t or '')[:160]}" for i, t in enumerate(chunk))
        out = None
        for attempt in range(2):  # one retry rides out a transient Groq hiccup
            try:
                out = _groq_chat(_GROQ_RANK_PROMPT.format(profile=_RELEVANCE_PROFILE, titles=numbered))
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                print(f"  [relevance] Groq chunk failed ({e}); keyword fallback for "
                      f"{len(chunk)} titles", file=sys.stderr)
        if out is None:
            for i in range(len(chunk)):
                scores[start + i] = min(10, _relevance_score(chunk[i]))
            continue
        parsed: dict[int, int] = {}
        for line in out.splitlines():
            m = re.match(r"\s*(\d+)\s*[:.\)]\s*(\d+)", line)
            if m:
                parsed[int(m.group(1))] = max(0, min(10, int(m.group(2))))
        for i in range(len(chunk)):
            scores[start + i] = parsed.get(i + 1, min(10, _relevance_score(chunk[i])))
        used_groq = used_groq or bool(parsed)
    return scores if used_groq else None  # type: ignore[return-value]


def _relevance_scores_for(titles: list[str]) -> list[float]:
    """Relevance score per title for ordering the eval queue best-first.
    Prefers Groq semantic ranking when a key is configured; otherwise, or on a
    total Groq failure, uses the keyword count. Ordering only, never drops."""
    if GROQ_API_KEY and titles:
        g = _groq_relevance_scores(titles)
        if g is not None:
            # scale Groq (0-10) above the keyword count, with the keyword as a
            # small stable tiebreaker inside equal Groq scores
            return [g[i] * 10 + _relevance_score(titles[i]) for i in range(len(titles))]
    return [float(_relevance_score(t)) for t in titles]

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
            eval_version TEXT,
            status       TEXT DEFAULT 'new',
            PRIMARY KEY (portal, job_id)
        )
    """)
    # Additive migration for pre-existing local DBs (this repo is open-source;
    # other users' seen_jobs.db predates this column). CREATE TABLE above only
    # applies to a brand-new DB, so anyone with an existing file needs this
    # ALTER TABLE to actually get the column added.
    try:
        conn.execute("ALTER TABLE seen_jobs ADD COLUMN eval_version TEXT")
    except sqlite3.OperationalError:
        pass  # column already present
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
               rating: str, notes: str, eval_version: str = EVAL_VERSION) -> None:
    conn.execute(
        "UPDATE seen_jobs SET fit_rating=?, fit_notes=?, eval_version=? WHERE portal=? AND job_id=?",
        (rating, notes, eval_version, portal, str(job_id))
    )
    conn.commit()


# workforce-au's own CLI passes through a literal placeholder string when it
# can't resolve the real employer — confirmed on real fetched postings, every
# one printed "Employer: CareerOne ORG" or "Employer: Adzuna ORG" verbatim.
# These are NOT company names; matching on them produces real false positives
# (confirmed on the live DB: "Data Engineer" @ "Adzuna ORG" alone covers 9
# genuinely different postings). Excluded outright from duplicate-matching.
#
# Known residual risk, not fixed here: a real staffing agency that legitimately
# reposts many distinct client roles under its own company name (e.g. jobs-ch's
# "Evergreen Human Resources AG") looks structurally identical to a genuine
# repost and isn't caught by this exclusion — title+company alone can't tell
# the two apart without also comparing description text, which this function
# doesn't have access to. Rare enough in practice not to block on right now,
# but worth knowing if a wrong-looking copied rating shows up from that portal.
_DUPLICATE_MATCH_EXCLUDED_COMPANIES = {"Adzuna ORG", "CareerOne ORG"}


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

    Only matches ratings stamped with the CURRENT EVAL_VERSION. Confirmed on
    real data: a posting rated Strong Fit on 2026-07-06 (before the
    incomplete-description safeguard existed in the prompt) was still being
    silently copied forward on 2026-08-27, weeks after that prompt bug was
    fixed, because the copy path never re-checked the rating against the
    newer logic. Gating on version means a stale rating just falls through
    to a real re-evaluation next time it's encountered, instead of
    propagating a decision made under outdated logic indefinitely.
    """
    if company in _DUPLICATE_MATCH_EXCLUDED_COMPANIES:
        return None
    row = conn.execute(
        "SELECT fit_rating, fit_notes FROM seen_jobs "
        "WHERE title = ? AND company = ? AND fit_rating NOT IN ('', 'Unknown') "
        "AND fit_rating IS NOT NULL AND eval_version = ? "
        "AND NOT (portal = ? AND job_id = ?) "
        "LIMIT 1",
        (title, company, EVAL_VERSION, exclude_portal, str(exclude_job_id)),
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


class SpawnMemoryKilled(Exception):
    """Raised when a child spawn was killed for exceeding its RAM ceiling."""


def _pgroup_rss_mb(pid: int) -> float:
    """Total resident memory (MB) of a process group — the spawned process plus
    every descendant (claude is Node and forks children). Best-effort; returns
    0.0 if it can't be read so the watchdog never kills on a bad reading."""
    try:
        pgid = os.getpgid(pid)
        out = subprocess.run(["ps", "-o", "pgid=,rss=", "-A"],
                             capture_output=True, text=True, timeout=5).stdout
        total_kb = 0
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit() and int(parts[0]) == pgid:
                total_kb += int(parts[1])
        return total_kb / 1024.0
    except Exception:
        return 0.0


def _run_with_group_kill(cmd: list[str], *, input: str | None = None,
                          cwd: str | None = None, timeout: int = 60,
                          mem_ceiling_mb: float | None = None,
                          stdout_to_file: bool = False) -> subprocess.CompletedProcess:
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

    If mem_ceiling_mb is set, a lightweight watchdog thread polls the whole
    process group's RSS every few seconds and kills it the moment it exceeds
    the ceiling, raising SpawnMemoryKilled — a bounded blast radius for a
    single runaway spawn, so one bad evaluation can't balloon the machine.

    stdout_to_file routes the child's stdout to a real temp file instead of a
    pipe. This is REQUIRED for the Node portal CLIs: Node's process.stdout to a
    PIPE is async and only the ~64KB pipe buffer is guaranteed flushed before
    the process exits, so a large JSON payload (jobnet emits ~183KB) is
    silently truncated to exactly 65536 bytes — which then fails json.loads and
    forced the lossy salvage path, capping jobnet to a handful of jobs no matter
    the --per-page. Writing to a file fd is synchronous, so the full payload
    always lands. (Confirmed 2026-10-19: same command → 65536 B via pipe vs
    183991 B via file.)
    """
    out_f = None
    out_path = None
    if stdout_to_file:
        fd, out_path = tempfile.mkstemp(suffix=".out", prefix="portal_", dir=str(SCRIPTS))
        out_f = os.fdopen(fd, "w")

    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=(out_f if stdout_to_file else subprocess.PIPE),
        stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )

    stop_watch = threading.Event()
    mem_killed = {"hit": False}
    if mem_ceiling_mb:
        def _watch() -> None:
            # Poll until the process exits or blows the ceiling. stop_watch is
            # set in the finally below, so this thread never outlives the call.
            while not stop_watch.wait(3.0):
                if _pgroup_rss_mb(proc.pid) > mem_ceiling_mb:
                    mem_killed["hit"] = True
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    return
        threading.Thread(target=_watch, daemon=True).start()

    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # process group already gone
        proc.communicate()  # reap the killed process, avoid a zombie
        if out_f is not None:
            out_f.close()
            try: os.unlink(out_path)
            except OSError: pass
        raise
    finally:
        stop_watch.set()

    if out_f is not None:
        out_f.close()
        try:
            stdout = Path(out_path).read_text(encoding="utf-8", errors="replace")
        finally:
            try: os.unlink(out_path)
            except OSError: pass

    if mem_killed["hit"]:
        raise SpawnMemoryKilled(
            f"spawn exceeded {mem_ceiling_mb:.0f}MB RSS ceiling — killed to protect the machine")
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


# Swap kept only as a hard safety backstop. The danger that can actually
# destabilise the machine is running out of *physical RAM* with no room left to
# page — which is captured by free swap in absolute MB, NOT by swap-used/total%.
# Confirmed 2026-10-19: swap sat at 95% (stale pages from an unrelated process,
# Docker, that had already exited) while 35% of RAM was genuinely free — the old
# swap-% gate aborted a run that had ample headroom. This backstop only bites
# when free swap is genuinely tiny: >= SWAP_SAFE_FREE_MB free -> 0 badness,
# 0 MB free -> 1.0, linear between.
SWAP_SAFE_FREE_MB = 1024.0


def _swap_backstop_fraction() -> float | None:
    """Badness (0..1, higher=worse) from ABSOLUTE free swap, not swap-used%.
    ~0 under normal conditions; only climbs when free swap nears exhaustion."""
    try:
        out = subprocess.run(
            ["sysctl", "vm.swapusage"], capture_output=True, text=True, timeout=5
        ).stdout
        m = re.search(r"free = ([\d.]+)M", out)
        if not m:
            return None
        free_mb = float(m.group(1))
        if free_mb >= SWAP_SAFE_FREE_MB:
            return 0.0
        return max(0.0, 1.0 - free_mb / SWAP_SAFE_FREE_MB)
    except Exception:
        return None


def _ram_badness_fraction() -> float | None:
    """Badness (0..1, higher=worse) from genuinely-available physical RAM.
    available = free + inactive + speculative + purgeable pages (all reclaimable
    by the kernel on demand); badness = 1 - available/total. This is the PRIMARY
    memory signal — it reflects real headroom the way swap-% does not."""
    try:
        total = int(subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
        ).stdout.strip())
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        psize_m = re.search(r"page size of (\d+) bytes", out)
        psize = int(psize_m.group(1)) if psize_m else 4096
        def pages(name: str) -> int:
            m = re.search(rf"{re.escape(name)}:\s+(\d+)\.", out)
            return int(m.group(1)) if m else 0
        available = (pages("Pages free") + pages("Pages inactive")
                     + pages("Pages speculative") + pages("Pages purgeable")) * psize
        return max(0.0, 1.0 - available / total) if total > 0 else None
    except Exception:
        return None


def _kernel_pressure_badness() -> float | None:
    """macOS's OWN memory-pressure verdict, mapped onto our 0..1 badness scale,
    and the authoritative signal. The raw available/total ratio (_ram_badness_
    fraction) is far too conservative on Apple Silicon: heavy memory compression
    reads as "low free RAM" while the kernel still rates pressure normal/warn and
    the machine stays perfectly responsive (confirmed 2026-10-19 on an 8 GB Mac:
    the ratio said 0.85 'critical' while the kernel said level 2 'warn', 2.3M
    pages compressed). kern.memorystatus_vm_pressure_level: 1=normal, 2=warn,
    4=critical."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return {"1": 0.65, "2": 0.80, "4": 0.97}.get(out)
    except Exception:
        return None


def _memory_badness_fraction() -> float | None:
    """Unified memory-pressure signal (0..1, higher=worse). PRIMARY = the kernel's
    own pressure level (the macOS-native truth); the absolute-free-swap backstop
    can still escalate it on genuine swap exhaustion. Falls back to the
    available-RAM ratio only if the kernel level can't be read."""
    k = _kernel_pressure_badness()
    swap = _swap_backstop_fraction()
    if k is not None:
        return max(k, swap) if swap is not None else k
    ram = _ram_badness_fraction()
    vals = [v for v in (ram, swap) if v is not None]
    return max(vals) if vals else None


# Batch-size response to memory pressure. KEY FACT learned 2026-10-19:
# evaluations run ONE claude --print spawn at a time (sequential), and a spawn is
# ~400MB regardless of how many jobs are in its prompt — so batch size does NOT
# change PEAK memory, only how many spawn/free cycles a run does. Shrinking the
# batch under pressure therefore buys ZERO headroom and just makes the run many
# times slower (the old code dropped to batch-of-1, ~10x slower, for no memory
# benefit). So there are only two useful levers: run LARGE batches (fewer spawns
# = less churn and far faster), and fully PAUSE when even one 400MB spawn is
# unsafe. No "batch-1" middle tier — if a spawn is affordable at all, make it big.
MEM_COMFORTABLE_THRESHOLD = 0.75  # at/below: healthy -> largest batch
MEM_ELEVATED_THRESHOLD    = 0.85  # used only to lengthen the inter-spawn cooldown
MEM_CRITICAL_THRESHOLD    = 0.95  # above: even one spawn is unsafe -> pause/wait
MEM_ABORT_THRESHOLD = MEM_CRITICAL_THRESHOLD


def _adaptive_batch_size(ceiling: int) -> int:
    """Jobs per claude --print spawn right now, re-checked every flush (#5) so it
    tracks pressure appearing or clearing mid-run. Big batch unless the kernel
    says critical, in which case 0 => the caller waits (pacing #4) rather than
    shrinking to a pointless batch-of-1 that would not lower peak memory anyway."""
    frac = _memory_badness_fraction()
    if frac is None:
        return EVAL_BATCH_SIZE_MAX
    if frac >= MEM_ABORT_THRESHOLD:
        return 0                     # critical -> pause and wait
    if frac <= MEM_COMFORTABLE_THRESHOLD:
        return EVAL_BATCH_SIZE_MAX   # healthy -> biggest batch (fewest spawns)
    return ceiling                   # warn -> normal batch (same peak; no point shrinking)


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


def _memory_status_str() -> str:
    """Human-readable one-liner of the current memory signals, for logs."""
    ram = _ram_badness_fraction()
    swap_free = None
    try:
        out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True,
                             text=True, timeout=5).stdout
        m = re.search(r"free = ([\d.]+)M", out)
        swap_free = float(m.group(1)) if m else None
    except Exception:
        pass
    ram_s = f"RAM {(1 - ram) * 100:.0f}% available" if ram is not None else "RAM n/a"
    swap_s = f"swap {swap_free:.0f}MB free" if swap_free is not None else "swap n/a"
    return f"{ram_s}, {swap_s}"


def _check_memory_pressure_or_abort(context: str) -> bool:
    """
    Memory-pressure check with retry-and-backoff. Returns True if it's safe to
    continue. On sustained critical pressure — not just a momentary reading —
    logs a warning, fires a macOS notification so this is discovered the
    same day rather than by chance days later, and returns False so the
    caller can stop the run cleanly (write final state, close the DB)
    instead of continuing blind and risking exactly the kind of
    system-wide resource exhaustion that can end in a kernel panic.
    Fails open — a broken check should never itself be the reason a run
    stops. Signal is _memory_badness_fraction (available RAM primary, free-swap
    backstop), NOT raw swap-used% — see that function.
    """
    for attempt in range(MEMORY_RETRY_ATTEMPTS):
        frac = _memory_badness_fraction()
        if frac is None:
            return True
        if frac <= MEM_ABORT_THRESHOLD:
            return True
        if attempt < MEMORY_RETRY_ATTEMPTS - 1:
            print(
                f"  [WARN] memory pressure {frac:.0%} ({_memory_status_str()}) "
                f"({context}) — waiting {MEMORY_RETRY_DELAY_SECONDS}s and rechecking "
                f"({attempt + 1}/{MEMORY_RETRY_ATTEMPTS}) before giving up.",
                file=sys.stderr,
            )
            time.sleep(MEMORY_RETRY_DELAY_SECONDS)
        else:
            print(
                f"  [WARN] memory pressure still critical ({frac:.0%}, "
                f"{_memory_status_str()}) after {MEMORY_RETRY_ATTEMPTS} checks over "
                f"{MEMORY_RETRY_ATTEMPTS * MEMORY_RETRY_DELAY_SECONDS}s ({context}) "
                f"— stopping run early rather than continuing under memory "
                f"pressure. Use --redo-unknown to pick up where this left off "
                f"once memory frees up.",
                file=sys.stderr,
            )
            _flag_issue(f"run stopped early for memory pressure during {context} "
                        f"({_memory_status_str()})")
            RUN_STATS["memory_paused"] = True
            _notify(
                "Job scan paused — low memory",
                f"Stopped after {context} — {_memory_status_str()}. "
                f"Run --redo-unknown once memory frees up.",
            )
            return False
    return True


AUTO_RESUME_MAX_WAIT_SECONDS = 1800  # give memory up to 30 min to recover
AUTO_RESUME_POLL_SECONDS     = 300   # ...checking every 5 min


MAX_DRAIN_ROUNDS = 20  # backstop on #3 chained passes (20 x up to 150 evals each)


def _unevaluated_count() -> int:
    """How many listings are still waiting for a real rating (fit_rating empty,
    NULL, or 'Unknown'). Opens its own short-lived connection so it can be read
    between chained passes without holding anything open."""
    try:
        c = sqlite3.connect(DB_PATH)
        n = c.execute(
            "SELECT COUNT(*) FROM seen_jobs "
            "WHERE fit_rating IN ('Unknown', '') OR fit_rating IS NULL"
        ).fetchone()[0]
        c.close()
        return int(n)
    except Exception:
        return 0


def _drain_backlog_loop() -> None:
    """
    #3 loop-to-completion. After the top-level pass finishes — whether it stopped
    for memory pressure OR hit the per-pass MAX_EVALUATIONS ceiling — keep
    launching --redo-unknown passes until the unevaluated backlog is empty. This
    is what turns a "degraded, N left unevaluated" finish into a slower but
    COMPLETE one, with no human needed.

    (Replaced the old single-shot auto-resume, which only fired on a memory pause
    and ran exactly one follow-up pass — so an ordinary cap-hit, like the run that
    left 263 unevaluated, was never picked up automatically.)

    Each pass is a fresh process (so the ~400MB spawns are fully released between
    rounds) invoked with --no-auto-resume, so only this top-level run orchestrates
    the loop; a child never recurses. Before each round it waits, bounded, for
    memory to drop below the abort line — pacing, not thrashing. Bounded to
    MAX_DRAIN_ROUNDS as a backstop.
    """
    if "--no-auto-resume" in sys.argv:
        return  # a child drain pass — never orchestrate further

    _release_single_instance_lock()  # release so each child pass can take the lock
    for rnd in range(1, MAX_DRAIN_ROUNDS + 1):
        remaining = _unevaluated_count()
        if remaining == 0:
            print("\n[drain] backlog empty — every listing has been evaluated.")
            _write_state(phase="done")
            return

        # Pace (#4): wait, bounded, until memory is safe before launching a pass.
        waited = 0
        while True:
            frac = _memory_badness_fraction()
            if frac is None or frac <= MEM_ABORT_THRESHOLD:
                break
            if waited >= AUTO_RESUME_MAX_WAIT_SECONDS:
                print(f"\n[drain] {remaining} listing(s) still unevaluated, but memory "
                      f"stayed critical for {waited}s ({_memory_status_str()}) — stopping. "
                      f"Run `scripts/morning_scan.py --redo-unknown` once memory frees up.",
                      file=sys.stderr)
                _notify("Job scan — backlog remains",
                        f"{remaining} listing(s) unevaluated; memory critical. Run --redo-unknown later.")
                return
            print(f"  [drain] memory at {frac:.0%} ({_memory_status_str()}), waiting "
                  f"{AUTO_RESUME_POLL_SECONDS}s before the next pass ({remaining} left)...",
                  file=sys.stderr)
            time.sleep(AUTO_RESUME_POLL_SECONDS)
            waited += AUTO_RESUME_POLL_SECONDS

        print(f"\n[drain] round {rnd}/{MAX_DRAIN_ROUNDS}: {remaining} unevaluated remain "
              f"— launching a --redo-unknown pass...", file=sys.stderr)
        try:
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--redo-unknown", "--no-auto-resume"],
                cwd=str(BASE_DIR),
            )
        except Exception as e:
            print(f"[drain] follow-up pass failed to launch: {e} — stopping loop.", file=sys.stderr)
            return

        # No-progress guard: if a pass resolved nothing, retrying won't help —
        # stop rather than spin out the remaining rounds (what the disabled-portal
        # jobs did before they were marked terminal).
        if _unevaluated_count() >= remaining:
            print(f"\n[drain] last pass resolved nothing ({remaining} still unevaluated) — "
                  f"stopping rather than spinning. Inspect those rows if unexpected.",
                  file=sys.stderr)
            _write_state(phase="done")
            return

    print(f"\n[drain] reached MAX_DRAIN_ROUNDS={MAX_DRAIN_ROUNDS}; "
          f"{_unevaluated_count()} may still remain — run --redo-unknown to finish.",
          file=sys.stderr)


def run_cli(portal_cfg: dict, args: list[str]) -> list[dict]:
    """Run a portal CLI command and return the results list, or [] on error."""
    cmd = [sys.executable, BUN_GUARD, portal_cfg["cli"]] + args
    try:
        result = _run_with_group_kill(cmd, cwd=str(BASE_DIR), timeout=60, stdout_to_file=True)
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
            else:
                # Must not stay silent here — a genuine parse failure with no
                # salvageable results looks identical to "0 new listings" if
                # nothing is logged, and a real portal-CLI failure gets
                # mistaken for an unusually quiet day.
                print(f"  [WARN] {portal_cfg['name']}: could not parse CLI output as JSON "
                      f"and salvage found nothing — stdout[:200]={result.stdout[:200]!r}", file=sys.stderr)
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
    #
    # Known imprecision, not fixed: jobindex's own --jobage filter only accepts
    # discrete steps (1/7/14/30/9999 days — see JOBINDEX_JOBAGE), which doesn't
    # line up with MAX_AGE_HOURS scaling continuously with --since-days, so a
    # run with an in-between window (e.g. --since-days 5) can let listings up
    # to ~2 days past the intended cutoff through unchecked. Similarly, jobnet
    # searches hardcode --per-page 10 regardless of the search window's width
    # (see the jobnet entries in PORTALS below), so a wide --since-days run can
    # silently truncate jobnet coverage for high-volume terms without any
    # warning, since being "trusted" here means it's never flagged as
    # incomplete. Both are accepted simplifications of relying on server-side
    # filtering rather than newly introduced bugs — revisit if either portal's
    # results start looking incomplete on wide catch-up runs.
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
        result = _run_with_group_kill(cmd, cwd=str(BASE_DIR), timeout=60, stdout_to_file=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""

# ============================================================
#  FIT EVALUATION
# ============================================================

def _parse_fit_block(block_text: str) -> tuple[str, str]:
    rating, notes = "Unknown", (block_text.strip()[:200] or "No response for this job.")
    unrecognized_raw = None
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
                # An unrecognized rating string must never become the bucket
                # key itself — write_digest() only ever prints the 5 known
                # buckets, so anything else would silently vanish from every
                # section of the digest while still counting as "evaluated".
                rating = "Unknown"
                unrecognized_raw = raw
        elif line.startswith("REASON:"):
            notes = line.split(":", 1)[1].strip()
    if unrecognized_raw is not None:
        # Keep the raw rating text visible rather than losing it — append
        # rather than overwrite so a real REASON line (processed after
        # RATING in the loop above) isn't clobbered by this diagnostic.
        notes = f"{notes} [unrecognized rating from model: {unrecognized_raw!r}]"
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
            portal=j["portal"], description=safe(j["description"][:MAX_DESCRIPTION_CHARS]),
        )
        for n, j in enumerate(evaluable_jobs, 1)
    )
    prompt = FIT_PROMPT_BATCH_TEMPLATE.format(
        n=len(evaluable_jobs), candidate_profile=CANDIDATE_PROFILE, jobs=job_blocks)

    try:
        result = _run_with_group_kill(
            [CLAUDE_BIN, "--print", "--output-format", "text",
             "--model", "claude-haiku-4-5-20251001"],
            input=prompt,
            timeout=40 + 20 * len(evaluable_jobs),
            cwd=str(BASE_DIR),
            mem_ceiling_mb=CLAUDE_SPAWN_MEM_CEILING_MB,
        )
    except SpawnMemoryKilled as e:
        RUN_STATS["mem_killed_spawns"] += 1
        RUN_STATS["eval_failed"] += len(evaluable_idx)
        print(f"  [WARN] claude --print (batch of {len(evaluable_jobs)}) {e}", file=sys.stderr)
        for i in evaluable_idx:
            results[i] = ("Unknown", "Evaluation spawn killed by memory watchdog.")
        return results
    except Exception as e:
        RUN_STATS["eval_failed"] += len(evaluable_idx)
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

    health_problems = _run_health_problems()
    if health_problems:
        lines.append("> ⚠️ **Run health: DEGRADED / incomplete** — this digest may "
                     "not reflect a full scan:")
        for p in health_problems:
            lines.append(f"> - {p}")
        lines.append("")

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
    target = _adaptive_batch_size(EVAL_BATCH_SIZE)
    # target > EVAL_BATCH_SIZE when RAM is plentiful (#7) -> wait to accumulate a
    # bigger batch; target < EVAL_BATCH_SIZE under pressure -> flush now small.
    if len(pending) >= target:
        return True
    return target < EVAL_BATCH_SIZE


def _flush_eval_batch(
    conn: sqlite3.Connection,
    pending: list[dict],
    eval_count: int,
    context: str,
) -> tuple[int, bool, list[dict], list[dict]]:
    """
    Evaluate as much of `pending` as is currently safe — up to
    _adaptive_batch_size(), which shrinks as memory pressure rises instead of
    the pipeline just refusing to proceed. Only when even a single evaluation
    is unsafe (memory at/above MEM_CRITICAL_THRESHOLD, sustained through
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
    # #5 pace: a longer cooldown under pressure gives the OS time to reclaim the
    # ~400MB this spawn just released before the next one starts, so a tight run
    # settles rather than ratchets upward.
    _frac = _memory_badness_fraction() or 0.0
    time.sleep(3.0 if _frac > MEM_ELEVATED_THRESHOLD else
               1.0 if _frac > MEM_COMFORTABLE_THRESHOLD else 0.5)
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


FETCH_WORKERS = 3  # matches bun_guarded.py's flock SLOTS; detail fetches are tiny
                   # node subprocesses, safe to run concurrently (unlike the 400MB
                   # claude spawns, which stay strictly sequential)


def _fetch_details_parallel(jobs: list[dict]) -> dict[str, str]:
    """Fetch full descriptions for several jobs CONCURRENTLY. Detail fetches are
    independent ~1.4s node subprocesses; running them one-at-a-time was ~19% of a
    full run's wall-clock for zero reason. bun_guarded.py already caps real
    concurrency at its flock SLOTS, so FETCH_WORKERS matches that. Returns
    {job_id: description} ('' on any failure). Keyed by job_id — callers must not
    mix two jobs with the same id in one window (they never do: a window is a
    slice of a deduplicated candidate list)."""
    out: dict[str, str] = {}
    if not jobs:
        return out
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = {ex.submit(fetch_detail, j["portal_cfg"], j["job_id"]): j["job_id"] for j in jobs}
        for fut, jid in futs.items():
            try:
                out[jid] = fut.result()
            except Exception:
                out[jid] = ""
    return out


def _evaluate_candidates(conn: sqlite3.Connection, candidates: list[dict], eval_count: int,
                         context: str, *, collect_into: list[dict] | None = None,
                         verbose: bool = False) -> tuple[int, bool]:
    """
    The single eval pipeline shared by the main pass and the redo pass (they used
    to be two hand-copied loops). `candidates` is an ORDER-PRESERVED list of dicts
    with keys: portal_cfg, portal, job_id, title, company, url.

    For each window of up to EVAL_BATCH_SIZE_MAX candidates it runs the cheap
    filters inline (duplicate-rating copy, then title pre-filter), then fetches
    the survivors' descriptions IN PARALLEL (#throughput) before the empty/stale
    checks and the batched claude evaluation. Order is preserved, so the Groq
    relevance ordering still means best-first. Stops at MAX_EVALUATIONS or when a
    flush pauses for memory. Returns (eval_count, stopped_for_memory).
    """
    pending: list[dict] = []
    stopped = False
    i, n = 0, len(candidates)
    while i < n and (eval_count + len(pending)) < MAX_EVALUATIONS and not stopped:
        # 1) gather a window of fetch-needed survivors (cheap filters first)
        to_fetch: list[dict] = []
        while (i < n and len(to_fetch) < EVAL_BATCH_SIZE_MAX
               and (eval_count + len(pending) + len(to_fetch)) < MAX_EVALUATIONS):
            c = candidates[i]; i += 1
            existing = find_existing_rating(conn, c["title"], c["company"], c["portal"], c["job_id"])
            if existing:
                rating, notes = existing
                if verbose:
                    print(f"  [{c['portal']}] → duplicate of an already-rated listing, copying: {c['title'][:60]}")
                update_fit(conn, c["portal"], c["job_id"], rating,
                           f"{notes} (duplicate posting — rating copied from an earlier listing)")
                continue
            pf = _prefilter_rating(c["title"])
            if pf:
                RUN_STATS["prefiltered"] += 1
                if verbose:
                    print(f"  [{c['portal']}] → pre-filtered, no spawn spent: {c['title'][:60]}")
                update_fit(conn, c["portal"], c["job_id"], pf[0], pf[1])
                continue
            to_fetch.append(c)

        if not to_fetch:
            continue

        # 2) fetch the window's descriptions in parallel
        details = _fetch_details_parallel(to_fetch)

        # 3) empty/stale checks, then accumulate + flush (unchanged semantics)
        for c in to_fetch:
            description = details.get(c["job_id"], "") or ""
            if len(description.strip()) < MIN_DESCRIPTION_CHARS:
                RUN_STATS["empty_detail"] += 1
                if verbose:
                    print(f"  [{c['portal']}] → empty detail fetch, skipping: {c['title'][:60]}")
                update_fit(conn, c["portal"], c["job_id"], "No Fit",
                           "Detail fetch returned empty — listing likely removed/expired.")
                continue
            if is_stale(description, c["portal"]):
                RUN_STATS["stale"] += 1
                if verbose:
                    print(f"  [{c['portal']}] → stale (>48h), skipping: {c['title'][:60]}")
                update_fit(conn, c["portal"], c["job_id"], "No Fit", "Stale listing (posted >48h ago).")
                continue
            pending.append({"portal": c["portal"], "job_id": c["job_id"], "title": c["title"],
                            "company": c["company"], "url": c.get("url", ""), "description": description})
            if _should_flush(pending):
                eval_count, stopped, evaluated, pending = _flush_eval_batch(conn, pending, eval_count, context)
                if collect_into is not None:
                    for j in evaluated:
                        collect_into.append({k: j[k] for k in
                                             ("portal", "job_id", "title", "company", "url", "fit_rating", "fit_notes")})
                if stopped:
                    break
        if stopped:
            break

    eval_count, stopped = _drain_pending(conn, pending, eval_count, stopped,
                                         f"{context} (final partial batch)", collect_into=collect_into)
    if eval_count >= MAX_EVALUATIONS and i < n:
        print(f"\n[limit] MAX_EVALUATIONS={MAX_EVALUATIONS} reached — remaining listings stay "
              f"unevaluated until the next pass")
        RUN_STATS["cap_hit"] = True
    return eval_count, stopped


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

    _print_run_health()

    send_notification(strong, good, digest_path)
    _write_state(run_issues=RUN_STATS["issues"])

    if "--no-auto-resume" in sys.argv:
        # A child drain pass: never orchestrate further. Just record terminal
        # state; if it stopped for memory, leave the paused state for the parent
        # loop (and the crash reporter) to see.
        if not stopped_for_memory:
            _write_state(phase="done")
    else:
        # Top-level run: chain --redo-unknown passes until the backlog is fully
        # drained (#3). Self-gates when there's nothing left and marks phase=done.
        _drain_backlog_loop()


# ============================================================
#  MAIN
# ============================================================

def main() -> None:
    populate_only = "--populate-cache" in sys.argv
    redo_mode     = "--redo-unknown" in sys.argv
    mode = "POPULATE CACHE (no evaluation)" if populate_only else ("redo Unknown/unevaluated" if redo_mode else "scan + evaluate")
    print(f"=== Morning scan {TODAY} [{mode}] ===")
    print(f"  relevance ranking: "
          f"{'Groq (' + GROQ_MODEL + ')' if GROQ_API_KEY else 'keyword (set GROQ_API_KEY for semantic ranking)'}")
    DIGESTS.mkdir(parents=True, exist_ok=True)

    _acquire_single_instance_lock()
    _report_previous_run_if_crashed()

    # #4 pace, don't cap: we deliberately do NOT lower MAX_EVALUATIONS when RAM is
    # tight at launch (that only guaranteed a degraded, incomplete finish). The run
    # instead keeps the full workload and absorbs memory pressure by pacing — the
    # per-flush adaptive batch size shrinks to 1 and waits under pressure (#5) — and
    # _drain_backlog_loop (#3) chains follow-up passes until the backlog is empty.
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
        # #6: re-evaluate the most relevant backlog first.
        if rows:
            _rscores = _relevance_scores_for([r[2] or "" for r in rows])
            rows = [r for _, r in sorted(zip(_rscores, rows), key=lambda p: p[0], reverse=True)]
        print(f"\n[redo] {len(rows)} Unknown/unevaluated jobs (all dates) to re-evaluate")
        candidates: list[dict] = []
        for portal_name, job_id, title, company, url in rows:
            portal_cfg = portal_by_name.get(portal_name)
            if not portal_cfg:
                # Portal was disabled/removed since this job was scraped, so there
                # is no CLI to fetch its detail — it can NEVER be evaluated. Mark
                # it terminal so it leaves the unevaluated set; otherwise it clogs
                # the backlog and spins the drain loop until MAX_DRAIN_ROUNDS
                # (confirmed 2026-10-19: 16 jobfinder-lu/jobs-ch jobs did exactly
                # this after those portals were disabled).
                update_fit(conn, portal_name, job_id, "No Fit",
                           "Portal no longer configured — out of scope, not evaluated.")
                continue
            candidates.append({"portal_cfg": portal_cfg, "portal": portal_name, "job_id": job_id,
                               "title": title or "", "company": company or "", "url": url or ""})
        eval_count, stopped_for_memory = _evaluate_candidates(conn, candidates, eval_count, "redo pass")
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
        if not found:
            # Zero listings from a portal that should have some is a coverage
            # red flag (broken query, changed site, dead CLI) — surface it in
            # the run-health banner rather than letting it pass as "nothing new".
            RUN_STATS["portals_zero"].append(portal_name)

        # #6: evaluate this portal's most relevant listings first, so a
        # partial/paced finish still surfaces the best matches (never drops any).
        if new_ids:
            _rscores = _relevance_scores_for([found[jid].get("title", "") for jid in new_ids])
            new_ids = [jid for _, jid in sorted(zip(_rscores, new_ids),
                                                key=lambda p: p[0], reverse=True)]
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
        # Pass 2: flatten the per-portal queues into one round-robin-ordered
        # candidate list (one job per portal per round preserves cross-portal
        # fairness; each portal's queue is already Groq-relevance-ordered, so the
        # flattened order is still best-first), then run the shared pipeline,
        # which fetches each window's descriptions in parallel.
        candidates: list[dict] = []
        while any(q for _, q in portal_queues):
            for portal_cfg, queue in portal_queues:
                if not queue:
                    continue
                jid = queue.pop(0)
                r = found_by_portal[portal_cfg["name"]][jid]
                candidates.append({
                    "portal_cfg": portal_cfg, "portal": portal_cfg["name"], "job_id": jid,
                    "title": r.get("title", ""),
                    "company": r.get("company", r.get("companyName", r.get("employer", r.get("hiringOrgName", "")))),
                    "url": r.get("url", ""),
                })
        eval_count, stopped_for_memory = _evaluate_candidates(
            conn, candidates, eval_count, "main pass", collect_into=new_jobs, verbose=True)

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
