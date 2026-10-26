"""Deletion owns only the documentation immediately attached to its declaration."""
import pytest

from semantic_model_cleaner import change_plan as plans
from semantic_model_cleaner.tmdl_writer import delete_item


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("final_newline", [False, True])
@pytest.mark.parametrize("kind", ["measure", "column"])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_delete_owned_description_preserves_retained_bytes(
    tmp_path, ending, final_newline, kind, position
):
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    blocks = []
    for i in range(3):
        declaration = (
            f"\tmeasure 'Item {i}' = 1"
            if kind == "measure" else f"\tcolumn 'Item {i}'"
        )
        blocks.append(
            f"\t/// Description {i}\n\t/// second line {i}\n"
            f"{declaration}\n\t\tformatString: 0\n"
        )
    # A retained expression comment/string, unrelated comment and detached ///
    # must survive; indentation keeps expression text out of declaration docs.
    prefix = (
        "/// Table description\ntable 'Quoted Table'\n"
        "\tmeasure Keep =\n\t\t\"/// literal\"\n"
        "\t\t/// expression comment\n"
        "\t// unrelated comment\n\t/// detached comment\n\n"
    )
    if not final_newline:
        blocks[-1] = blocks[-1].rstrip("\n")
    text = prefix + "".join(blocks)
    path = tables / "Quoted Table.tmdl"
    encode = lambda value: value.replace("\n", ending).encode("utf-8")
    path.write_bytes(encode(text))
    result = delete_item(model, "Quoted Table", f"Item {position}", kind)
    assert result["ok"], result
    assert path.read_bytes() == encode(text.replace(blocks[position], "", 1))


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
@pytest.mark.parametrize("final_newline", [False, True])
def test_described_whole_table_removal_preserves_model_bytes(tmp_path, ending, final_newline):
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    path = tables / "Gone.tmdl"
    path.write_bytes(
        ("/// Table docs\n/// More table docs\ntable 'Gone Table'\n"
         "\t/// Item docs\n\tmeasure 'Last Item' = 1\n").replace("\n", ending).encode()
    )
    model_file = model / "definition/model.tmdl"
    retained = "model Model\n\tculture: en-US\n\nref table Keep"
    if final_newline:
        retained += "\n"
    original = retained.replace("ref table Keep", "ref table 'Gone Table'\nref table Keep")
    model_file.write_bytes(original.replace("\n", ending).encode())
    result = delete_item(model, "Gone Table", "Last Item", "measure")
    assert result["ok"] and result["table_deleted"], result
    assert not path.exists()
    assert model_file.read_bytes() == retained.replace("\n", ending).encode()


def test_described_table_fragment_does_not_consume_next_table_docs(tmp_path):
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    path = tables / "fragments.tmdl"
    neighbor = b"/// Neighbor docs\n/// second line\ntable Neighbor\n\tmeasure Kept = 3"
    path.write_bytes(
        b"/// Gone docs\ntable Gone\n\t/// Last docs\n\tmeasure Last = 1\n\n"
        + neighbor
    )
    result = delete_item(model, "Gone", "Last", "measure")
    assert result["ok"] and result["table_deleted"], result
    assert path.read_bytes() == neighbor


def test_supported_plan_deletes_described_whole_table_and_restores(tmp_path):
    model = tmp_path / "M.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    (tables / "Keep.tmdl").write_bytes(b"table Keep\n\tmeasure Kept = 2\n")
    removed = tables / "Gone.tmdl"
    removed.write_bytes(
        b"/// Owned table description\n/// second line\ntable Gone\n"
        b"\t/// Owned measure description\n\tmeasure Last = 1\n"
    )
    (model / "definition/model.tmdl").write_bytes(
        b"model Model\n\tculture: en-US\n\nref table Gone\nref table Keep\n"
    )
    original = {p: p.read_bytes() for p in model.rglob("*") if p.is_file()}
    report = tmp_path / "R.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition/report.json").write_text("{}", encoding="utf-8")
    (report / "definition.pbir").write_text(
        '{"datasetReference":{"byPath":{"path":"../M.SemanticModel"}}}', encoding="utf-8"
    )
    plan = plans.create_plan(model, [report], [{
        "kind": "actions", "actions": [{
            "action": "delete", "table": "Gone", "name": "Last", "item_type": "Measure"
        }]
    }])
    assert {p: p.read_bytes() for p in model.rglob("*") if p.is_file()} == original
    assert plans.apply_plan(plan, tmp_path / "journal")["ok"]
    assert not removed.exists()
    assert plans.verify_plan(plan)["ok"]
    assert plans.restore_plan(plan, tmp_path / "journal")["ok"]
    assert {p: p.read_bytes() for p in model.rglob("*") if p.is_file()} == original

@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
@pytest.mark.parametrize("final_newline", [False, True])
def test_table_ref_deletion_preserves_every_retained_byte(tmp_path, ending, final_newline):
    from semantic_model_cleaner.tmdl_writer import _delete_table_ref_from_model

    definition = tmp_path / "definition"
    definition.mkdir()
    path = definition / "model.tmdl"
    before = b"model Model\n\tculture: en-US\n\nref table 'Gone Table'\nref table Keep"
    before = before.replace(b"\n", ending) + (ending if final_newline else b"")
    path.write_bytes(before)
    assert _delete_table_ref_from_model(tmp_path, "Gone Table")
    assert path.read_bytes() == before.replace(b"ref table 'Gone Table'" + ending, b"")
    unchanged = path.read_bytes()
    assert not _delete_table_ref_from_model(tmp_path, "Absent")
    assert path.read_bytes() == unchanged
