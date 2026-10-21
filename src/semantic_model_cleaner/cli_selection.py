"""Consistent opt-in artifact paths; legacy selectors retain their semantics."""
from pathlib import Path


def add_path_options(parser):
    parser.add_argument("--model-path", help="Exact .SemanticModel folder, relative to PROJECT (or absolute).")
    parser.add_argument("--report-path", action="append", help="Exact connected .Report folder, relative to PROJECT (or absolute); repeatable.")


def resolve_path_options(args, project):
    """Validate canonical selectors without falling back to discovery on mistakes."""
    model = getattr(args, "model_path", None)
    reports = getattr(args, "report_path", None)
    if model is not None and (getattr(args, "model", None) or getattr(args, "models_path", None)):
        raise ValueError("--model-path cannot be combined with --model or --models-path.")
    if reports and any(getattr(args, name, None) for name in ("report", "reports_path", "all_reports", "model_only")):
        raise ValueError("--report-path cannot be combined with --report, --reports-path, --all-reports or --model-only.")
    if (model is not None or reports) and not Path(project).is_dir():
        raise ValueError(f"Project directory does not exist: {project}")

    def artifact(value, suffix, option):
        path = (Path(project) / value).resolve()
        if not path.is_dir() or not path.name.casefold().endswith(suffix.casefold()):
            raise ValueError(f"{option} requires an existing {suffix} folder: {path}")
        if not (path / "definition").is_dir():
            raise ValueError(f"{option} requires a supported definition directory: {path}")
        return path

    return (
        artifact(model, ".SemanticModel", "--model-path") if model is not None else None,
        sorted({artifact(value, ".Report", "--report-path") for value in reports}) if reports else None,
    )


def select_exact_reports(requested, connected):
    """Exact paths never silently drop unbound Reports or become name searches."""
    if any(path not in connected for path in requested):
        raise ValueError("Every --report-path must be connected to the selected Semantic Model.")
    return requested
