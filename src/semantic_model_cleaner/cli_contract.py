"""Shared machine-output conventions without changing saved artifact schemas."""
import argparse
import json


COMMAND_GUIDE = """Commands (use COMMAND --help for details):
  smc PROJECT                     Analyze one model and its connected Reports
  smc items PROJECT --search TEXT  Find item names (bounded results)
  smc usage PROJECT --item NAME    Explain usage; add --table to disambiguate
  smc usage PROJECT --table NAME   Explain whole-table usage
  smc summary PROJECT             Model totals and each Report's footprint
  smc review PROJECT              Compact existing model/Report checks
  smc capabilities                Discover query options and reviewed operations
  smc check PROJECT               Read-only CI checks (JSON by default)
  smc operations-schema           Standalone JSON Schema for versioned operations
  smc clean-stale PROJECT          Discover stale Report metadata (read-only)
  smc plan PROJECT --operations FILE -o PLAN
                                  Prepare reviewed changes on copies
  smc diff PLAN [CANDIDATE]        Show plan diff, or compare two model folders
  smc apply PLAN                  Apply the exact reviewed plan
  smc verify PLAN                 Check current files against the plan
  smc history                     List local change receipts
  smc restore PLAN                Recover original bytes from the reviewed plan
  smc recover-lock PLAN           Recover an interrupted operation lock
  smc policy ACTION PROJECT       Show/validate/init/add/remove review decisions
  smc naming preview PROJECT      Preview naming conventions as a reviewed plan

Examples:
  smc . --format json
  smc check . --model Models/Sales.SemanticModel --report Executive
  smc plan . --operations operations.json -o review/changes.json --format json
  smc diff review/changes.json --format json
  smc apply review/changes.json --format json

Path rules:
  Analysis/clean-stale --model and --report are name substring FILTERS.
  Analysis --models-path/--reports-path are search paths relative to the CWD.
  Check --model is an exact path relative to PROJECT; --report is a name filter.
  Plan --model/--report are exact paths relative to the current directory (CWD).
  Policy/naming --model/--report are exact paths relative to PROJECT.
  Items/usage/summary/review --model/--report are exact paths relative to PROJECT.
  Output, operations, plan, baseline and journal file paths are relative to CWD.

Automation: UTF-8 output. Analysis --format json and check use JSON stdout.
Plan-family --format json opts into JSON stdout for successes and errors;
omitting it preserves existing text diffs and JSON errors on stderr.
Machine-mode exit 0: success; 1: findings/verification or operation failure; 2: invalid input
or execution failure. See docs/cli/README.md for per-command details.
Aliases: smc, semantic-model-cleaner, python -m semantic_model_cleaner.
Use --version to print the installed package version.
"""


class CLIUsageError(ValueError):
    """Argument syntax error represented in the requested JSON envelope."""


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, json_errors=False, **kwargs):
        self.json_errors = json_errors
        super().__init__(*args, **kwargs)

    def error(self, message):
        if self.json_errors:
            raise CLIUsageError(message)
        super().error(message)


def json_requested(argv, *, default=False):
    format_value = "json" if default else None
    for index, value in enumerate(argv):
        if value.startswith("--format="):
            format_value = value.partition("=")[2]
        elif value == "--format" and index + 1 < len(argv):
            format_value = argv[index + 1]
    return format_value == "json" or (default and format_value != "text")


def emit_json(command, payload):
    """Add command metadata around response data, never persisted plan content."""
    response = {"schema_version": "1.0", "command": command, "ok": True, **payload}
    if response.get("error") and "errors" not in response:
        response["errors"] = [response["error"]]
    print(json.dumps(response, indent=2, ensure_ascii=False))


class DiagnosticCapture:
    """Tee human diagnostics so interactive prompts remain visible immediately."""
    def __init__(self, stream):
        self.stream = stream
        self.parts = []

    def write(self, text):
        self.parts.append(text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)
