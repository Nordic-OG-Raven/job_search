#!/usr/bin/env python3
"""Concurrency-capped, low-memory wrapper around `bun run`.

Every portal-search CLI call (from morning_scan.py AND from an interactive
Claude session running the SKILL.md example commands) goes through this
instead of calling `bun` directly. Two problems this fixes:

1. Uncapped parallel spawns: evaluating a large backlog (e.g. 254 listings)
   by firing off many Bash/Skill tool calls in the same turn used to launch
   one full Bun runtime per call with no limit, exhausting all system RAM
   and crashing unrelated processes. This caps it to SLOTS concurrent
   runtimes; anything beyond that blocks until a slot frees up.
2. Per-process heap size: `--smol` tells Bun to run in low-memory mode,
   bounding how much any single call can use.

A slot is a flock() on one of SLOTS lock files. The lock is tied to the
open file descriptor, which fcntl requires to be marked inheritable to
survive exec — so it transfers to the bun process and is released
automatically by the kernel when that process exits, even if it's killed
or crashes. No stale-lock cleanup needed.
"""
import fcntl
import os
import shutil
import sys
import time

SLOTS = 3
POLL_SECONDS = 0.5
# shutil.which() first so this works out of the box on any machine where bun
# is on PATH; falls back to this machine's known install location only if not.
BUN_BIN = shutil.which("bun") or "/Users/jonas/.bun/bin/bun"
LOCK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bun_slots")


def acquire_slot() -> None:
    os.makedirs(LOCK_DIR, exist_ok=True)
    while True:
        for i in range(SLOTS):
            path = os.path.join(LOCK_DIR, f"slot_{i}.lock")
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            os.set_inheritable(fd, True)
            return
        time.sleep(POLL_SECONDS)


def main() -> None:
    acquire_slot()
    os.execv(BUN_BIN, [BUN_BIN, "--smol", "run"] + sys.argv[1:])


if __name__ == "__main__":
    main()
