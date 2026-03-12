from pathlib import Path

from semantic_model_cleaner import backlog_worktree


def test_slugify_backlog_item_normalizes_text():
    assert backlog_worktree.slugify_backlog_item("Item 123: Refresh Toggle") == (
        "item-123-refresh-toggle"
    )


def test_slugify_backlog_item_rejects_empty_slug():
    try:
        backlog_worktree.slugify_backlog_item("!!!")
    except ValueError as exc:
        assert "must contain at least one letter or digit" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_default_worktree_home_prefers_configured_env(tmp_path):
    context = backlog_worktree.RepoContext(
        current_top=tmp_path / "task-01",
        repo_root=tmp_path / "repo-root",
        repo_name="Semantic-Model-Cleaner",
    )

    home = backlog_worktree.default_worktree_home(
        context,
        {"SMC_WORKTREE_HOME": str(tmp_path / "custom-home")},
    )

    assert home == (tmp_path / "custom-home" / "Semantic-Model-Cleaner").resolve()


def test_default_worktree_home_reuses_linked_worktree_parent(tmp_path):
    repo_home = tmp_path / "Semantic-Model-Cleaner"
    current_top = repo_home / "item-123"
    context = backlog_worktree.RepoContext(
        current_top=current_top,
        repo_root=tmp_path / "source" / "Semantic-Model-Cleaner",
        repo_name="Semantic-Model-Cleaner",
    )

    assert backlog_worktree.default_worktree_home(context, {}) == repo_home.resolve()


def test_default_worktree_home_falls_back_to_repo_sibling_folder(tmp_path):
    repo_root = tmp_path / "source" / "Semantic-Model-Cleaner"
    context = backlog_worktree.RepoContext(
        current_top=repo_root,
        repo_root=repo_root,
        repo_name="Semantic-Model-Cleaner",
    )

    assert backlog_worktree.default_worktree_home(context, {}) == (
        tmp_path / "source" / "Semantic-Model-Cleaner-worktrees"
    ).resolve()


def test_parse_worktree_list_extracts_branch_and_flags():
    output = "\n".join(
        [
            "worktree C:/Projects/Semantic-Model-Cleaner",
            "HEAD 619b422",
            "branch refs/heads/main",
            "",
            "worktree C:/Users/MrPerfectH/.t3/worktrees/Semantic-Model-Cleaner/item-123",
            "HEAD 619b422",
            "branch refs/heads/backlog/item-123",
            "locked manual review",
            "",
        ]
    )

    entries = backlog_worktree.parse_worktree_list(output)

    assert len(entries) == 2
    assert entries[0].branch == "main"
    assert entries[1].branch == "backlog/item-123"
    assert entries[1].locked == "manual review"


def test_resolve_target_path_converts_slug_to_worktree_path(tmp_path):
    home = tmp_path / "Semantic-Model-Cleaner"

    resolved = backlog_worktree._resolve_target_path("Item 123", home)

    assert resolved == (home / "item-123").resolve()
