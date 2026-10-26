"""Generate the repository skill from the installed CLI's discovery contract."""
import argparse
import difflib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def cell(value):
    return str(value).replace("|", "&#124;").replace("\n", " ")


def option_text(option):
    parts = []
    if "value" in option:
        parts.append(option["value"])
    if "choices" in option:
        parts.append("choices: " + ", ".join(map(str, option["choices"])))
    if "type" in option:
        parts.append(option["type"])
    for key in ("minimum", "maximum", "default"):
        if key in option:
            parts.append(f"{key}: {option[key]}")
    if option.get("repeatable"):
        parts.append("repeatable")
    return "; ".join(parts)


def render(capabilities):
    commands = ["| Command | Purpose |", "| --- | --- |"]
    options = ["| Option | Details | Commands |", "| --- | --- | --- |"]
    grouped = {}
    for command in capabilities["commands"]:
        commands.append(f'| `smc {command["name"]}` | {cell(command["description"])} |')
        for option in command["options"]:
            key = json.dumps(option, sort_keys=True)
            grouped.setdefault(key, (option, []))[1].append(command["name"])
    for option, names in grouped.values():
        flag = option["flag"]
        if "alias" in option:
            flag += ", " + option["alias"]
        options.append(f'| `{cell(flag)}` | {cell(option_text(option))} | {", ".join(names)} |')
    replacements = {
        "VERSION": capabilities["tool_version"],
        "APPROVAL": capabilities["approval"],
        "SCOPE": capabilities["response"]["scope"],
        "COMMANDS": "\n".join(commands),
        "OPTIONS": "\n".join(options),
        "PATHS": capabilities["path_base"],
        "MATCHING": capabilities["matching"],
        "PAGINATION": capabilities["limits"]["pagination"],
        "SEMANTICS": "\n".join("- " + entry for entry in capabilities["semantics"]),
        "OPERATIONS": ", ".join(f"`{kind}`" for kind in capabilities["operations"]),
        "SCHEMA": capabilities["schema_command"],
        "EXIT_CODES": "\n".join(f"| {code} | {cell(meaning)} |"
                                 for code, meaning in capabilities["exit_codes"].items()),
        "EXAMPLES": "\n".join(capabilities["examples"]),
    }
    template = (ROOT / "scripts/templates/SKILL.md.in").read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if SKILL.md is stale; never write.")
    args = parser.parse_args()
    result = subprocess.run(
        [sys.executable, "-m", "semantic_model_cleaner", "capabilities"],
        check=True, capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    expected = render(json.loads(result.stdout))
    target = ROOT / "SKILL.md"
    if args.check:
        actual = target.read_text(encoding="utf-8") if target.exists() else ""
        if actual != expected:
            sys.stderr.writelines(difflib.unified_diff(
                actual.splitlines(keepends=True), expected.splitlines(keepends=True),
                fromfile="SKILL.md (committed)", tofile="SKILL.md (generated)",
            ))
            print("Run python scripts/generate_skill.py to refresh SKILL.md.", file=sys.stderr)
            return 1
        print("SKILL.md matches smc capabilities.")
        return 0
    target.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Generated {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
