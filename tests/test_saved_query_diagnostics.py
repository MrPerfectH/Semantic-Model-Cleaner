"""Saved DAX limitations must identify unsupported binding, not JSON damage."""
import pytest
from semantic_model_cleaner import analyzer
from semantic_model_cleaner.saved_dax import DaxCoverageError, query_references
from test_report_measure_delete import project
from test_report_measure_coverage import query


@pytest.mark.parametrize('text,reason', [
    ('EVALUATE VAR X = 1', 'requires RETURN'),
    ('DEFINE VAR X = X EVALUATE X', 'Self or forward VAR binding'),
    ('EVALUATE SUMX(GENERATESERIES(1, 2), [Value])', 'Unsupported table schema binding'),
    ('EVALUATE FILTER(CROSSJOIN(ROW("V", 1), ROW("V", 2)), [V] > 0)', 'Ambiguous join column binding'),
])
def test_precise_unsupported_binding_reason(text, reason):
    with pytest.raises(DaxCoverageError, match=reason):
        query_references(text)


def test_query_limitation_preserves_reason_and_does_not_claim_bad_json(tmp_path):
    model, reports = project(tmp_path)
    query(reports[0], 'EVALUATE TOPN(100, Missing)')
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[reports[0]])
    limitations = [v for v in result['coverage']['limitations'] if v['kind'] == 'unsupported_saved_dax_query']
    assert len(limitations) == 1
    limitation = limitations[0]
    assert limitation['feature'] == 'unsupported saved DAX query binding'
    assert 'Unresolved table or identifier binding: Missing' in limitation['message']
    assert 'Unresolved table or identifier binding: Missing' in limitation['unchecked']
    assert 'JSON' not in limitation['message'] + limitation['feature'] + limitation['unchecked']
    assert not result['coverage']['complete']
    assert all(r['removal_risk'] != 'Safe' for r in result['items'] if r['item'].source_kind == 'model')
