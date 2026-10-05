# Semantic Model Cleaner release readiness review

Reviewed on 2026-10-02 at checkout `6d29ce2`, version `0.4.0b2`, on Windows with Python 3.13. The goal is a broader public launch next week. The user confirmed Power BI developers on Windows as the primary audience; CLI automation and AI coding agents remain supported secondary workflows.

The follow-up [implementation plan and session-sized ticket drafts](../plans/windows-public-beta/README.md) translate this audit into ordered work. These findings describe the audited revision; they are not marked fixed by the existence of the plan.

**Recommendation: prepare a focused public beta after addressing the launch blockers below.** The shared change-plan engine is a useful foundation. The highest priorities are protecting ordinary exports, correcting Windows text handling, protecting local HTTP operations, and making report selection consistent. Additional large features would compete with this work.

This is a source, CLI, API, and release-documentation review. Visual verification is incomplete: the T3 shared browser reported a Linux runtime and could not reach the Windows loopback server. Local HTTP returned 200, but browser navigation returned connection refused; environment-port navigation also failed. No product screenshots were accepted. UI findings below are explicitly implementation findings or design proposals, not observations of rendered screens. The packaged EXE and Power BI runtime behavior were not tested in this review.

## What already works well

- CLI and UI share staged plans, exact differences, source fingerprints, apply receipts, and guarded restore.
- A fresh disposable copy passed `plan`, `diff`, `apply`, `verify`, and `restore`. All original project file bytes matched after recovery.
- `smc check` already offers versioned JSON, finding fingerprints, baselines, selected-scope evidence, and meaningful exit codes. These are valuable foundations for CI and AI agents.
- Analysis distinguishes usage evidence, report health, unsupported metadata, and cleanup recommendations. This is more useful than simply counting textual references.
- A bundled demo, support matrix, public issue templates, checksums, and separate downloaded-package verification already exist. Avoid spending the launch week recreating these capabilities.
- Inventory pagination, configurable columns, object tabs, a native change-review dialog, and Changes & history are already implemented.

## Launch blockers

| Priority | Confirmed finding | Consequence | Required outcome |
| --- | --- | --- | --- |
| P1 | Analysis export can overwrite selected source metadata | A command presented as analysis can destroy the model without a reviewed plan or receipt | Reject output inside discovered or selected model/report artifacts, including resolved aliases; preserve source bytes on rejection |
| P1 | UTF-8 operations JSON is decoded using the Windows locale | Valid non-English text can silently become corrupted text in a successful plan | Read operations explicitly as UTF-8, with an intentional BOM policy; verify non-ASCII operations end to end |
| P1 | Local API lacks Host and cross-origin mutation protection | Requests outside the intended UI context can reach filesystem and apply operations | Validate trusted local hosts and request origin; protect mutation endpoints with a per-launch token or equivalent protection |
| P1 | Ordinary analyzer selects unrelated reports while `check` excludes them | UI, CI, and analyzer output can disagree about what uses the model | Share connected-report selection and report exclusions across command families |
| P1 | Python web launcher crashes with a non-UTF-8 stdout | Windows automation or redirected startup can fail before the server starts | Handle output encoding consistently across all entry points |

**Export reproduction.** On a disposable bundled-demo copy, `smc <copy> --format json -o <copy>/Models/TestModel.SemanticModel/definition/tables/Sales.tmdl` exited 0 and replaced TMDL with the JSON analysis. Source: [analyzer.py](../../src/semantic_model_cleaner/analyzer.py), `main`, approximately lines 5638–5655. Audit both text/JSON and Excel output paths. The protected plan and baseline output paths are useful precedents.

**Unicode reproduction.** A UTF-8 operations file requested display folder `Zażółć`. With `PYTHONUTF8=0` on this machine, `smc plan` exited 0 but the saved operation contained the character sequence `Za\u00c5\u00bc\u00c3\u00b3\u00c5\u201a\u00c4\u2021`. This demonstrates silent corruption, not just a display problem. Source: [plan_cli.py](../../src/semantic_model_cleaner/plan_cli.py), line 47, calls `read_text()` without an encoding. Check other user-authored JSON readers too. Generated plans generally escape Unicode, so this finding specifically concerns input decoding rather than every saved JSON file.

**HTTP reproduction.** Flask's test client accepted `GET /api/browse` with `Host: untrusted.example` and an unrelated Origin, returning directory information. It also accepted a form POST with a cross-site Origin and `Sec-Fetch-Site: cross-site` to the apply URL of a known, locally created test plan. The response was 200 with an applied receipt; the disposable project was then restored. `TRUSTED_HOSTS` was unset and no before-request guards were registered. Sources: [webapp.py](../../src/semantic_model_cleaner/webapp.py), app creation, `api_browse`, and `api_plan_operation`.

The test proves missing application-side checks. It does not prove a complete browser exploit: plan-ID knowledge and browser networking restrictions affect exploitability. Loopback remains the right default. The README's `--host 0.0.0.0` example also deserves removal or explicit treatment as an unsupported exposure until access control is designed. Flask documents [Host validation and request security](https://flask.palletsprojects.com/en/stable/web-security/).

**Report-selection reproduction.** Adding `Unrelated.Report` with a binding to `Different.SemanticModel` made ordinary analyzer JSON list both `TestReport` and `Unrelated`. `smc check` selected only `TestReport` and reported the other as `not_connected`. Source: [analyzer.py](../../src/semantic_model_cleaner/analyzer.py), approximately lines 5606–5633; compare `ci.run_check` and `filter_reports_bound_to_model`. This can contaminate reference counts and retention decisions; this review did not demonstrate deletion of a required item through this discrepancy.

**Startup reproduction.** `.venv/Scripts/python.exe -m semantic_model_cleaner.web examples/product-qa-workspace --port 5097` raised `UnicodeEncodeError` in `print_startup_banner`, line 398. `PYTHONUTF8=1` allowed startup and local HTTP checks. [windows_launcher.py](../../src/semantic_model_cleaner/windows_launcher.py) already configures console output, so the result must not be generalized to the packaged EXE.

## Windows verification gap

The full suite produced **694 passed, 13 failed, 4 skipped** in 70.83 seconds. Ruff passed. Re-running only the 13 failures with UTF-8 enabled produced **9 passed and 4 failed**:

- Nine failures were source-file decoding errors in tests reading JavaScript without an explicit encoding.
- Two remaining tests require Windows symlink privileges unavailable to this process.
- One assumes `Path('/Users')` serializes with POSIX separators.
- One indexes a snapshot with a POSIX path although the snapshot uses platform-native separators.

These are not 13 proven runtime defects. They do show that default Windows execution is not covered well enough. The primary test matrix is Ubuntu-only; the Windows release workflow provides separate package/browser smokes, which should be retained. Add a Windows unit-test lane, explicit fixture encodings, normalized logical paths, and capability-aware symlink tests without losing privileged symlink coverage elsewhere.

## CLI and AI usability

The existing CLI is substantial. Its discovery and consistency lag behind its capabilities.

| Finding | Evidence | Improvement |
| --- | --- | --- |
| Main help hides most commands | `smc --help` exposes analyzer options and mentions only `clean-stale`; dispatch also supports check, plans, recovery, policy, and naming | A top-level command directory with short examples and preserved legacy invocation |
| No standard version flag | `smc --version` exits 2 as an unknown argument | Add version/build output for support reports and agent capability checks |
| Scope flags change meaning | Analyzer `--model` is a substring; check uses a project-relative artifact path; plan uses an exact path relative to the process directory | Use consistent exact-path flags and separate name-filter flags; document migration compatibility |
| JSON contracts differ | Analyzer JSON has no top-level schema version; missing-path JSON mode prints plain stderr and exits 1; check uses a versioned error envelope and exit 2 | Extend the check contract across commands; stabilize stdout/stderr and error codes |
| Operations require reading prose | Plan accepts arbitrary JSON parsed into the operation engine | Publish a machine-readable operations schema with examples and explicit supported capabilities |

For next week, prioritize help, version, consistent errors, and one documented agent workflow: inspect scope, run `check`, prepare operations, create a plan, inspect differences and limitations, apply only an approved plan, then verify. Agent examples should treat model names, DAX, and annotations as data, not instructions. Existing check fingerprints and plan digests should remain the basis of traceability.

Useful follow-ups are compact item-level explain output, filtered JSON queries, a capability/schema command, and SARIF output. An MCP adapter can follow the stable CLI contract. An embedded AI chat or autonomous cleanup service would add a separate product and trust problem during an already short release window.

## User experience and appearance

These findings come from source inspection. A browser walkthrough at laptop sizes and Windows display scaling remains a release requirement.

**Make the first run explain the value before asking for folder decisions.** The v2 layout automatically opens the scope drawer before analysis; the demo button is inside that setup area. The welcome screen separately asks for model/report selection. Proposed first screen: one sentence explaining the outcome, a primary “Open Power BI project” action, and a clearly visible “Try demo” action. Discover the model and connected reports automatically, then ask users to resolve ambiguity or review exclusions. Keep manual paths as an advanced route. Sources: [index_v2.html](../../src/semantic_model_cleaner/templates/index_v2.html), welcome card, setup drawer, and final `smcSync` initialization.

**Make the scan result a decision starting point.** Proposed first result: selected model, reports checked, coverage limitations, cleanup candidates, and broken-reference count, followed by a clear next action. Existing inventory, dependencies, report health, and object tabs can support this. Do not collapse “unused,” “Safe,” and “fully validated” into one promise. Prefer visible wording such as “Candidate in selected scope,” with the exact reason one click away. The glossary currently gives “Safe” a narrower meaning than a first-time user may infer.

**Simplify launch-facing controls and copy.** The app exposes a Classic layout switch and build stamp, and the beta banner says stable users should use standard releases. The landing page calls `0.4.0b2` the current public beta but also recommends stable releases as the default. Use one clear recommended download and describe available versions precisely. Move build details and layout compatibility controls into About or settings. The current public [release page](https://github.com/MrPerfectH/Semantic-Model-Cleaner/releases/tag/v0.4.0b2) identifies this version as a prerelease; this review did not establish that no other release exists.

**Improve small text and keyboard behavior.** The template uses 10–12px supporting text and a faint `#94a3b8` token on light surfaces. This deserves contrast and readability verification. The scope drawer is an `aside` translated offscreen; its open/close functions only change a body class, with no focus transfer, focus restoration, or inert handling in those functions. Use a native modal dialog or complete equivalent semantics. Verify closed controls are removed from keyboard navigation, Escape closes the correct layer, and focus returns to the trigger. The native change-review dialog is already a better local pattern.

**Bundle typography if offline use is a product promise.** Both the app and landing page request Google Fonts. Local fallbacks exist, so this is not proof of an offline failure. Bundling fonts would make appearance more predictable and remove an unnecessary third-party request from the local tool.

**Show the actual product on the landing page.** Lead with a current screenshot and a short demonstration of selection, explanation, preview, and recovery. The present page spends substantial space on release channels. Show the CLI as a supported user workflow rather than describing it mainly as a contributor path. Explain the supported PBIR/TMDL input formats immediately; provide a short path for users starting with PBIX.

## Flow coverage

| Step | Task | Health and evidence |
| --- | --- | --- |
| 1 | Install and launch | Python web startup defect reproduced; packaged EXE not exercised |
| 2 | Select project and reports | Scope inconsistency reproduced through CLI; drawer reviewed in code; visual interaction blocked |
| 3 | Analyze and understand findings | Analyzer/check exercised; evidence and classification code reviewed; visual comprehension untested |
| 4 | Inspect an item and prepare a change | Plan preparation and exact diff succeeded on a synthetic project; item UI reviewed in code |
| 5 | Apply and verify | Successful disposable CLI round trip; HTTP origin-protection gap reproduced with test client |
| 6 | Restore | Byte-exact recovery succeeded; Windows interrupted-lock recovery remains a documented manual workflow |

No screenshot of a failed connection is presented as product evidence. Full keyboard, screen-reader, zoom, responsive, and visual review remains outstanding.

## Maintenance priorities after launch

The two main HTML templates contain 7,061 and 7,253 lines, respectively. The analyzer is approximately 233 KB, and the v2 template approximately 377 KB. Several static scripts extend or replace globally defined UI functions. This increases the chance that a fix works in one layout but regresses another. Consolidate shared rendering and behavior incrementally after the release; avoid a framework migration this week.

Global server state also warrants explicit multi-tab behavior tests, particularly analysis/export scope. Plan locking is journal-directory-specific, and Windows interrupted-lock recovery requires manual verification and removal. These are documented limitations, but a friendlier recovery workflow and shared lock ownership would be valuable follow-ups. No concurrency corruption was reproduced in this review.

For additional usefulness, prioritize a redacted support bundle, a compact shareable cleanup report, and change-over-time reporting against a saved baseline. Validate demand before adding cloud integrations. A support bundle should omit expressions, private paths, and credentials by default and allow inspection before sharing.

## Proposed launch week

| Day | Focus | Acceptance condition |
| --- | --- | --- |
| 1 | Export protection and UTF-8 operations | Disposable negative cases leave source bytes unchanged; non-English names round-trip exactly |
| 2 | Local API protection and unified scope | Legitimate UI works; foreign-origin mutations fail; analyzer/check/plan select the same connected reports |
| 3 | Windows startup and CI portability | Default Windows launch works; Windows and Ubuntu tests pass with intentional capability skips |
| 4 | First-run clarity and focused visual polish | New users can open/demo, identify scope, inspect one finding, and locate recovery without coaching; verify keyboard and 125/150 percent scaling |
| 5 | CLI help, errors, and automation documentation | A human or agent can discover commands and complete a documented reviewed change without guessing flag semantics |
| 6 | Release candidate verification | Download the actual built ZIP on a clean Windows environment; verify checksum, launch, analyze, export, apply, stale-plan refusal, and restore; open changed synthetic project in Power BI |
| 7 | Buffer and release decision | Address feedback, capture final screenshots, publish accurate notes and support links; launch only when the blockers are resolved |

This schedule is a proposed scope, not a completion estimate. If fixes expand, reduce optional polish or narrow the release to analysis-only until mutation paths meet the release criteria. Keep calculation-group and dynamic-reference limitations visible. Do not promise runtime equivalence from static checks.

All mutation reproductions used newly created temporary synthetic copies. No original Power BI project files were changed by this review. Exploratory application edits started afterward were removed when the user requested planning first; the intended changes are this report and the linked plan/ticket documents.
