"""The UI header must not show a misleading commit for installed copies."""
from semantic_model_cleaner import __version__, webapp


def test_build_stamp_is_version_only_without_a_source_checkout(monkeypatch, tmp_path):
    fake_module = tmp_path / "lib" / "site-packages" / "semantic_model_cleaner" / "webapp.py"
    fake_module.parent.mkdir(parents=True)
    monkeypatch.setattr(webapp, "__file__", str(fake_module))
    assert webapp._build_stamp() == f"v{__version__}"
