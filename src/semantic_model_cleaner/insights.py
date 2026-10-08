"""Read-only, bounded projections of analyzer evidence for people and agents.

Report locations come from the scanner, never from names guessed in expressions.
Graph identities retain report ownership. Traversals return one shortest evidence
path per consumer, not every possible path through a dependency diamond.
"""
from collections import Counter, defaultdict, deque
from dataclasses import replace
from pathlib import Path, PurePosixPath
import os

from . import analyzer


ITEM_TYPES = {"measure": "Measure", "column": "Column", "calculated-column": "Calculated Column"}


def relative(path, root):
    if not path:
        return ""
    try:
        return Path(os.path.relpath(Path(path).resolve(), root)).as_posix()
    except ValueError:  # Different Windows drives.
        return Path(path).resolve().as_posix()


def window(rows, limit=20, offset=0):
    if limit is None:
        limit = max(1, len(rows))
    return {"total": len(rows), "offset": offset, "limit": limit,
            "has_more": offset + limit < len(rows), "items": rows[offset:offset + limit]}


class QueryError(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def select_scope(project, model=None, reports=None, model_only=False):
    """New query commands use exact artifact paths relative to PROJECT."""
    root = Path(project).resolve()
    if not root.is_dir():
        raise QueryError("Project directory does not exist.")
    models = [(root / model).resolve()] if model else analyzer.discover_models([root])
    if len(models) != 1:
        raise QueryError("Select exactly one Semantic Model with --model PATH.",
                         models=window([relative(p, root) for p in models]))
    model = models[0]
    if not (model / "definition").is_dir():
        raise QueryError("The selected Semantic Model requires a TMDL definition directory.")
    if model_only and reports:
        raise QueryError("--model-only cannot be combined with --report.")
    explicit = sorted({(root / path).resolve() for path in reports or []})
    discovered = sorted(set(analyzer.discover_reports([root])) | set(explicit))
    bindings = analyzer.report_binding_scope(model, discovered)
    connected = {Path(row["path"]) for row in bindings["selected"]}
    selected = [] if model_only else (explicit if reports else sorted(connected))
    scope = {"model": relative(model, root), "reports": [relative(p, root) for p in selected],
             "known_connected_reports": len(connected), "selected_reports": len(selected),
             "selection_complete": not model_only and set(selected) == connected,
             "report_usage_checked": not model_only, "external_consumers_verified": False,
             "excluded_reports": [{"path": relative(row["path"], root),
                                    "reason": row["status"]} for row in bindings["excluded"]],
             "unverified_reports": sum(row["status"] != "not_connected" for row in bindings["excluded"])}
    scope["excluded_reports"] += [{"path": relative(p, root), "reason": "not_selected"}
                                  for p in sorted(connected - set(selected))]
    if any(path not in connected for path in selected):
        raise QueryError("Every --report path must exist and be connected to the selected Semantic Model.", scope=scope)
    if not selected and not model_only:
        raise QueryError("No connected Reports selected. Use --model-only to inspect model dependencies without Report usage.", scope=scope)
    return root, model, selected, scope


class Insights:
    def __init__(self, root, model, reports, scope):
        self.root, self.model, self.reports, self.scope = root, model, reports, scope
        self.result = analyzer.analyze(root, model_paths=[model], report_paths=reports,
                                       allow_model_only=not scope["report_usage_checked"])
        self.scope["scan_complete"] = self.result["coverage"]["complete"]
        self.rows = {analyzer.item_identity(row["item"]): row for row in self.result["items"]}
        self.graph = defaultdict(set)
        self.reverse = defaultdict(set)
        self.structural = defaultdict(list)
        self.tables = {}
        self.live = {key: list(row["usages"]) for key, row in self.rows.items()}
        # Only model-owned items define model tables (report extensions may use
        # unrelated entities with colliding names).
        self.children = defaultdict(set)
        for path in sorted((model / "definition/tables").glob("*.tmdl")):
            for node in analyzer.scan_tmdl_declarations(path.read_text(encoding="utf-8-sig")):
                if node.keyword == "table" and node.kind == "object" and node.parent is None:
                    self.tables[node.name.casefold()] = node.name
                    self.children.setdefault(node.name, set())
        for key, row in self.rows.items():
            item = row["item"]
            if item.source_kind == "model":
                self.tables[item.table.casefold()] = item.table
                self.children[item.table].add(key)
        for table in self.result["table_summaries"]:
            if table["name"].casefold() in self.tables:
                self.tables[table["name"].casefold()] = table["name"]
        graphs = self.result["dependency_graphs"]
        for key in self.rows:
            self.graph[key].update(graphs["measures"].get(key, set()) | graphs["columns"].get(key, set()))
            # The legacy item-derived index omits declared Tables without item
            # rows. Resolve their bare-table references using the same tokenizer.
            item = self.rows[key]["item"]
            table_refs = set(graphs["tables"].get(key, set()))
            if item.item_type in ("Measure", "Calculated Column"):
                table_refs.update(analyzer.dax_table_references(item.dax_body, self.tables))
            for name in table_refs:
                if name.casefold() in self.tables:
                    self.graph[key].add(self.table_key(self.tables[name.casefold()]))
        for table, children in self.children.items():
            for child in children:
                self.graph[child].add(self.table_key(table))
        self._structural_edges()
        for source, targets in self.graph.items():
            for target in targets:
                self.reverse[target].add(source)

    @staticmethod
    def table_key(name):
        return ("model", "Table", name, name)

    def identity(self, key):
        if key[1] == "Table":
            return {"type": "Table", "table": key[2], "name": key[2], "source": "model"}
        item = self.rows[key]["item"]
        out = {"type": item.item_type, "table": item.table, "name": item.name,
               "source": item.source_kind}
        if item.source_kind == "report":
            out["report_path"] = relative(Path(item.source_file).parent.parent, self.root)
        return out

    def _structural_edges(self):
        columns = defaultdict(list)
        for key, row in self.rows.items():
            item = row["item"]
            if item.source_kind == "model" and item.item_type in ("Column", "Calculated Column"):
                columns[analyzer.normalize_key(*item.key)].append(key)
                if item.is_key:
                    self.structural[key].append("Key column")
                for name in row.get("hierarchies", []):
                    self.structural[key].append("Hierarchy: " + name)
        hierarchy_refs = defaultdict(list)
        for usage in self.result["report_references"]:
            if usage.ref_type == "HierarchyLevel":
                hierarchy_refs[analyzer.normalize_key(usage.table, usage.name)].append(usage)
        for hierarchy in analyzer.parse_hierarchies(self.model):
            for usage in hierarchy_refs[analyzer.normalize_key(hierarchy.table, hierarchy.name)]:
                for column in hierarchy.columns:
                    for key in columns[analyzer.normalize_key(hierarchy.table, column)]:
                        self.live[key].append(replace(usage, context="Hierarchy: " + hierarchy.name))
        for key, row in self.rows.items():
            item = row["item"]
            if item.source_kind == "model" and item.sort_by_column:
                for target in columns[analyzer.normalize_key(item.table, item.sort_by_column)]:
                    self.graph[key].add(target)
                    self.structural[target].append("Sort column for " + analyzer.format_item_ref(item.key))
        for rel in analyzer.parse_relationship_details(self.model):
            for table, column in ((rel.from_table, rel.from_column), (rel.to_table, rel.to_column)):
                for key in columns[analyzer.normalize_key(table, column)]:
                    self.structural[key].append("Relationship: " + rel.name + (" (inactive)" if not rel.is_active else ""))
        for role, table, column in analyzer.parse_rls_roles(self.model):
            for key in columns[analyzer.normalize_key(table, column)]:
                self.structural[key].append("RLS role: " + role)

    def _paths(self, start, graph):
        paths = {start: ()}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for other in sorted(graph.get(current, ())):
                if other not in paths:
                    paths[other] = (other, *paths[current])
                    queue.append(other)
        return paths

    def _recommendation(self, key):
        row = self.rows[key]
        risk = row.get("removal_risk")
        # These queries recommend deleting one item at a time. Even an idle
        # dependent must be retained until a separate group deletion is reviewed.
        paths = self._paths(key, self.reverse)
        if any(self.live[consumer] or self.structural[consumer] for consumer in paths) or any(
                consumer in self.rows for consumer in self.reverse[key]):
            return "Blocked"
        if row.get("broken_dax_refs"):
            return "Review"
        if analyzer.is_used_status(row["status"]) or risk in {"Caution", "Do not remove"}:
            return "Blocked"
        if risk == "Safe" and (not self.scope["selection_complete"] or self.scope["unverified_reports"]):
            return "Review"
        return risk or "Review"

    def _base(self, limit=20, offset=0):
        return {"scope": self.scope, "limitations": window([
            {"id": row["id"], "feature": row["feature"], "owner": row["owner"],
             "message": row["message"]} for row in self.result["analysis_limitations"]], limit, offset)}

    def match(self, *, table=None, item=None, item_type=None, source="model", search=None):
        matches = []
        if item_type == "table":
            keys = [self.table_key(name) for name in self.tables.values()] if source != "report" else []
        else:
            keys = self.rows
        for key in keys:
            identity = self.identity(key)
            if source != "all" and identity["source"] != source:
                continue
            if table and identity["table"].casefold() != table.casefold():
                continue
            if item and identity["name"].casefold() != item.casefold():
                continue
            if item_type in ITEM_TYPES and identity["type"] != ITEM_TYPES[item_type]:
                continue
            if search and search.casefold() not in (identity["table"] + "[" + identity["name"] + "]").casefold():
                continue
            matches.append(key)
        return sorted(matches, key=lambda k: (k[2].casefold(), k[3].casefold(), k[1], k[0]))

    def items(self, *, limit=20, offset=0, used_in_reports=False, unused=False, **filters):
        matches = self.match(**filters)
        if unused:
            matches = [key for key in matches if key in self.rows
                       and self.rows[key]["status"] == "NOT USED"]
        if used_in_reports:
            if not self.scope["report_usage_checked"]:
                raise QueryError("--used-in-reports requires Report analysis; omit --model-only.")
            used = set()
            for key in self.rows:
                if self.live[key]:
                    used.update(self._paths(key, self.graph))
            matches = [key for key in matches if key in used]
        rows = []
        for key in matches[offset:offset + limit if limit is not None else None]:
            identity = self.identity(key)
            if key in self.rows:
                row = self.rows[key]
                identity.update(status=row["status"], cleanup=self._recommendation(key),
                                hidden=row["item"].is_hidden)
                identity["status_code"] = ("broken" if row["broken_dax_refs"] else
                    "unused" if row["status"] == "NOT USED" else
                    "indirect" if row["status"].startswith("INDIRECT") else "used")
                identity["via"] = [self.identity(consumer) for consumer in sorted(self.reverse[key])
                                   if consumer in self.rows]
            rows.append(identity)
        page = window(matches, limit, offset)
        page["items"] = rows
        return {**self._base(limit, offset), "items": page}

    def cleanup_groups(self, *, limit=20, offset=0):
        """Preview dead measure components; validate group deletion with existing policy."""
        from .cleanup_policy import _evaluate_deletion_policy
        live = set()
        for key in self.rows:
            if self.live[key] or self.structural[key]:
                live.update(self._paths(key, self.graph))
        dead = {key for key in self.rows if key[0] == "model" and key[1] == "Measure"
                and key not in live}
        components = []
        while dead:
            start = min(dead)
            component, queue = set(), [start]
            while queue:
                key = queue.pop()
                if key not in dead:
                    continue
                dead.remove(key)
                component.add(key)
                queue.extend((self.graph[key] | self.reverse[key]) & dead)
            components.append(sorted(component))
        rows = []
        for component in window(components, limit, offset)["items"]:
            actions = [{"action": "delete", "table": key[2], "name": key[3], "item_type": "Measure"}
                       for key in component]
            policy = _evaluate_deletion_policy(self.model, self.reports, actions, analysis=self.result)
            complete = self.scope["selection_complete"] and not self.scope["unverified_reports"]
            outside = sorted({consumer for key in component for consumer in self.reverse[key]
                              if consumer in self.rows and consumer not in component})
            rows.append({"items": [self.identity(key) for key in component], "actions": actions,
                         "cleanup": "Safe" if policy["ok"] and complete else "Review",
                         "violations": policy["violations"], "scope_complete": bool(complete),
                         "outside_consumers": [self.identity(key) for key in outside]})
        page = window(components, limit, offset)
        page["items"] = rows
        return {**self._base(limit, offset), "groups": page,
                "semantics": "Dead measure groups in selected local scope; preview only. Use a reviewed plan before deletion."}

    def _location(self, usage):
        artifact = usage.artifact_path.replace("\\", "/")
        parts = PurePosixPath(artifact).parts
        page_id = parts[parts.index("pages") + 1] if "pages" in parts and parts.index("pages") + 1 < len(parts) else ""
        return {"report": usage.report, "report_path": relative(usage.report_path, self.root),
                "page": usage.page, "page_id": page_id, "page_hidden": usage.page_hidden,
                "visual": usage.visual_title or usage.visual_id, "visual_id": usage.visual_id,
                "visual_type": usage.visual_type, "visual_hidden": usage.visual_hidden,
                "context": usage.context, "artifact_path": artifact, "source_path": usage.source_path}

    def usage(self, *, table=None, item=None, item_type=None, source="model", limit=20, offset=0,
              include_expression=False):
        if not item and not table:
            raise QueryError("Specify --item NAME, or --table NAME for whole-table usage.")
        if not item:
            if source != "model" or item_type not in (None, "table"):
                raise QueryError("Whole-table usage requires --source model and no item type.")
            item_type = "table"
        matches = self.match(table=table, item=item, item_type=item_type, source=source)
        if len(matches) != 1:
            message = ("Item not found. Use smc items --search TEXT to discover exact names." if not matches else
                       "Ambiguous item. Specify --table, --type, --source and/or an exact --report path.")
            raise QueryError(message, matches=window([self.identity(k) for k in matches], limit, offset), scope=self.scope)
        key = matches[0]
        paths = self._paths(key, self.reverse)
        locations, stale = [], []
        seen = set()
        for consumer, via in paths.items():
            row = self.rows.get(consumer)
            if not row:
                continue
            direct = consumer == key or (key[1] == "Table" and consumer in self.children[key[2]] and len(via) == 1)
            for stale_flag, usages in ((False, self.live[consumer]), (True, row["stale_usages"])):
                for usage in usages:
                    location = self._location(usage)
                    mode = ("field_parameter" if usage.context == "Field Parameter" else
                            "hierarchy" if usage.context.startswith("Hierarchy: ") else
                            "direct" if direct else "indirect")
                    signature = (stale_flag, consumer, *[str(v) for v in location.values()], mode)
                    if signature in seen:
                        continue
                    seen.add(signature)
                    location.update(kind=mode, item=self.identity(consumer), via=[self.identity(k) for k in via])
                    (stale if stale_flag else locations).append(location)
        order = lambda r: (r["report_path"], r["page_id"], r["page"], r["artifact_path"], r["source_path"], r["kind"], str(r["item"]))
        locations.sort(key=order)
        stale.sort(key=order)
        by_report = defaultdict(list)
        for location in locations:
            by_report[location["report_path"]].append(location)
        reports = [{"path": path, "name": refs[0]["report"], "pages": len({(r["page_id"] or r["page"]) for r in refs if r["page"] or r["page_id"]}),
                    "locations": len(refs)} for path, refs in sorted(by_report.items())]
        structural = [{"item": self.identity(k), "reason": reason} for k in paths
                      for reason in sorted(set(self.structural[k]))]
        dependents = [self.identity(k) for k in sorted(self.reverse[key]) if k in self.rows
                      and not (key[1] == "Table" and k in self.children[key[2]])]
        dependencies = [self.identity(k) for k in sorted(self.graph[key])
                        if not (k[1] == "Table" and key in self.children[k[2]])]
        used = bool(locations or structural or dependents)
        if locations:
            answer = f"Used in {len(reports)} Report(s), on {sum(r['pages'] for r in reports)} page(s)."
        elif structural or dependents:
            answer = "No live Report use found; retained model dependencies require this item."
        elif not self.scope["report_usage_checked"]:
            answer = "No model use found. Report usage has not been checked."
        else:
            answer = "No live usage found in the selected scope."
        if key[1] == "Table":
            cleanup = "Blocked" if used else ("Review" if not self.children[key[2]] or any(self._recommendation(k) != "Safe" for k in self.children[key[2]]) else "Safe")
            reasons = sorted({r for k in self.children[key[2]] for r in self.rows[k].get("review_triggers", [])})
        else:
            cleanup = self._recommendation(key)
            reasons = self.rows[key].get("review_triggers", [])
        details = {}
        if key in self.rows:
            item_data = self.rows[key]["item"]
            details = {"source_file": relative(item_data.source_file, self.root)}
            if include_expression:
                details["expression"] = item_data.dax_body
        return {**self._base(limit, offset), **details, "item": self.identity(key), "answer": answer,
                "used": used, "report_used": bool(locations) if self.scope["report_usage_checked"] else None,
                "cleanup": cleanup, "review_reasons": window(reasons, limit, offset),
                "counts": {"reports": len(reports), "pages": sum(r["pages"] for r in reports),
                           "live_locations": len(locations), "stale_locations": len(stale),
                           "direct_locations": sum(r["kind"] == "direct" for r in locations),
                           "indirect_locations": sum(r["kind"] != "direct" for r in locations)},
                "reports": window(reports, limit, offset), "locations": window(locations, limit, offset),
                "stale_locations": window(stale, limit, offset), "model_uses": window(structural, limit, offset),
                "dependents": window(dependents, limit, offset), "dependencies": window(dependencies, limit, offset),
                "path_semantics": "One shortest dependency path per consumer; not all possible paths."}

    def summary(self, *, limit=20, offset=0):
        report_items = defaultdict(set)
        report_direct = defaultdict(set)
        report_pages = defaultdict(set)
        for key, row in self.rows.items():
            if not self.live[key]:
                continue
            reachable = set(self._paths(key, self.graph))
            for usage in self.live[key]:
                path = relative(usage.report_path, self.root)
                report_items[path].update(reachable)
                if usage.context != "Field Parameter" and not usage.context.startswith("Hierarchy: "):
                    report_direct[path].add(key)
                location = self._location(usage)
                if location["page_id"] or location["page"]:
                    report_pages[path].add(location["page_id"] or location["page"])
        model_keys = {key for key in self.rows if key[0] == "model"}
        reports = []
        for path in self.reports:
            rel = relative(path, self.root)
            used = report_items[rel] & model_keys
            direct = report_direct[rel] & model_keys
            reports.append({"name": analyzer.report_display_name(path), "path": rel,
                            "pages_with_model_usage": len(report_pages[rel]),
                            "direct_model_items": len(direct), "indirect_model_items": len(used - direct),
                            "model_items": len(used), "tables": len({k[2] for k in report_items[rel] if k[1] == "Table"}),
                            "report_measures": len({k for k in report_items[rel] if k[0] != "model"})})
        tables = []
        for name, children in sorted(self.children.items()):
            owners = [path for path in self.reports if self.table_key(name) in report_items[relative(path, self.root)]]
            used = set().union(*(report_items[relative(path, self.root)] for path in owners)) & children
            tables.append({"name": name, "items": len(children), "items_used_by_reports": len(used),
                           "reports": len(owners),
                           "cleanup_candidates": sum(self._recommendation(k) == "Safe" for k in children)})
        cleanup = Counter(self._recommendation(k) for k in model_keys)
        return {**self._base(limit, offset), "model": {
            "tables": len(tables), "measures": sum(k[1] == "Measure" for k in model_keys),
            "columns": sum(k[1] in {"Column", "Calculated Column"} for k in model_keys),
            "items": len(model_keys), "reports": len(reports),
            "cleanup_candidates": cleanup["Safe"], "requires_review": cleanup["Review"],
            "required_items": cleanup["Blocked"],
            "broken_items": sum(bool(self.rows[k]["broken_dax_refs"]) for k in model_keys)},
            "reports": window(reports, limit, offset), "tables": window(tables, limit, offset)}


def compact_review(payload, limit=20, offset=0):
    """Keep check decisions, fingerprints and exit semantics; bound the display."""
    groups = defaultdict(list)
    for finding in payload.get("findings", []):
        groups[finding["rule_id"]].append(finding)
    labels = {"SMC001": "Broken model references", "SMC002": "Incomplete Report scans",
              "SMC003": "Analysis limitations", "SMC004": "Items with no use found",
              "SMC005": "Stale Report metadata", "SMC006": "Report reference issues",
              "SMC007": "Analyzer warnings", "SMC008": "Unverified Report bindings",
              "SMC009": "Naming suggestions", "SMC010": "Naming conflicts",
              "SMC011": "Invalid Report schema", "SMC012": "Unvalidated Report schema"}
    findings = sorted(payload.get("findings", []), key=lambda f: (f["suppressed"], f["severity"] != "error", f["rule_id"], f["fingerprint"]))
    return {"ok": payload["ok"], "scope": payload["scope"], "summary": payload["summary"],
            "errors": payload["errors"],
            "groups": [{"rule": rule, "label": labels.get(rule, rule), "count": len(rows),
                        "suppressed": sum(row["suppressed"] for row in rows)} for rule, rows in sorted(groups.items())],
            "findings": window(findings, limit, offset),
            "review_kind": "Existing static SMC checks; not the Tabular Editor BPA rule library."}
