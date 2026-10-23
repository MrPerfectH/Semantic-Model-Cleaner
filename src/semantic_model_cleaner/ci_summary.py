"""Bounded Markdown artifacts for checks; project metadata is always escaped."""
import html
import re


def _text(value, limit=800):
    value = " ".join(str(value).split())
    if len(value) > limit:
        value = value[:limit] + "… [truncated]"
    return re.sub(r"([\\`*_{}\[\]()#+.!|~:\-])", r"\\\1", html.escape(value, quote=True))


def render_summary(payload, exit_code):
    """At most 200 findings, 100 rows per scope collection and 20 input errors."""
    status = {0: "Passed", 1: "Blocked by findings or coverage requirements", 2: "Input or execution failure"}[exit_code]
    summary = payload.get("summary", {})
    scope = payload.get("scope", {})
    lines = ["# Semantic Model Cleaner", "", f"**{status}** (exit {exit_code}).", "",
             f"Findings: {summary.get('finding_count', 0)}; blocking findings/requirements: {summary.get('failure_count', 0)}; "
             f"suppressed findings: {summary.get('suppressed_count', 0)}.", "",
             "## Selected scope", "", "Semantic Model: " + _text(scope.get("model", "Not established")), "",
             "External consumers were not verified. No Use Found In Scope is not proof of global non-use.", ""]

    def listing(title, rows, render, limit):
        lines.extend([f"### {title} ({len(rows)})", ""])
        lines.extend("- " + render(row) for row in rows[:limit])
        if not rows:
            lines.append("None.")
        if len(rows) > limit:
            lines.append(f"{len(rows) - limit} additional entries omitted; see full JSON.")
        lines.append("")

    listing("Selected Reports", scope.get("reports", []), _text, 100)
    excluded = [row for row in scope.get("bindings", []) if not row.get("selected")]
    listing("Excluded Reports", excluded,
            lambda row: _text(row.get("path", "")) + " — " + _text(row.get("status", "")) + ": " + _text(row.get("message", "")), 100)
    lines.extend(["Dependency scan complete: " + _text(scope.get("scan_complete", "Unknown")) + ".",
                  "All known connected Reports selected: " + _text(scope.get("selection_complete", "Unknown")) + ".",
                  "Schema validation complete: " + _text(payload.get("schema_validation", {}).get("complete", "Unknown")) + ".", ""])
    listing("Input/execution errors", payload.get("errors", []), _text, 20)
    requirements = payload.get("gate", {}).get("requirements", [])
    listing("Coverage requirements", requirements,
            lambda row: _text(row["requirement"]) + (" — passed: " if row["passed"] else " — BLOCKING: ") + _text(row["reason"]), 3)
    findings = sorted(payload.get("findings", []), key=lambda row: (
        not row.get("gate", {}).get("blocking", False), row.get("suppressed", False), row["rule_id"], row["fingerprint"]))
    groups = [
        ("Report Health", {"SMC005", "SMC006", "SMC011"}),
        ("Analysis Limitations and coverage", {"SMC002", "SMC003", "SMC008", "SMC012"}),
        ("Items with No Use Found In Scope", {"SMC004"}),
        ("Naming", {"SMC009", "SMC010"}),
        ("Model references and other findings", {"SMC001", "SMC007"}),
    ]
    shown = {row["fingerprint"] for row in findings[:200]}
    for title, rules in groups:
        rows = [row for row in findings if row["rule_id"] in rules]
        lines.extend([f"## {title} ({len(rows)})", ""])
        visible = [row for row in rows if row["fingerprint"] in shown]
        for row in visible:
            gate = row.get("gate", {})
            state = "suppressed" if row["suppressed"] else "BLOCKING" if gate.get("blocking") else "advisory"
            identity = f"{row['table']}[{row['name']}]" if row.get("name") else ""
            location = " / ".join(filter(None, [row.get("path"), row.get("location")]))
            lines.append(f"- {_text(row['rule_id'])} ({_text(row['severity'])}; {state}): "
                         f"{_text(identity)} — {_text(row['message'])} Source: {_text(location)}.")
            if gate:
                lines.append("  Gate: " + _text(gate.get("reason", "")))
            decision = row.get("review_decision")
            if decision:
                lines.append("  Review: " + _text(row.get("review_status", "")) + "; " +
                             "; ".join(_text(decision.get(key, "")) for key in ("owner", "reason", "expires_on")))
        if not rows:
            lines.append("None.")
        if len(rows) > len(visible):
            lines.append(f"{len(rows) - len(visible)} additional findings omitted; see full JSON.")
        lines.append("")
    lines.append("Static checks of selected local files only. CI gates do not authorize cleanup or apply changes.")
    return "\n".join(lines) + "\n"
