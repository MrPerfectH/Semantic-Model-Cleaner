# Five-minute public beta quick start

Semantic Model Cleaner works on local Power BI Project folders. Use a Git
branch or a copy containing one TMDL `.SemanticModel` folder and one or more
connected PBIR `.Report` folders. It is free under the MIT license and needs
no Power BI Desktop, Fabric connection, account, or paid service.

## Windows

1. Open the [v0.4.0b1 prerelease](https://github.com/MrPerfectH/Semantic-Model-Cleaner/releases/tag/v0.4.0b1).
2. Download `semantic-model-cleaner-windows-x64-0.4.0b1.zip` and its
   `.sha256` file. Compare the ZIP's SHA-256 value with the sidecar.
3. Extract the complete ZIP and run `Semantic Model Cleaner.exe`.
4. Choose your repository folder, select one semantic model and its connected
   reports, then analyze.
5. Inspect the selected scope, warnings, dependencies, and exact diff before
   applying a reviewed change. Keep the receipt until recovery is no longer
   needed.

The beta is unsigned, so Windows may show a reputation prompt on first launch.

## Python

```bash
python -m pip install semantic_model_cleaner-0.4.0b1-py3-none-any.whl
smc /path/to/project --format full
smc-web /path/to/project
```

Open `http://127.0.0.1:5001` if the browser does not open automatically.

## Read-only CI

```yaml
- name: Check TMDL and PBIR
  run: smc check . --baseline smc-baseline.json --format json > smc-check.json
- name: Retain the evidence
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: semantic-model-cleaner-check
    path: smc-check.json
```

`smc check` returns 0 when the configured gate passes, 1 for policy findings,
and 2 for invalid input or execution errors. Baselines keep findings visible and
do not authorize deletion. See the [full CI contract](cli/check.md) and
[supported workflows](support.md).
