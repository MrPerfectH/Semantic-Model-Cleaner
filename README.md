# Semantic Model Cleaner

Analyze and clean up unused measures and columns in Power BI PBIR + TMDL projects.

## Quick start

```bash
git clone https://github.com/<you>/Semantic-Model-Cleaner.git
cd Semantic-Model-Cleaner
pip install -r requirements.txt
```

### Web App

```bash
python3 scripts/app.py
```

Open http://127.0.0.1:5001 — use the built-in file browser to select your `.SemanticModel` and `.Report` folders.

### CLI

```bash
python3 scripts/analyze_model_usage.py ~/Projects/MyProject --format full
```

The path argument is the folder containing your `.SemanticModel` and `.Report` directories — the tool finds them recursively. You can also pass explicit paths with `--models-path` and `--reports-path`.

See [scripts/analyze_model_usage.README.md](scripts/analyze_model_usage.README.md) for full documentation.
