#!/bin/sh
# PreToolUse(mcp): lanes, subagents and managers never merge; the operator does, and so does the coordinator's main
# session once the PR's own checks pass (AGENTS.md, operator 2026-11-21; merge_role_ok in _lib.sh)
. "$(dirname "$0")/_lib.sh"; IN=$(cat); TOOL=$(json_get "$IN" .tool_name)
echo "$TOOL" | grep -Eq '^mcp__.+__(merge_pull_request|enable_pr_auto_merge|update_pull_request_branch)$' || exit 0
merge_role_ok "$IN" && exit 0
deny "dev-loop: $TOOL is a merge path; the operator or the coordinator merges (AGENTS.md). Leave the PR ready for review."
