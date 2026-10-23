"""Saved DAX limitations must identify unsupported binding, not JSON damage."""
import pytest
from semantic_model_cleaner import analyzer
from semantic_model_cleaner.saved_dax import DaxCoverageError, query_references
from test_report_measure_delete import project
from test_report_measure_coverage import query


@pytest.mark.parametrize('text,reason', [
    ('DEFINE MEASURE Sales[Local] = (VAR X = 1 RETURN X) EVALUATE {[Local]}', 'inside nested delimiters'),
    ('EVALUATE VAR X = {1} RETURN X', 'VAR after EVALUATE'),
    ('DEFINE MEASURE Sales[Local] = 1 VAR X = {1} EVALUATE X', 'following DEFINE MEASURE'),
    ('EVALUATE TOPN(100, Sales)', 'standalone table or identifier binding: Sales'),
])
def test_precise_unsupported_binding_reason(text, reason):
    with pytest.raises(DaxCoverageError, match=reason):
        query_references(text)


def test_query_limitation_preserves_reason_and_does_not_claim_bad_json(tmp_path):
    model, reports = project(tmp_path)
    query(reports[0], 'EVALUATE TOPN(100, Sales)')
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    limitations = [v for v in result['coverage']['limitations'] if v['kind'] == 'unsupported_saved_dax_query']
    assert len(limitations) == 1
    limitation = limitations[0]
    assert limitation['feature'] == 'unsupported saved DAX query binding'
    assert 'standalone table or identifier binding: Sales' in limitation['message']
    assert 'standalone table or identifier binding: Sales' in limitation['unchecked']
    assert 'JSON' not in limitation['message'] + limitation['feature'] + limitation['unchecked']
    assert not result['coverage']['complete']
    assert all(r['removal_risk'] != 'Safe' for r in result['items'] if r['item'].source_kind == 'model')
