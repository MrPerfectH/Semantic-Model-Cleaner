# Changelog

## 0.1.4 - prepared public pre-release

- Prepare the initial public identity `MrPerfectH.semantic-model-cleaner`, retaining Preview.
- Document separate installation of the released 0.4.0b9 Python engine and the user-chosen executable path; no automatic installation or runtime changes.
- Add a manually dispatched Marketplace pre-release workflow. Publication remains a separate maintainer action.

## 0.1.3 — unpublished pre-release

- Restore the established Analysis Scope sidebar against the current engine.
- Keep the current results workspace with Compare and Classic retired.

## 0.1.2 — unpublished pre-release

- Move model and report selection into a native **Analysis Scope** sidebar.
  A sole model is selected automatically; several require an explicit choice.
  All connected reports are selected by default, with per-report checkboxes,
  select all/clear and a selected/total count.
- **Analyze** sends the exact selection, including zero reports (model-only).
  Unselected connected reports add an analysis limitation, so nothing is Safe.
- The editor shows results only, without the scope drawer, and marks results
  out of date (and inert) when the sidebar scope changes.
- Model and report choices survive Restart; another folder resets them.
- Fix a Windows hang: the engine no longer blocks subprocess launches (git build
  stamp) while watching the parent pipe, which left the editor blank.

## 0.1.1 — unpublished pre-release

- Add a Cleaner Activity Bar icon and native sidebar actions for Open Cleaner,
  Restart Server, Stop Server and Show Logs using the existing commands.
- Preserve Workspace Trust checks and existing server/security behavior.

## 0.1.0 — unpublished pre-release

- Wrap the existing local Python/UI in an owned desktop VS Code webview.
- Add trusted folder selection, restart/stop/log commands and status bar.
- Add explicit secure embedding protocol, per-instance readiness and cleanup.
- Adapt sandboxed confirmations without automatically analyzing or editing files.
