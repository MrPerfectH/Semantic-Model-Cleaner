"""Experimental service commands. Existing offline command contracts are unchanged."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from .cli_contract import ArgumentParser, CLIUsageError
from .service_provider import (
    ProbeError,
    ServiceProvider,
    Target,
    error_hint,
    public_summary,
    result_exit,
)
from .service_probe import write_json


def parser_for():
    parser = ArgumentParser(
        description="Experimental read-only service validation. Live API compatibility remains unverified.",
        json_errors=True,
    )
    parser.add_argument("action", choices=["discover"])
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--workspace-id", required=True, help="Exact model workspace GUID.")
    parser.add_argument(
        "--model-id", required=True, help="Exact published model GUID. Names are not accepted."
    )
    parser.add_argument(
        "--report-workspace-id",
        action="append",
        required=True,
        help="Explicit report discovery workspace GUID; repeat for additional accessible workspaces.",
    )
    parser.add_argument(
        "--fixture", type=Path, help="Synthetic HTTP transcript; no live credentials or requests."
    )
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument(
        "--public",
        action="store_true",
        help="Export only sanitized, shareable summary; omit IDs and metadata.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="New private output file; existing files are never overwritten.",
    )
    return parser


def render_text(result):
    target = result.get("target", {})
    lines = [
        "Experimental service validation — live acceptance unverified",
        f"Target tenant: {target.get('tenant_id', '(redacted)')}",
        f"Model workspace: {target.get('workspace_id', '(redacted)')} | Model: {target.get('model_id', '(redacted)')}",
        f"Status: {result['status']}",
        "Global consumer completeness: unknown",
        f"Known direct Reports in inspected scope: {result.get('known_connected_report_count', 0)}",
    ]
    for ws in result.get("workspaces", []):
        lines.append(f"Workspace {ws['workspace_id']}: {ws['status']}")
    for report in result.get("reports", []):
        lines.append(f"Report {report['report_id']} ({report['name']}): {report['status']}")
    lines.append("Analysis Limitations:")
    lines.extend(
        "  " + row.get("code", row.get("feature", "unknown"))
        for row in result.get("analysis_limitations", [])
    )
    lines.extend("  " + code for code in result.get("limitation_codes", []))
    lines.extend("  " + error["message"] for error in result.get("errors", []))
    lines.extend(result["boundaries"])
    return "\n".join(lines)


def execute(args, *, progress=None):
    target = Target(
        args.tenant_id, args.workspace_id, args.model_id, tuple(args.report_workspace_id)
    )
    provider = ServiceProvider(target, fixture=args.fixture, progress=progress)
    return provider.discover()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser_for().parse_args(argv)
        result = execute(args)
        payload = public_summary(result) if args.public else result
        if args.output:
            write_json(args.output, payload)
        else:
            print(json.dumps(payload, indent=2) if args.format == "json" else render_text(payload))
        return result_exit(result)
    except (ProbeError, CLIUsageError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ProbeError) else "invalid_input_or_output"
        print(
            json.dumps(
                {
                    "schema_version": "service-validation/1",
                    "command": "service",
                    "experimental": True,
                    "status": "failed",
                    "error": {"code": code, "message": error_hint(code)},
                }
            )
        )
        return 2
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "schema_version": "service-validation/1",
                    "command": "service",
                    "experimental": True,
                    "status": "cancelled",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
