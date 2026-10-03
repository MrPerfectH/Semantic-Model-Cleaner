"""Destination boundaries for read-only analysis exports."""
from pathlib import Path


def validate_export_destination(output: str, artifacts: list[Path]) -> Path:
    """Resolve aliases and reject exports that could overwrite project metadata.

    Hard links do not resolve to their other directory entries. Reject existing
    multiply-linked outputs rather than truncating an inode that may also belong
    to a Semantic Model or Report outside the analyzed scope.
    """
    requested = Path(output).absolute()
    target = requested.resolve()
    roots = {artifact.resolve() for artifact in artifacts}
    inside_artifact = any(target.is_relative_to(root) for root in roots)
    # Also protect named artifacts outside discovery, including a .Report or
    # .SemanticModel directory that itself aliases an otherwise unnamed folder.
    named_artifact = any(
        ancestor.name.casefold().endswith((".semanticmodel", ".report"))
        and target.is_relative_to(ancestor.resolve())
        for path in (requested, target) for ancestor in path.parents
    )
    if inside_artifact or named_artifact:
        raise ValueError(
            "Analysis output must be outside Semantic Model and Report artifact folders. "
            "Choose an external export directory with --output."
        )
    if target.exists():
        if not target.is_file():
            raise ValueError("Analysis output must be a file in an external export directory.")
        if target.stat().st_nlink > 1:
            raise ValueError(
                "Analysis output has multiple hard links and could overwrite project metadata. "
                "Choose a new file in an external export directory with --output."
            )
    if not target.parent.is_dir():
        raise ValueError("Analysis output directory does not exist. Choose an existing external export directory.")
    return target
