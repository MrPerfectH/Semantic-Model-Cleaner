#!/usr/bin/env python3
"""Generate synthetic local PBIR/TMDL metadata into a NEW directory only.

No real business data is used. The caller owns cleanup of the generated directory.
"""
import argparse
import json
from pathlib import Path


def generate_fixture(output: Path, *, items: int = 2000, reports: int = 5,
                     pages_per_report: int = 10, visuals_per_page: int = 10) -> dict:
    if items not in (2000, 10000):
        raise ValueError("items must be 2000 or 10000")
    if not all(isinstance(value, int) and 1 <= value <= 100 for value in (reports, pages_per_report, visuals_per_page)):
        raise ValueError("Report/page/visual counts must each be between 1 and 100")
    output = Path(output)
    if output.is_symlink():
        raise ValueError("Output symlinks are not supported")
    output = output.resolve()
    if output.exists():
        raise ValueError("Output directory already exists; refusing to overwrite any files")
    # The exclusive mkdir also refuses racing creators and existing dangling links.
    output.mkdir(parents=True, exist_ok=False)
    table_count = items // 100
    model = output / "Scale.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (model / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}))
    (model / "definition/model.tmdl").write_text("model Model\n\tculture: en-US\n\n" +
        "\n".join(f"ref table Table{index:03d}" for index in range(table_count)) + "\n")
    for table_no in range(table_count):
        name = f"Table{table_no:03d}"
        lines = [f"table {name}"]
        for column in range(50):
            calculated = f" = {name}[Column{column - 1:02d}] * 2" if column >= 45 else ""
            lines += [f"\tcolumn Column{column:02d}" + calculated, "\t\tdataType: decimal"]
            if not calculated:
                lines += [f"\t\tsourceColumn: Column{column:02d}"]
        for measure in range(50):
            number = table_no * 50 + measure
            expression = f"SUM({name}[Column{measure:02d}])"
            if measure % 5:
                expression += f" + [Metric{number - 1:05d}]"
            lines += [f"\t/// Synthetic metric {number}; no business data.",
                      f"\tmeasure Metric{number:05d} = {expression}",
                      "\t\tformatString: #,0.00", "\t\tdisplayFolder: Benchmarks"]
        names = ", ".join(f'"Column{column:02d}"' for column in range(45))
        values = ", ".join("0" for _ in range(45))
        lines += [f"\tpartition {name} = m", "\t\tmode: import", "\t\tsource =",
                  "\t\t\tlet", f"\t\t\t\tSource = #table({{{names}}}, {{{{{values}}}}})",
                  "\t\t\tin", "\t\t\t\tSource"]
        (tables / f"{name}.tmdl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (model / "definition/relationships.tmdl").write_text("\n".join(
        f"relationship Relationship{index:03d}\n\tfromColumn: Table{index:03d}.Column00\n"
        "\ttoColumn: Table000.Column00\n\tfromCardinality: many\n\ttoCardinality: one\n"
        for index in range(1, table_count)))
    roles = model / "definition/roles"
    roles.mkdir()
    (roles / "Synthetic.tmdl").write_text("role Synthetic\n\tmodelPermission: read\n\ttablePermission Table001 = Table001[Column01] >= 0\n")
    for report_no in range(reports):
        report = output / f"Report{report_no:03d}.Report"
        for page_no in range(pages_per_report):
            page = report / "definition/pages" / f"Page{page_no:03d}"
            page.mkdir(parents=True)
            (page / "page.json").write_text(json.dumps({"name": page.name, "displayName": f"Page {page_no}", "displayOption": "FitToPage", "height": 720, "width": 1280}))
            for visual_no in range(visuals_per_page):
                table_no = (report_no * pages_per_report + page_no + visual_no) % table_count
                measure = (page_no * 5 + visual_no) % 50
                table = f"Table{table_no:03d}"
                names = [("Measure", f"Metric{table_no * 50 + measure:05d}"), ("Column", f"Column{measure:02d}")]
                projections = [{"field": {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}, "queryRef": f"{table}.{name}"} for kind, name in names]
                visual = page / "visuals" / f"Visual{visual_no:03d}"
                visual.mkdir(parents=True)
                (visual / "visual.json").write_text(json.dumps({"name": visual.name,
                    "position": {"x": visual_no * 10, "y": 0, "z": visual_no, "width": 300, "height": 200},
                    "visual": {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": projections}}}}}))
        (report / "definition/report.json").write_text(json.dumps({"themeCollection": {}, "layoutOptimization": "None"}))
        (report / "definition.pbir").write_text(json.dumps({"version": "4.0", "datasetReference": {"byPath": {"path": "../Scale.SemanticModel"}}}))
    return {"items": items, "tables": table_count, "measures": items // 2,
            "columns": items // 2, "calculated_columns": table_count * 5,
            "relationships": table_count - 1, "roles": 1, "reports": reports,
            "pages": reports * pages_per_report, "visuals": reports * pages_per_report * visuals_per_page,
            "files": sum(path.is_file() for path in output.rglob("*"))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory; existing directories are always rejected")
    parser.add_argument("--items", type=int, choices=(2000, 10000), default=2000)
    parser.add_argument("--reports", type=int, default=5)
    parser.add_argument("--pages", type=int, default=10)
    parser.add_argument("--visuals", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        result = generate_fixture(args.output, items=args.items, reports=args.reports,
                                  pages_per_report=args.pages, visuals_per_page=args.visuals)
        print(json.dumps({"ok": True, "fixture": result}, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
