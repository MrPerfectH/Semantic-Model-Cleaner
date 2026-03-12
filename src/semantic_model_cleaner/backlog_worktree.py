"""CLI helpers for backlog-oriented git worktree workflows."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


@dataclass(frozen=True)
class RepoContext:
    """Resolved git paths for the current repository."""

    current_top: Path
    repo_root: Path
    repo_name: str


@dataclass(frozen=True)
class WorktreeEntry:
    """Parsed `git worktree list --porcelain` row."""

    path: Path
    head: str | None = None
    branch: str | None = None
    locked: str | None = None
    prunable: str | None = None


def slugify_backlog_item(value: str) -> str:
    """Normalize a backlog item label into a branch/path-safe slug."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Backlog item name must contain at least one letter or digit.")
    return slug


def default_worktree_home(context: RepoContext, env: dict[str, str] | None = None) -> Path:
    """Choose a stable home for linked worktrees."""

    env = env or os.environ
    configured = env.get("SMC_WORKTREE_HOME")
    if configured:
        return Path(configured).expanduser().resolve() / context.repo_name

    if context.current_top.name != context.repo_name:
        return context.current_top.parent.resolve()

    return (context.repo_root.parent / f"{context.repo_name}-worktrees").resolve()


def branch_name_for(slug: str, prefix: str) -> str:
    """Build the backlog branch name."""

    clean_prefix = prefix.strip().strip("/")
    return f"{clean_prefix}/{slug}" if clean_prefix else slug


def worktree_path_for(home: Path, slug: str) -> Path:
    """Build the linked worktree path."""

    return home / slug


def parse_worktree_list(output: str) -> list[WorktreeEntry]:
    """Parse `git worktree list --porcelain` output."""

    entries: list[WorktreeEntry] = []
    current: dict[str, str] = {}

    for line in output.splitlines():
        if not line:
            if current:
                entries.append(
                    WorktreeEntry(
                        path=Path(current["worktree"]),
                        head=current.get("HEAD"),
                        branch=_normalize_branch_ref(current.get("branch")),
                        locked=current.get("locked"),
                        prunable=current.get("prunable"),
                    )
                )
                current = {}
            continue

        key, _, value = line.partition(" ")
        current[key] = value

    if current:
        entries.append(
            WorktreeEntry(
                path=Path(current["worktree"]),
                head=current.get("HEAD"),
                branch=_normalize_branch_ref(current.get("branch")),
                locked=current.get("locked"),
                prunable=current.get("prunable"),
            )
        )

    return entries


def format_entry_status(entry: WorktreeEntry) -> str:
    """Compact human-readable status column for list output."""

    labels = []
    if entry.branch:
        labels.append(entry.branch)
    else:
        labels.append("(detached)")
    if entry.locked is not None:
        labels.append("locked")
    if entry.prunable is not None:
        labels.append("prunable")
    return ", ".join(labels)


def discover_repo_context(cwd: Path) -> RepoContext:
    """Resolve current worktree and canonical repo root via git."""

    current_top = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--show-toplevel"], cwd)
    ).resolve()
    common_git_dir = Path(
        _run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    ).resolve()
    repo_root = common_git_dir.parent
    return RepoContext(current_top=current_top, repo_root=repo_root, repo_name=repo_root.name)


def find_worktree_entry(entries: list[WorktreeEntry], target_path: Path) -> WorktreeEntry | None:
    """Locate a worktree entry by resolved path."""

    resolved = target_path.resolve()
    for entry in entries:
        if entry.path.resolve() == resolved:
            return entry
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout.rstrip(), file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.rstrip(), file=sys.stderr)
        return exc.returncode or 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smc-backlog",
        description="Create and manage per-backlog-item git worktrees.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a linked worktree for a backlog item.")
    create.add_argument("item", help="Backlog item label, ticket, or short description.")
    create.add_argument(
        "--name",
        help="Override the generated worktree folder/branch slug.",
    )
    create.add_argument(
        "--base",
        default="origin/main",
        help="Base branch or commit to branch from. Defaults to origin/main.",
    )
    create.add_argument(
        "--branch-prefix",
        default="backlog",
        help="Prefix for new branches. Defaults to backlog.",
    )
    create.add_argument(
        "--worktrees-dir",
        help="Explicit directory that will contain backlog worktrees.",
    )
    create.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip git fetch origin before creating the worktree.",
    )
    create.set_defaults(func=_cmd_create)

    listing = subparsers.add_parser("list", help="List repo worktrees.")
    listing.set_defaults(func=_cmd_list)

    remove = subparsers.add_parser("remove", help="Remove a linked worktree.")
    remove.add_argument(
        "item_or_path",
        help="Worktree slug or full path.",
    )
    remove.add_argument(
        "--worktrees-dir",
        help="Explicit directory that contains backlog worktrees.",
    )
    remove.add_argument(
        "--delete-branch",
        action="store_true",
        help="Delete the branch after removing the worktree.",
    )
    remove.add_argument(
        "--force",
        action="store_true",
        help="Force-remove the worktree and branch if needed.",
    )
    remove.set_defaults(func=_cmd_remove)

    prune = subparsers.add_parser("prune", help="Prune stale worktree metadata.")
    prune.set_defaults(func=_cmd_prune)

    return parser


def _cmd_create(args: argparse.Namespace) -> int:
    context = discover_repo_context(Path.cwd())
    slug = args.name or slugify_backlog_item(args.item)
    branch = branch_name_for(slug, args.branch_prefix)
    worktree_home = _resolve_worktree_home(context, args.worktrees_dir)
    target_path = worktree_path_for(worktree_home, slug)

    if not args.no_fetch:
        _run_git(["fetch", "origin"], context.current_top, check=True, capture=False)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run_git(
        ["worktree", "add", str(target_path), "-b", branch, args.base],
        context.current_top,
        check=True,
        capture=False,
    )

    print(f"Created {target_path}")
    print(f"Branch: {branch}")
    print(f"Base: {args.base}")
    return 0


def _cmd_list(_: argparse.Namespace) -> int:
    context = discover_repo_context(Path.cwd())
    output = _run_git(["worktree", "list", "--porcelain"], context.current_top)
    entries = parse_worktree_list(output)

    if not entries:
        print("No worktrees found.")
        return 0

    branch_width = max(len(format_entry_status(entry)) for entry in entries)
    for entry in entries:
        status = format_entry_status(entry).ljust(branch_width)
        print(f"{status}  {entry.path}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    context = discover_repo_context(Path.cwd())
    worktree_home = _resolve_worktree_home(context, args.worktrees_dir)
    target_path = _resolve_target_path(args.item_or_path, worktree_home)

    output = _run_git(["worktree", "list", "--porcelain"], context.current_top)
    entries = parse_worktree_list(output)
    entry = find_worktree_entry(entries, target_path)

    command = ["worktree", "remove"]
    if args.force:
        command.append("--force")
    command.append(str(target_path))
    _run_git(command, context.current_top, check=True, capture=False)

    if args.delete_branch and entry and entry.branch:
        delete_flag = "-D" if args.force else "-d"
        _run_git(
            ["branch", delete_flag, entry.branch],
            context.current_top,
            check=True,
            capture=False,
        )

    print(f"Removed {target_path}")
    if args.delete_branch and entry and entry.branch:
        print(f"Deleted branch {entry.branch}")
    return 0


def _cmd_prune(_: argparse.Namespace) -> int:
    context = discover_repo_context(Path.cwd())
    _run_git(["worktree", "prune"], context.current_top, check=True, capture=False)
    print("Pruned stale worktree metadata.")
    return 0


def _resolve_worktree_home(context: RepoContext, configured: str | None) -> Path:
    if configured:
        return Path(configured).expanduser().resolve()
    return default_worktree_home(context)


def _resolve_target_path(item_or_path: str, worktree_home: Path) -> Path:
    candidate = Path(item_or_path).expanduser()
    if candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate.resolve()
    return worktree_path_for(worktree_home, slugify_backlog_item(item_or_path)).resolve()


def _normalize_branch_ref(value: str | None) -> str | None:
    if not value:
        return None
    prefix = "refs/heads/"
    return value[len(prefix):] if value.startswith(prefix) else value


def _run_git(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
    capture: bool = True,
) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
    )
    return completed.stdout.strip() if capture else ""
