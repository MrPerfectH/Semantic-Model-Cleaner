"""Small file snapshot helpers for transactional cleanup writes."""

from pathlib import Path


def snapshot_artifact_files(
    roots: list[Path],
    *,
    suffixes: tuple[str, ...] = (".tmdl", ".json"),
) -> dict[Path, str]:
    snapshot: dict[Path, str] = {}
    normalized_suffixes = tuple(suffix.casefold() for suffix in suffixes)

    for root in roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in candidates:
            if path.suffix.casefold() in normalized_suffixes:
                snapshot[path.resolve()] = path.read_text(encoding="utf-8")

    return snapshot


def restore_artifact_files(
    roots: list[Path],
    snapshot: dict[Path, str],
    *,
    suffixes: tuple[str, ...] = (".tmdl", ".json"),
) -> dict:
    normalized_suffixes = tuple(suffix.casefold() for suffix in suffixes)
    errors: list[str] = []
    current_files: set[Path] = set()

    for root in roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        current_files.update(
            path.resolve()
            for path in candidates
            if path.suffix.casefold() in normalized_suffixes
        )

    for path in current_files - set(snapshot):
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"Could not remove created file {path}: {exc}")

    for path, content in snapshot.items():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            errors.append(f"Could not restore {path}: {exc}")

    return {
        "ok": not errors,
        "restored_file_count": len(snapshot),
        "removed_created_file_count": len(current_files - set(snapshot)),
        "errors": errors,
    }
