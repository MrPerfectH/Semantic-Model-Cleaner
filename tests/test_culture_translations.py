"""Culture translations are parsed structurally as per-object evidence (issue #93).

A translation is Translation Membership: concrete metadata evidence that keeps an
unused item at Review, like Perspective Membership. It is never an Analysis
Limitation and never a Report Reference. `linguisticMetadata` stays an Analysis
Limitation owned by its culture and never yields item references from its text.
"""
from pathlib import Path

import pytest

from semantic_model_cleaner import analyzer, webapp
from semantic_model_cleaner.tmdl_declarations import extract_culture_metadata

FIXTURE = Path(__file__).parent / "fixtures" / "calculation_group_dependencies"
MODEL = FIXTURE / "Models" / "Synthetic Dependencies.SemanticModel"
REPORT = FIXTURE / "Reports" / "Executive.Report"
CULTURE_FILE = "definition/cultures/pl-PL.tmdl"


@pytest.fixture(scope="module")
def results():
    return analyzer.analyze(FIXTURE, model_paths=[MODEL], report_paths=[REPORT])


@pytest.fixture(scope="module")
def payload(results):
    return webapp._serialize_results(results, model_paths=[str(MODEL)])


def row(results, table, name):
    return next(r for r in results["items"] if r["item"].table == table and r["item"].name == name)


def item(payload, table, name):
    return next(i for i in payload["items"] if i["table"] == table and i["name"] == name)


# ── Declaration scanning ─────────────────────────────────────────────────────

def test_translations_are_read_per_object_from_the_tmdl_grammar():
    text = (
        "culture pt-PT\n"
        "\ttranslations\n"
        "\t\tmodel Model\n"
        "\t\t\tcaption: Modelo\n"
        "\t\t\ttable Sales\n"
        "\t\t\t\tcaption: Vendas\n"
        "\t\t\t\tmeasure 'Sales Amount'\n"
        "\t\t\t\t\tcaption: Total de Vendas\n"
        "\t\t\t\t\tdisplayFolder: Métricas Base\n"
        "\t\t\t\tcolumn Product\n"
        "\t\t\t\t\ttranslatedDescription: Coluna\n"
        "\t\t\t\thierarchy 'Product Hierarchy'\n"
        "\t\t\t\t\tcaption: Hierarquia\n"
    )
    translations, linguistic = extract_culture_metadata(text)
    assert [(t.culture, t.table, t.name, t.kind, t.properties, t.line) for t in translations] == [
        ("pt-PT", "Sales", "", "table", ["caption"], 5),
        ("pt-PT", "Sales", "Sales Amount", "measure", ["caption", "displayFolder"], 7),
        ("pt-PT", "Sales", "Product", "column", ["description"], 10),
        ("pt-PT", "Sales", "Product Hierarchy", "hierarchy", ["caption"], 12),
    ]
    assert linguistic == []


@pytest.mark.parametrize("text", [
    # Names in descriptions and captions are values, not references.
    "culture pl-PL\n\ttranslations\n\t\tmodel Model\n\t\t\tdescription: Sales[Amount] and 'Targets'[Target]\n",
    # Comments are never declarations.
    "culture pl-PL\n\ttranslations\n\t\tmodel Model\n\t\t\t// table Sales\n\t\t\t/// measure Sales[Revenue]\n",
    # An object with no translated property carries no translation.
    "culture pl-PL\n\ttranslations\n\t\tmodel Model\n\t\t\ttable Sales\n\t\t\t\tmeasure Revenue\n",
    # Tables outside a translations block are not translations.
    "culture pl-PL\n\ttable Sales\n\t\tcaption: Sprzedaż\n",
    # Linguistic metadata JSON mentioning entities yields no translation.
    "culture pl-PL\n\tlinguisticMetadata =\n\t\t\t{\"Entities\": {\"sales.amount\": "
    "{\"Binding\": {\"ConceptualEntity\": \"Sales\", \"ConceptualProperty\": \"Amount\"}}}}\n"
    "\t\tcontentType: json\n",
])
def test_words_in_culture_text_never_produce_translations(text):
    translations, _ = extract_culture_metadata(text)
    assert translations == []


def test_linguistic_metadata_is_detected_with_culture_owner_and_line():
    translations, linguistic = extract_culture_metadata(
        "cultureInfo en-US\n\n\tlinguisticMetadata =\n\t\t\t{\n\t\t\t  \"Version\": \"1.0.0\"\n\t\t\t}\n"
        "\t\tcontentType: json\n")
    assert translations == []
    assert [(block.culture, block.line) for block in linguistic] == [("en-US", 3)]


# ── Analyzer evidence ────────────────────────────────────────────────────────

def test_translated_items_get_owner_culture_and_location(results):
    goal = row(results, "Sales", "Revenue Goal")
    assert goal["translations"] == [{
        "culture": "pl-PL", "owner": "Sales[Revenue Goal]", "kind": "measure",
        "properties": ["caption", "displayFolder"], "source_file": CULTURE_FILE, "line": 13}]
    region = row(results, "Sales", "Region")
    assert region["translations"][0]["owner"] == "Sales[Region]"
    assert region["translations"][0]["line"] == 18


def test_translation_is_a_review_trigger_with_exact_wording(results):
    region = row(results, "Sales", "Region")
    assert region["status"] == "NOT USED"
    assert region["removal_risk"] == "Review"
    assert (f"Translated in culture pl-PL ({CULTURE_FILE}:18). Removing the item also removes its "
            f"translation; a translation does not prove report use.") in region["review_triggers"]


def test_names_in_culture_descriptions_and_comments_produce_no_evidence(results):
    # Mentioned only in descriptions or comments of pl-PL.tmdl, or declared there
    # without any translated property.
    for table, name in [("Sales", "Amount"), ("Sales", "Order Date"), ("Targets", "Target"),
                        ("KPI Selector", "KPI Name"), ("Time Intelligence", "Ordinal"),
                        ("Sales", "Revenue Ignoring TI 01")]:
        evidence = row(results, table, name)
        assert evidence["translations"] == [], (table, name)
        assert not any("pl-PL" in trigger for trigger in evidence["review_triggers"]), (table, name)


def test_translations_are_not_analysis_limitations(results, payload):
    assert not any(limitation["area"] == "Cultures/translations" or "cultures/" in limitation["source_file"]
                   for limitation in results["analysis_limitations"])
    # Adding the culture file leaves the distinct limitation counts unchanged.
    assert payload["analysisLimitations"]["distinctCount"] == 7
    assert payload["analysisLimitations"]["sharedCount"] == 4
    goal = item(payload, "Sales", "Revenue Goal")
    assert goal["usageCount"] == 0  # a translation is never a Report Reference


def test_table_translation_is_a_table_signal(results):
    sales = next(t for t in results["table_summaries"] if t["name"] == "Sales")
    assert [t["owner"] for t in sales["translations"]] == ["Sales"]
    assert "Translated in culture pl-PL; a translation does not prove report use." in sales["signals"]
    targets = next(t for t in results["table_summaries"] if t["name"] == "Targets")
    assert targets["translations"] == []


def test_browser_payload_carries_translation_memberships(payload):
    assert item(payload, "Sales", "Revenue Goal")["translationMemberships"] == [{
        "culture": "pl-PL", "owner": "Sales[Revenue Goal]", "kind": "measure",
        "properties": ["caption", "displayFolder"], "sourceFile": CULTURE_FILE, "line": 13,
        "location": f"{CULTURE_FILE}:13"}]
    assert item(payload, "Sales", "Amount")["translationMemberships"] == []
    sales = next(t for t in payload["tables"] if t["name"] == "Sales")
    assert [(t["owner"], t["location"]) for t in sales["translations"]] == [("Sales", f"{CULTURE_FILE}:9")]


def test_json_export_lists_translation_cultures(results):
    import json
    exported = json.loads(analyzer.format_json_output(results))
    goal = next(i for i in exported["items"] if i["table"] == "Sales" and i["name"] == "Revenue Goal")
    assert goal["translations"] == ["pl-PL"]


@pytest.mark.parametrize("ui", ["classic", "v2"])
def test_both_layouts_explain_translation_membership_next_to_perspectives(ui):
    html = webapp.app.test_client().get("/?ui=" + ui).get_data(as_text=True)
    assert "{ label: 'Translation membership'" in html
    assert html.index("label: 'Perspective membership'") < html.index("label: 'Translation membership'")
    assert "item.translationMemberships" in html


def test_detail_workspace_renders_translation_evidence():
    script = webapp.app.test_client().get("/static/detail-workspace.js").get_data(as_text=True)
    assert "Translation membership — metadata evidence" in script
    assert "perspectiveCard + translationCard" in script
    assert "(table.translations || [])" in script


def test_linguistic_metadata_is_a_culture_owned_limitation_without_references(tmp_path):
    model = tmp_path / "Workspace" / "Models" / "Sales.SemanticModel"
    (model / "definition" / "tables").mkdir(parents=True)
    (model / "definition" / "cultures").mkdir(parents=True)
    (model / "definition" / "tables" / "Sales.tmdl").write_text(
        "table Sales\n\tmeasure Revenue = 1\n\tmeasure Margin = 1\n", encoding="utf-8")
    (model / "definition" / "cultures" / "en-US.tmdl").write_text(
        "cultureInfo en-US\n"
        "\tlinguisticMetadata =\n"
        "\t\t\t{\"Entities\": {\"sales.revenue\": {\"Binding\": {\"ConceptualEntity\": \"Sales\","
        " \"ConceptualProperty\": \"Revenue\"}}}, \"Note\": \"Sales[Margin]\"}\n"
        "\t\tcontentType: json\n",
        encoding="utf-8")
    pages = tmp_path / "Workspace" / "Reports" / "Executive.Report" / "definition" / "pages" / "Page 1"
    pages.mkdir(parents=True)
    (pages / "page.json").write_text('{"displayName":"Overview"}', encoding="utf-8")
    (pages.parents[2] / "definition.pbir").write_text(
        '{"datasetReference":{"byPath":{"path":"../../Models/Sales.SemanticModel"}}}', encoding="utf-8")
    results = analyzer.analyze((tmp_path / "Workspace").resolve())
    limitations = [l for l in results["analysis_limitations"] if l["area"] == "Cultures/translations"]
    assert len(limitations) == 1
    limitation = limitations[0]
    assert limitation["owner"] == "culture en-US"
    assert limitation["location"] == "definition/cultures/en-US.tmdl:2"
    assert limitation["targets"] == []
    assert limitation["scope"] == "targeted"
    assert "never treated as item references" in limitation["unchecked"]
    for name in ("Revenue", "Margin"):
        evidence = next(r for r in results["items"] if r["item"].name == name)
        assert evidence["removal_risk"] == "Safe"
        assert evidence["translations"] == []
