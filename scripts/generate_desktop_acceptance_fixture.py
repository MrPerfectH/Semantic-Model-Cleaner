"""Create a Power BI Desktop acceptance copy of the richer analyzer fixture.

The original fixture intentionally includes invalid DAX, a missing Report
Reference and an inferred-column declaration that Desktop cannot deserialize.
This derivative removes those negative cases for an actual Desktop round trip.
It materializes the report-extension expressions as model measures for a local
Import model, so both reports have a valid native Desktop baseline.
"""
from pathlib import Path
import argparse
import json
from generate_ui_acceptance_fixture import generate_fixture


def generate_desktop_fixture(output):
    fixture = generate_fixture(Path(output))
    (fixture['model'] / 'definition/database.tmdl').write_text(
        'database SyntheticAcceptance\n\tcompatibilityLevel: 1604\n\tcompatibilityMode: powerBI\n',
        encoding='utf-8',
    )
    model = fixture['model'] / 'definition/model.tmdl'
    model.write_text(model.read_text(encoding='utf-8').replace(
        '\tculture: en-US', '\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US'
    ), encoding='utf-8')
    table = fixture['model'] / 'definition/tables/Sales.tmdl'
    text = table.read_text(encoding='utf-8').replace('\t\tisNameInferred\n', '')
    text = text.replace('[Missing Revenue] + 1', '0')
    text = text.replace("Owner's Region [Synthetic]", "Owner's Region Synthetic")
    table.write_text(text, encoding='utf-8')
    for report in fixture['reports']:
        extensions = report / 'definition/reportExtensions.json'
        if extensions.exists():
            metadata = json.loads(extensions.read_text(encoding='utf-8'))
            for entity in metadata['entities']:
                target = fixture['model'] / ('definition/tables/' + entity['name'] + '.tmdl')
                with target.open('a', encoding='utf-8') as stream:
                    for measure in entity['measures']:
                        name = measure['name'].replace("'", "''")
                        stream.write("\n\tmeasure '" + name + "' = " + measure['expression'] + '\n')
            extensions.unlink()
        for path in (report / 'definition/pages').rglob('visual.json'):
            visual = json.loads(path.read_text(encoding='utf-8'))
            values = visual['visual']['query']['queryState']['Values']['projections']
            values[:] = [entry for entry in values if entry.get('field', {}).get('Measure', {}).get('Property') != 'Missing Report Metric']
            visual['visual'].pop('objects', None)
            path.write_text(json.dumps(visual, indent=2), encoding='utf-8')
    return fixture


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    fixture = generate_desktop_fixture(parser.parse_args().output)
    print(json.dumps({key: str(value) if isinstance(value, Path) else list(map(str, value)) for key, value in fixture.items()}, indent=2))
