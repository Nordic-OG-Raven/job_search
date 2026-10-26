#!/usr/bin/env python3
"""
SessionStart hook: surface the LAST job-scan's health into the agent's context.

Why this exists: a fresh Claude session used to read the day's digest and
implicitly assume it was a complete, healthy scan. But the scan can crash,
run degraded, or not have run yet — and the digest looks the same. This hook
reads the persisted scan state (scripts/run_state.json, written by
morning_scan.py's _finish_run) plus whether today's digest exists, and injects
a short status line so the agent knows up front whether to trust the results.

Contract: reads the SessionStart hook JSON on stdin (ignored), ALWAYS exits 0,
and prints a single JSON object with hookSpecificOutput.additionalContext. Any
error is swallowed into a safe message — a health hook must never break the
session it's reporting on.
"""
import json
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
STATE_PATH = SCRIPTS / "run_state.json"
DIGESTS = SCRIPTS / "daily_digests"


def _emit(context: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    sys.exit(0)


def main() -> None:
    # Drain stdin so the hook runner never blocks on an unread pipe.
    try:
        sys.stdin.read()
    except Exception:
        pass

    today = date.today().isoformat()
    lines: list[str] = []

    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except Exception:
            lines.append("⚠ Could not read scripts/run_state.json (corrupt?) — "
                         "job-scan health is unknown; verify the last scan manually.")

    # 1) Did the last run finish cleanly? phase is set to "done" only on a clean exit.
    phase = state.get("phase")
    if phase not in ("done", None):
        lines.append(
            f"⚠ The last job scan did NOT finish cleanly (phase='{phase}', last action: "
            f"{state.get('last_action')!r}, heartbeat {state.get('last_heartbeat_at')}). "
            f"Results may be incomplete — suggest re-running `scripts/morning_scan.py --redo-unknown`."
        )

    # 2) Was the last completed run degraded? Prefer the structured run_health
    #    summary; fall back to the digest's DEGRADED banner for older state files.
    health = state.get("run_health") or {}
    problems = health.get("problems")
    if problems is None:
        problems = _problems_from_digest(health.get("digest_date") or today)
    if problems:
        hdate = health.get("digest_date", "last scan")
        lines.append(
            f"⚠ The last job scan ({hdate}) ran DEGRADED: " + "; ".join(problems) +
            ". When discussing job results, LEAD with this — do not present the digest as complete."
        )

    # 3) Has today's scan actually produced a digest yet?
    if not (DIGESTS / f"{today}.md").exists():
        lines.append(
            f"⚠ Today's job scan ({today}) has not produced a digest yet "
            f"(no daily_digests/{today}.md). If asked about today's jobs, say the scan hasn't run "
            f"rather than implying there are none."
        )

    if not lines:
        _emit(f"✓ Job-scan health: last scan completed clean and today's digest "
              f"(daily_digests/{today}.md) is present. Safe to present the digest normally.")

    _emit("SCAN HEALTH — action needed before trusting job results:\n- " + "\n- ".join(lines))


def _problems_from_digest(digest_date: str) -> list[str]:
    """Fallback for state files written before run_health existed: parse the
    '> - <problem>' bullets under the digest's DEGRADED banner."""
    path = DIGESTS / f"{digest_date}.md"
    if not path.exists():
        return []
    try:
        text = path.read_text()
    except Exception:
        return []
    if "DEGRADED" not in text:
        return []
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("> -"):
            out.append(s[3:].strip())
        elif out and not s.startswith(">"):
            break  # banner block ended
    return out


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _emit(f"(job-scan health hook errored: {e}; health unknown — verify the last scan manually.)")
