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


def test_discovery_does_not_recheck_pruned_ancestors_for_every_directory(tmp_path, monkeypatch):
    model = tmp_path / 'M.SemanticModel'
    model.mkdir()
    for index in range(40):
        (tmp_path / 'R.Report' / 'definition/pages' / str(index) / 'visuals/V').mkdir(parents=True)
    calls = []
    original = analyzer._skip_discovery_path
    monkeypatch.setattr(analyzer, '_skip_discovery_path', lambda *a, **kw: calls.append(1) or original(*a, **kw))
    assert analyzer.discover_models([tmp_path]) == [model]
    assert len(calls) <= 3, 'Once ancestors are pruned, discovery should filter directory names directly'
