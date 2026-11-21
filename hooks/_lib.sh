# shared helpers for dev-loop hooks (POSIX sh; jq optional, python3 fallback)
json_get() { # $1=json $2=jq path (e.g. .tool_input.command)
  if command -v jq >/dev/null 2>&1; then printf '%s' "$1" | jq -r "$2 // empty"; else
  printf '%s' "$1" | python3 -c 'import json,sys; d=json.load(sys.stdin)
for k in sys.argv[1].strip(".").split("."): d=d.get(k,"") if isinstance(d,dict) else ""
print(d if isinstance(d,str) else (json.dumps(d) if d not in ("",None) else ""))' "$2"; fi; }
deny() { # PreToolUse deny with reason
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' "$(printf '%s' "$1" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"; exit 0; }
merge_role_ok() { # $1=hook json. Only a MAIN session on a machine the operator marked as the coordinator's may merge
  # (AGENTS.md, operator 2026-11-21); a subagent or lane never does. The marker lives outside every repo, so a
  # checkout cannot grant it: ${DEVLOOP_MERGE_ROLE_FILE:-$XDG_CONFIG_HOME/dev-loop/merge-role} holding "coordinator".
  [ -z "$(json_get "$1" .agent_type)" ] || return 1
  _mr="${DEVLOOP_MERGE_ROLE_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/dev-loop/merge-role}"
  [ -f "$_mr" ] && [ -r "$_mr" ] && [ "$(tr -d '[:space:]' < "$_mr")" = coordinator ]; }
