#!/bin/sh
# SessionStart: inject the constitution pointer, last ledger entry, and unblocked tasks (stdout becomes context)
R=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
[ -f "$R/AGENTS.md" ] && printf 'dev-loop: project constitution is %s/AGENTS.md (read it before acting).\n' "$R"
[ -f "$R/.devloop/LEDGER.md" ] && { printf '\n## Last dev-loop ledger entry\n'; awk '/^## /{b=""} {b=b $0 "\n"} END{printf "%s", b}' "$R/.devloop/LEDGER.md" | tail -n 12; }
ART="${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}/skills/dev-loop/scripts/artifacts.py"
# The task file is resolved by artifacts.py (<root>/tasks.jsonl, else .devloop/tasks.jsonl, or an override), never hardcoded here.
F=$(command -v python3 >/dev/null && python3 "$ART" tasks path --root "$R" 2>/dev/null)
[ -n "$F" ] && [ -f "$F" ] && { printf '\n## Unblocked tasks\n'; python3 "$ART" tasks next --root "$R" --limit 15 2>/dev/null; }
# Cloud sessions: agy keeps its credential in a keyring whose daemon is a process, so it is gone on
# every cold start while agy itself survives in the environment snapshot. Revive it and hand its bus
# address to every later tool call through CLAUDE_ENV_FILE, whatever repo the session is in.
# The env file outlives each SessionStart (startup, resume, clear, compact), so the hook owns ONE
# delimited block in it rather than appending (a bare >> stacked ~150 export pairs in one session):
# lines outside the markers are kept, the old block is dropped, the current one goes last, and the
# result is written to a sibling temp file (set -C: created exclusively) and renamed into place.
if [ "${CLAUDE_CODE_REMOTE:-}" = true ] && [ -x "$HOME/.local/bin/agy" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  K="${CLAUDE_PLUGIN_ROOT:-$(dirname "$0")/..}/skills/dev-loop/scripts/env/agy-keyring.sh"
  KE="${AGY_CLOUD_DIR:-$HOME/.config/agy-cloud}/keyring.env"
  MB='# >>> dev-loop keyring' ME='# <<< dev-loop keyring' T="$CLAUDE_ENV_FILE.dev-loop.$$"
  if [ -r "$K" ] && (. "$K") >/dev/null 2>&1 && [ -r "$KE" ]; then
    if (set -C; { { [ ! -f "$CLAUDE_ENV_FILE" ] || awk -v b="$MB" -v e="$ME" '$0==b{s=1;next} $0==e{s=0;next} !s' "$CLAUDE_ENV_FILE"; } \
         && printf '%s\n' "$MB" && awk 1 "$KE" && printf '%s\n' "$ME"; } > "$T") && mv -f "$T" "$CLAUDE_ENV_FILE"; then :; else rm -f "$T"; fi
  fi
fi
# Cloud sessions provisioned from a MiOS checkout: the host's tailnet node (tailscaled) is a
# process as well, so a resumed session has lost it, and an ephemeral node offline for a while
# has been removed. MiOS's `bootstrap.sh tailnet` restarts it and re-enrolls; it runs detached
# (it may mint a key and wait on the tailnet), logging under the MiOS cloud state directory.
MC="${MIOS_DEPLOYMENT_CLOUD_STATE_DIRECTORY:-/var/lib/mios-cloud}"
if [ "${CLAUDE_CODE_REMOTE:-}" = true ] && [ -r "$MC/source-root" ]; then
  B="$(head -n 1 "$MC/source-root")/.devcontainer/cloud-shell/bootstrap.sh"
  [ -f "$B" ] && (setsid nohup bash "$B" tailnet >> "$MC/tailnet.log" 2>&1 < /dev/null &)
fi
exit 0
