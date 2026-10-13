"""Repository discovery must include every visible model, not only Models/."""
from semantic_model_cleaner import analyzer


def test_conventional_models_folder_does_not_hide_other_repository_models(tmp_path):
    primary = tmp_path / 'Models' / 'Primary.SemanticModel'
    nested = tmp_path / 'Department' / 'Secondary.SemanticModel'
    hidden = tmp_path / '.worktrees' / 'Hidden.SemanticModel'
    for model in (primary, nested, hidden):
        (model / 'definition').mkdir(parents=True)
        (model / 'definition' / 'model.tmdl').write_text('model Model\n')
    assert set(analyzer.discover_models([tmp_path])) == {primary, nested}
