#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parent_dir="$(cd "$repo_root/.." && pwd)"

worktree_specs=(
  "smc-foundation codex/public-foundation"
  "smc-windows codex/windows-exe"
  "smc-beta codex/beta-gating"
  "smc-site codex/landing-site"
)

branch_exists() {
  local branch="$1"
  git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"
}

worktree_exists() {
  local target="$1"
  git -C "$repo_root" worktree list --porcelain | grep -Fxq "worktree $target"
}

for spec in "${worktree_specs[@]}"; do
  read -r dirname branch <<<"$spec"
  target="$parent_dir/$dirname"

  if worktree_exists "$target"; then
    echo "Skipping existing worktree: $target"
    continue
  fi

  if [ -e "$target" ]; then
    echo "Refusing to create worktree because path already exists: $target" >&2
    exit 1
  fi

  if branch_exists "$branch"; then
    echo "Creating worktree for existing branch $branch at $target"
    git -C "$repo_root" worktree add "$target" "$branch"
  else
    echo "Creating worktree $target on new branch $branch"
    git -C "$repo_root" worktree add "$target" -b "$branch" main
  fi
done

echo
echo "Worktree setup complete."
echo "Review worktrees with: git -C \"$repo_root\" worktree list"
