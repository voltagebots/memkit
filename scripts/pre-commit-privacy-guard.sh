#!/usr/bin/env bash
# Fail-closed pre-commit hook: .gitignore alone is advisory (doesn't stop
# `git add -f` or a file written outside the ignored tree). This hard-
# refuses staging anything under data/private/ or matching a DB glob,
# independent of .gitignore.
set -euo pipefail

staged=$(git diff --cached --name-only)
blocked=0

while IFS= read -r path; do
    [ -z "$path" ] && continue
    case "$path" in
        data/private/*|*.db|*.sqlite|*.sqlite3|RESULTS_PRIVATE.md)
            echo "BLOCKED: staged path touches private data: $path" >&2
            blocked=1
            ;;
    esac
done <<< "$staged"

if [ "$blocked" -eq 1 ]; then
    echo "" >&2
    echo "Refusing to commit. Unstage with: git restore --staged <path>" >&2
    exit 1
fi

exit 0
