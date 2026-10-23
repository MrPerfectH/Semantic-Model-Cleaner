"""Report-scoped extension deletion; no implicit cascade or expression rewrites."""
from __future__ import annotations

from collections import defaultdict
import copy
import json
from pathlib import Path

from . import analyzer, metadata_validation
from .reference_tokens import dax_references

OPERATION_KIND = "delete_report_measures"
EXTENSION = Path("definition/reportExtensions.json")


def _invalid_constant(value):
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON property: {key}")
        result[key] = value
    return result


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _strings(child)


def _mentions(text, name):
    # Conservative fallback for opaque and unfamiliar metadata surfaces.
    folded = text.casefold()
    return name.casefold() in folded or name.replace("]", "]]").casefold() in folded


def _entry(item):
    return {"report_path": str(Path(item.source_file).parent.parent.resolve()),
            "table": item.table, "name": item.name}


def _key(entry):
    return (str(Path(entry["report_path"]).resolve()), entry["table"].casefold(),
            entry["name"].casefold())


def assessment(model_path, report_paths, analysis):
    """Assess each report/entity/name identity and its explicit closed deletion group."""
    model = Path(model_path).resolve()
    reports = sorted({Path(p).resolve() for p in report_paths})
    rows = {_key(_entry(r["item"])): r for r in analysis["items"]
            if r["item"].source_kind == "report"}
    reasons = defaultdict(list)
    scope_reasons = []
    if not reports or not analysis.get("coverage", {}).get("complete", False):
        scope_reasons.append("Complete supported analysis coverage is required.")
    model_items = [r["item"] for r in analysis["items"] if r["item"].source_kind == "model"]
    model_names = {i.name.casefold() for i in model_items if i.item_type == "Measure"}
    entities = {i.table.casefold() for i in model_items}
    dependencies = defaultdict(set)
    report_reasons = defaultdict(list)
    for report in reports:
        owner = str(report)
        if analyzer.report_binding_status(report, model)["status"] != "connected":
            report_reasons[owner].append("Report deletion requires a verified local byPath binding to the selected semantic model.")
        local = {key: row for key, row in rows.items() if key[0] == owner}
        if not local:
            continue
        try:
            for path in sorted(report.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Symlinks are not supported.")
                if path.is_file() and path.suffix.lower() == ".dax":
                    raise ValueError("Saved report DAX queries are not covered by report extension deletion.")
                if not path.is_file() or path.suffix.lower() not in {".json", ".pbir"}:
                    continue
                if path == report / EXTENSION and path.read_bytes().startswith(b"\xef\xbb\xbf"):
                    raise ValueError("Report extension deletion requires UTF-8 without a BOM.")
                document = json.loads(path.read_bytes(), object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
                if not isinstance(document, dict):
                    raise ValueError(f"Expected a metadata object: {path.relative_to(report)}")
                if path == report / EXTENSION:
                    _extension_dependencies(document, local, model_items, model_names,
                                            entities, dependencies)
                else:
                    if "$schema" in document:
                        validation = metadata_validation.validate_document(document)
                        if validation["status"] != "valid" or validation["truncated"]:
                            raise ValueError(f"Invalid or unsupported report metadata schema: {path.relative_to(report)}")
                    strings = list(_strings(document))
                    for key in local:
                        if any(_mentions(value, local[key]["item"].name) for value in strings):
                            reasons[key].append("Reference or possible reference remains in "
                                                + path.relative_to(report).as_posix() + ".")
            if not (report / EXTENSION).is_file():
                raise ValueError("Report extension file is missing.")
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            report_reasons[owner].append(str(exc))

    selected = {str(p) for p in reports}
    for key, row in rows.items():
        reasons[key].extend(scope_reasons)
        reasons[key].extend(report_reasons[key[0]])
        if key[0] not in selected:
            reasons[key].append("Report is outside the selected scope.")
        if row.get("usages") or row.get("stale_usages") or analyzer.row_usage_status(row) != "NOT USED":
            reasons[key].append("Live, indirect, or stale report references require this measure.")
    candidates = {key for key in rows if not reasons[key]}
    while True:
        blocked = {target for source, targets in dependencies.items() if source not in candidates
                   for target in targets if target in candidates}
        if not blocked:
            break
        candidates -= blocked
    consumers = defaultdict(set)
    for source, targets in dependencies.items():
        for target in targets:
            if source != target:
                consumers[target].add(source)
    output = {}
    for key, row in rows.items():
        blockers = list(dict.fromkeys(reasons[key]))
        if key not in candidates and not blockers:
            blockers.append("Required by a retained report extension dependency chain.")
        needed = set()
        todo = list(consumers[key])
        while todo:
            source = todo.pop()
            if source == key or source in needed:
                continue
            needed.add(source)
            todo.extend(consumers[source] - needed)
        output[key] = {
            "supported": not scope_reasons and not report_reasons[key[0]] and key[0] in selected,
            "eligible": key in candidates and not needed,
            "groupEligible": key in candidates,
            "reasons": blockers or (["Select the dependency-closed group together."] if needed else []),
            "entry": _entry(row["item"]),
            "requiredGroup": [_entry(rows[k]["item"]) for k in sorted(needed | {key})]
                             if key in candidates else [],
            "reason": "No live, stale, opaque metadata or retained DAX consumer in the selected scope."
                      if key in candidates else "",
        }
    return output


def _extension_dependencies(document, local, model_items, model_names, entities, dependencies):
    validation = metadata_validation.validate_document(document)
    if validation["status"] != "valid" or validation["truncated"]:
        raise ValueError("Report extension metadata must validate against its supported declared schema.")
    owner = next(iter(local))[0]
    if analyzer.scan_report_extension_issues(Path(owner)):
        raise ValueError("Report extension metadata contains invalid or unrecognized references.")
    seen = set()
    for entity in document.get("entities", []):
        if entity["name"].casefold() not in entities:
            raise ValueError("Report extension entity is absent from the selected model.")
        for measure in entity.get("measures", []):
            key = (owner, entity["name"].casefold(), measure["name"].casefold())
            if key in seen or key not in local:
                raise ValueError("Duplicate or unreadable report extension identity.")
            seen.add(key)
            if not measure["name"].strip() or not measure["expression"].strip():
                raise ValueError("Empty report extension identity or expression.")
            if measure["name"].casefold() in model_names:
                raise ValueError("Report extension name collides with a semantic-model measure.")
            if analyzer._expression_uses_dynamic_measure_context(measure["expression"]):
                raise ValueError("Dynamic report extension dependencies cannot be proved.")
            if local[key].get("broken_dax_refs"):
                raise ValueError("Unresolved report extension DAX dependencies.")
            # Qualified names resolve in this report/entity only. Bare names
            # conservatively retain every candidate, never a global first match.
            for table, name in dax_references(measure["expression"]):
                dependencies[key].update(target for target in local
                    if target[2] == name.casefold()
                    and (table is None or target[1] == table.casefold()))
            for ref in measure.get("references", {}).get("measures", []):
                if ref.get("schema", "") not in ("", document["name"]):
                    raise ValueError("Unknown report extension reference schema.")
                target = (owner, ref["entity"].casefold(), ref["name"].casefold())
                candidates = [i for i in model_items if i.item_type == "Measure"
                              and analyzer.normalize_key(*i.key) == target[1:]]
                if target not in local and not candidates:
                    raise ValueError("Unresolved explicit report extension dependency.")
                if ref.get("schema") and target not in local:
                    raise ValueError("Explicit extension reference does not resolve in this report.")
                if target in local:
                    dependencies[key].add(target)
    if seen != set(local):
        raise ValueError("Report extension inventory does not match current identities.")



def check_operation(operation, assessments):
    if set(operation) - {"kind", "entries"} or operation.get("kind") != OPERATION_KIND:
        raise ValueError("Report measure deletion accepts only kind and entries.")
    entries = operation.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Report measure deletion requires explicit report/entity/name entries.")
    selected = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"report_path", "table", "name"}:
            raise ValueError("Each report deletion requires exact report_path, table and name.")
        if any(not isinstance(v, str) or not v.strip() for v in entry.values()):
            raise ValueError("Report deletion identity fields must be nonempty strings.")
        if not Path(entry["report_path"]).is_absolute():
            raise ValueError("Report deletion requires an absolute selected report path.")
        key = _key(entry)
        if key in selected:
            raise ValueError("Duplicate report measure deletion target.")
        if key not in assessments:
            raise ValueError("Unknown or unselected report measure identity.")
        selected.add(key)
    explanations = []
    for key in sorted(selected):
        evidence = assessments[key]
        if not evidence["groupEligible"]:
            raise ValueError("Cannot delete report extension measure: " + "; ".join(evidence["reasons"]))
        if not {_key(entry) for entry in evidence["requiredGroup"]} <= selected:
            raise ValueError("Report extension measure is required by a retained measure; select its dependency-closed group.")
        explanations.append({**evidence["entry"], "reason": evidence["reason"],
                             "required_group": evidence["requiredGroup"]})
    return explanations


def _array_spans(text):
    """Locate JSON array element spans without serializing retained content."""
    decoder = json.JSONDecoder()
    arrays = {}

    def whitespace(pos):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        return pos

    def visit(pos, path):
        pos = whitespace(pos)
        if text[pos] == "{":
            pos = whitespace(pos + 1)
            while text[pos] != "}":
                key, pos = decoder.raw_decode(text, pos)
                pos = whitespace(pos)
                if text[pos] != ":":
                    raise ValueError("Invalid JSON object")
                pos = whitespace(visit(pos + 1, path + (key,)))
                if text[pos] == ",":
                    pos = whitespace(pos + 1)
                else:
                    break
            return pos + 1
        if text[pos] == "[":
            pos = whitespace(pos + 1)
            spans = []
            while text[pos] != "]":
                start = pos
                end = visit(pos, path + (len(spans),))
                spans.append((start, end))
                pos = whitespace(end)
                if text[pos] == ",":
                    pos = whitespace(pos + 1)
                else:
                    break
            arrays[path] = spans
            return pos + 1
        return decoder.raw_decode(text, pos)[1]

    visit(0, ())
    return arrays


def delete_definitions(report_paths, entries):
    """Staging-only writer; caller checks policy and uses the sealed-plan transaction."""
    allowed = {Path(p).resolve() for p in report_paths}
    grouped = defaultdict(set)
    for entry in entries:
        report = Path(entry["report_path"]).resolve()
        if report not in allowed:
            raise ValueError("Report deletion target is outside selected reports.")
        grouped[report].add((entry["table"].casefold(), entry["name"].casefold()))
    for report, targets in grouped.items():
        path = report / EXTENSION
        text = path.read_bytes().decode("utf-8")
        document = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        expected = copy.deepcopy(document)
        arrays = _array_spans(text)
        edits, found = [], set()
        for index, entity in enumerate(document.get("entities", [])):
            measures = entity.get("measures", [])
            deleted = {i for i, measure in enumerate(measures)
                       if (entity["name"].casefold(), measure["name"].casefold()) in targets}
            found.update((entity["name"].casefold(), measures[i]["name"].casefold()) for i in deleted)
            if not deleted:
                continue
            expected["entities"][index]["measures"] = [m for i, m in enumerate(measures) if i not in deleted]
            spans = arrays[("entities", index, "measures")]
            i = 0
            while i < len(spans):
                if i not in deleted:
                    i += 1
                    continue
                start = i
                while i + 1 in deleted:
                    i += 1
                end = i
                if end + 1 < len(spans):
                    edits.append((spans[start][0], spans[end + 1][0]))
                elif start > 0:
                    edits.append((spans[start - 1][1], spans[end][1]))
                else:
                    edits.append((spans[start][0], spans[end][1]))
                i += 1
        if found != targets:
            raise ValueError("Report deletion identity changed during staging.")
        for start, end in sorted(edits, reverse=True):
            text = text[:start] + text[end:]
        if json.loads(text) != expected:
            raise ValueError("Report deletion changed unrelated metadata.")
        path.write_bytes(text.encode("utf-8"))
    return {"ok": True, "deleted": len(entries)}
