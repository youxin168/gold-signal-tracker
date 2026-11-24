#!/usr/bin/env bash
# Preserve the dedicated automation journal across ephemeral GitHub Actions runners.
set -euo pipefail
state_branch=refs/heads/signal-tracker-state
dir=generated-artifacts
mkdir -p "$dir"

# Exit 2 means the state branch has never been created. Other errors must stop
# the run rather than starting over and risking duplicate publication.
parent=""
if git ls-remote --exit-code origin "$state_branch" >/dev/null; then
  git fetch --quiet --no-tags origin "$state_branch"
  parent=$(git rev-parse FETCH_HEAD)
else
  rc=$?
  if [[ "$rc" != 2 ]]; then exit "$rc"; fi
fi

case "${1:-}" in
  restore)
    if [[ -n "$parent" ]]; then
      for name in signals.db runner-status.json; do
        if git cat-file -e "$parent:$name" 2>/dev/null; then
          git show "$parent:$name" > "$dir/$name"
        fi
      done
    fi
    ;;
  save)
    # Put only these two files on the public state branch; never the calendar,
    # GitHub secrets, chat identifiers, or any local database from a workstation.
    if [[ -z "$parent" && ! -f "$dir/signals.db" && ! -f "$dir/runner-status.json" ]]; then exit 0; fi
    tree=$(
      for name in signals.db runner-status.json; do
        if [[ -f "$dir/$name" ]]; then
          printf '100644 blob %s\t%s\n' "$(git hash-object -w "$dir/$name")" "$name"
        elif [[ -n "$parent" ]] && git cat-file -e "$parent:$name" 2>/dev/null; then
          git ls-tree "$parent" -- "$name"
        fi
      done | git mktree
    )
    parents=()
    if [[ -n "$parent" ]]; then
      if [[ "$tree" == "$(git rev-parse "$parent^{tree}")" ]]; then exit 0; fi
      parents=(-p "$parent")
    fi
    revision=$(git -c user.name="Signal Tracker automation" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      commit-tree "$tree" "${parents[@]}" -m "Save gold signal journal")
    # No force push: a concurrent update must fail instead of losing records.
    git push origin "$revision:$state_branch"
    ;;
  *) echo "Usage: bash scripts/runner-state.sh restore|save" >&2; exit 2 ;;
esac
