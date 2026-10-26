"""CI failure decisions, separate from finding severity and cleanup authorization."""

RULES = {f"SMC{number:03d}" for number in range(1, 13)}
ADVISORY_RULES = {"SMC004", "SMC005", "SMC006", "SMC007", "SMC009"}
REQUIREMENTS = {"require_complete_scan", "require_complete_schema", "require_all_reports"}


def validate_gate(value):
    if not isinstance(value, dict) or set(value) - {"rules", "unused_recommendations", *REQUIREMENTS}:
        raise ValueError("ci_gate must be an object containing only documented gate settings.")
    rules = value.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("ci_gate.rules must map rule IDs to fail or advisory.")
    for rule, action in rules.items():
        if rule not in RULES or not isinstance(action, str) or action not in {"fail", "advisory"}:
            raise ValueError("ci_gate.rules requires known SMC001-SMC012 IDs and fail/advisory values.")
        if action == "advisory" and rule not in ADVISORY_RULES:
            raise ValueError(f"ci_gate cannot make protected rule {rule} advisory.")
    result = {"rules": dict(rules)}
    for key in sorted(REQUIREMENTS):
        if key in value:
            if not isinstance(value[key], bool):
                raise ValueError(f"ci_gate.{key} must be a boolean.")
            result[key] = value[key]
    if "unused_recommendations" in value:
        choices = value["unused_recommendations"]
        if (not isinstance(choices, list) or not choices
                or any(not isinstance(item, str) or item not in {"Safe", "Review", "Blocked"} for item in choices)
                or len(set(choices)) != len(choices)):
            raise ValueError("ci_gate.unused_recommendations must be a nonempty unique array of Safe, Review or Blocked.")
        result["unused_recommendations"] = list(choices)
    return result


def evaluate_gate(findings, scope, schema_validation, settings, fail_on):
    """Annotate every finding with its effective decision; never hide evidence."""
    settings = validate_gate(settings)
    for finding in findings:
        rule = finding["rule_id"]
        if finding["suppressed"]:
            blocking, reason = False, "Suppressed by an existing baseline or current review decision."
        elif finding["severity"] == "error":
            blocking, reason = True, "Error findings always block unless already suppressed by the established baseline contract."
        elif (rule == "SMC004" and "unused_recommendations" in settings
              and finding.get("cleanup_recommendation") not in settings["unused_recommendations"]):
            blocking, reason = False, "Cleanup Recommendation is outside ci_gate.unused_recommendations."
        elif rule in settings["rules"]:
            blocking = settings["rules"][rule] == "fail"
            reason = f"Repository ci_gate.rules.{rule}: {settings['rules'][rule]}."
        else:
            blocking = fail_on == "warning"
            reason = f"Default --fail-on {fail_on} threshold."
        finding["gate"] = {"blocking": blocking, "reason": reason}
    checks = {
        "require_complete_scan": (scope.get("scan_complete") is True and scope.get("report_usage_checked", True),
                                  "Selected model/Report dependency scan must be complete."),
        "require_complete_schema": (schema_validation.get("complete") is True,
                                    "Every selected JSON metadata file must have complete declared-schema validation."),
        "require_all_reports": (scope.get("selection_complete") is True and scope.get("unverified_report_count") == 0,
                                "All known connected Reports must be selected, with no unverified discovered bindings."),
    }
    requirements = [{"requirement": name, "passed": bool(checks[name][0]), "reason": checks[name][1]}
                    for name in sorted(REQUIREMENTS) if settings.get(name)]
    return {"settings": settings, "requirements": requirements,
            "blocking_finding_count": sum(row["gate"]["blocking"] for row in findings),
            "failed_requirement_count": sum(not row["passed"] for row in requirements)}
