#!/bin/bash
# PostToolUse hook: verifies a cover letter still follows the mandatory four-part
# structure (Motivation / Value+tasks / Company knowledge / Personal fit) documented
# in .claude/skills/job-application-assistant/06-cover-letter-templates.md, every
# time a cover_letters/*.tex file is written or edited. Runs an independent
# `claude --print` check rather than trusting the generating session's own
# self-assessment, since that already failed once (2026-09-26, Adversus letter).

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

case "$file_path" in
  */cover_letters/*.tex) ;;
  *) exit 0 ;;
esac

if [[ ! -f "$file_path" ]]; then
  exit 0
fi

tmpfile=$(mktemp)
cat > "$tmpfile" << PROMPT_EOF
You are checking a LaTeX cover letter for structural compliance against a mandatory rule.
The letter's body must have EXACTLY these four parts, each its own clean paragraph, no fifth part, no content blended between parts:

1. Motivation - why this specific job. Must not just be a capability/positioning hook.
2. Value/tasks - capability mapping to the posting's tasks, plus at least one capability not explicitly listed in the posting. Gap-confession only for a genuinely hard/blocking requirement, paired with a counter-argument.
3. Company knowledge - something genuine and specific about this company (personal connection, mission, growth story, culture). Must contain ONLY company-specific content, not a capability claim.
4. Personal fit - what the candidate is like to work with, colleague's-eye view. Not hobbies.

The greeting line ("Dear X,") and a short closing sentence ("I look forward to hearing from you" or equivalent) are normal boilerplate, NOT one of the four parts and NOT a violation — do not flag them as a missing/extra part.

Also flag: any sentence that just repeats a CV bullet with no new framing, any sentence stating the obvious (e.g. "I am writing to apply for X"), or any extra SUBSTANTIVE paragraph beyond the four that doesn't map cleanly to one part.

ALLOWED, do NOT flag: a single confident subsidy/availability offer sentence on a Danish posting (mentioning virksomhedspraktik and/or løntilskud) — it normally lives inside Part 1 (motivation/confidence) or at the end of Part 2 (value), and is NOT a fifth part or a violation.

Reply with EXACTLY one line: either the word PASS, or FAIL: <specific reason(s), naming which part(s) are violated and why>. No other output.

Cover letter content to check:

$(cat "$file_path")
PROMPT_EOF

result=$(claude --print < "$tmpfile" 2>/dev/null)
rm -f "$tmpfile"

# Soft, NON-BLOCKING nudge: a Danish-looking cover letter that omits the subsidy
# mechanism. virksomhedspraktik/løntilskud only exist for Danish postings and only
# while the candidate is eligible, so this is a reminder, never a hard failure — international
# (CH/LU/CA/AU) letters and post-eligibility letters legitimately omit it.
subsidy_reminder=""
if grep -qi "Kære\|Med venlig hilsen\|ansøgning\|stillingen" "$file_path" 2>/dev/null \
   && ! grep -qi "løntilskud\|virksomhedspraktik" "$file_path" 2>/dev/null; then
  subsidy_reminder="SOFT REMINDER (not a failure): this looks like a Danish cover letter with no virksomhedspraktik/løntilskud subsidy line. If it is a Danish posting where the candidate is eligible, consider adding the confident subsidy offer (see 06-cover-letter-templates.md -> Subsidy Offer). Skip for international postings or when not eligible."
fi

if [[ "$result" == PASS* ]]; then
  if [[ -n "$subsidy_reminder" ]]; then
    jq -n --arg r "$subsidy_reminder" '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": $r}}'
  fi
  exit 0
fi

jq -n --arg reason "$result" --arg file "$file_path" --arg r "$subsidy_reminder" \
  '{"decision": "block", "reason": ("Cover letter four-part structure check FAILED for " + $file + ": " + $reason), "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ("MANDATORY STRUCTURE CHECK FAILED for " + $file + ": " + $reason + " -- Fix this before presenting the letter to the candidate." + (if $r != "" then "\n\n" + $r else "" end))}}'
exit 0
