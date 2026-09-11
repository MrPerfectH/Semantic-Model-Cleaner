import json

from semantic_model_cleaner import analyzer


def test_legacy_report_json_is_unsupported_and_never_safe(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tmeasure Revenue = 1\n\tcolumn Spare\n')
    report = tmp_path / 'Legacy.Report'
    report.mkdir()
    # Even a coincidentally recognizable reference shape must not make this
    # unsupported legacy representation look like a complete PBIR scan.
    (report / 'report.json').write_text(json.dumps({'Column': {
        'Expression': {'SourceRef': {'Entity': 'Sales'}}, 'Property': 'Spare'}}))
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert not result['coverage']['complete']
    assert len(result['report_issues']) == 1
    issue = result['report_issues'][0]
    assert issue['issueType'] == 'unsupported_report_format'
    assert issue['severity'] == 'error'
    assert issue['reportPath'] == str(report.resolve())
    assert result['coverage']['limitations'][0]['kind'] == 'unsupported_report_format'
    assert all(row['removal_risk'] == 'Review' for row in result['items'])
    assert result['summary']['total_usage_refs'] == 0


def test_missing_definition_without_legacy_file_is_also_incomplete(tmp_path):
    model = tmp_path / 'M.SemanticModel'
    tables = model / 'definition/tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text('table Sales\n\tcolumn Spare\n')
    report = tmp_path / 'Incomplete.Report'
    report.mkdir()
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    assert result['coverage']['limitations'][0]['source_file'] == 'definition/'
    assert result['items'][0]['removal_risk'] == 'Review'
