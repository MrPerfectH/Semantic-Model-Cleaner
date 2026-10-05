# Classic layout: local browser verification on MSI

Source revision: `7c145f3`. Machine: MSI Summit E15 A11SCST. Browser: local Microsoft Edge 153.0.4234.32, driven with Playwright 1.55.0 in an isolated headless context at 1366×768. The user explicitly authorized local browser automation. This is a source-app run, not a Windows ZIP test or human visual acceptance.

The app used a disposable empty project and separate user-state directory. The browser loaded the real classic page and operated visible controls; the protected API was not substituted or mocked. No original Power BI Project was opened or changed.

1. **Start — works, crowded setup.** The classic layout exposes model/report controls and a demo button. [Start capture](01-classic-start.png).
2. **Demo and analysis — works.** The demo immediately analyzes; nine items appear. This skips a deliberate pre-analysis scope review, addressed by R07. [Analyzed capture](03-classic-results.png). JSON and Excel buttons triggered actual authenticated blob downloads: JSON contained nine items and Excel contained a workbook.
3. **Prepare and review — works.** Selected `Orders[Total Orders]`, queued Hide, and chose Apply (1). The review showed the exact one-file diff before any source change. [Review capture](04-classic-plan-review.png).
4. **Apply and verify — works.** Apply reviewed changes changed the disposable model; Changes & history → Verify files reported `applied`.
5. **Review restore — works.** The original bytes and diff were available before confirmation. [Restore review](05-classic-restore-review.png).
6. **Restore — works.** Restore reviewed original files completed. All ten original project files matched the pre-change byte snapshot, with no extra project files at that point. [Restored capture](06-classic-restored.png).
7. **Review policy — works.** Saved a disposable Keep decision with owner, reason and expiry through the rendered policy dialog. The policy file was created; all original model/report bytes remained unchanged.

No browser page errors occurred. Machine-readable results are in [result.json](result.json). Accepted screenshots were opened and inspected; transient loading screenshots were excluded.

## Remaining checks and observations

- R03 still needs the current v2 lifecycle and rendered cancellation evidence; no claim that its full browser checklist is complete.
- Packaged EXE, offline behavior, Power BI runtime equivalence, screen-reader behavior and actual OS scaling were not tested here.
- After restore, the classic table later displayed `Pending: Hide` for the restored item. This is an observed queue-state clarity issue for R08 to reproduce and assess; the byte restoration itself passed. No additional source change was applied.
