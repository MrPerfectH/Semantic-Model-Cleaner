"""Read-only downstream projections. Never used to decide cleanup safety."""
from collections import defaultdict


class DependencyView:
    def __init__(self, items, graphs, identity, limitations=()):
        self.items = {identity(item): item for item in items}
        self.reverse = defaultdict(set)
        self.table_direct = defaultdict(set)
        for kind in ("measures", "columns", "metadata"):
            for source, targets in graphs.get(kind, {}).items():
                for target in targets:
                    if source in self.items and target in self.items:
                        self.reverse[target].add(source)
        for source, tables in graphs.get("tables", {}).items():
            if source in self.items:
                for table in tables:
                    self.table_direct[table.casefold()].add(source)
        self.coverage = {
            "status": "supported-references",
            "unresolvedCount": sum(len(refs) for refs in graphs.get("broken", {}).values()),
            "limitationCount": len(limitations),
            "note": "Includes all downstream measures reachable through resolved calculation references, including calculated columns. Unsupported or unresolved expressions can hide further dependencies. This list does not change cleanup safety.",
        }

    def _result(self, direct, exclude=()):
        seen = set(exclude)
        queue = list(direct - seen)
        reached = set(queue)
        while queue:
            target = queue.pop()
            for consumer in self.reverse.get(target, ()):
                if consumer not in reached and consumer not in seen:
                    reached.add(consumer)
                    queue.append(consumer)
        rows = []
        for key in reached:
            item = self.items[key]
            if item.item_type != "Measure":
                continue
            rows.append({
                "type": item.item_type, "table": item.table, "name": item.name,
                "sourceKind": item.source_kind, "sourceFile": item.source_file or None,
                "relationship": "Direct" if key in direct else "Indirect",
            })
        rows.sort(key=lambda row: (row["name"].casefold(), row["table"].casefold(), row["sourceFile"] or ""))
        return {"measures": rows, "totalCount": len(rows),
                "directCount": sum(row["relationship"] == "Direct" for row in rows),
                "coverage": self.coverage}

    def for_item(self, key):
        return self._result(self.reverse.get(key, set()), {key})

    def for_table(self, name):
        # A home table does not imply a dependency. Seed only actual table
        # references and references to columns contained in the selected table.
        direct = set(self.table_direct.get(name.casefold(), ()))
        for key, item in self.items.items():
            if item.source_kind == "model" and item.table.casefold() == name.casefold() and item.item_type in ("Column", "Calculated Column"):
                direct.update(self.reverse.get(key, ()))
        return self._result(direct)
