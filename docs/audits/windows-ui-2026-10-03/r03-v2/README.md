# V2 layout: local browser verification on MSI

Ran against the R07 source worktree based on `7c145f3`, with the first-run changes present before commit. Local Microsoft Edge 153.0.4234.32, Playwright 1.55.0, isolated headless context at 1366×768. Disposable demo and separate user-state directory; no original project was opened. This is not packaged-EXE or human acceptance.

- Demo prepared the model/report selection without analysis. [Scope](01-v2-scope.png) shows one connected Report before explicit Analyze.
- Analyze produced nine items. Actual authenticated JSON and Excel downloads contained nine items and a valid workbook respectively. [Results](02-v2-results.png).
- Queued Hide for `Orders[Total Orders]`; the [review](03-v2-plan-review.png) showed the one-file change and validation. Closing the review preserved all original bytes. Reopening and applying changed the disposable model and refreshed results.
- Changes & history displayed the applied receipt. Review recovery exposed the confirmation action. [Recovery confirmation](04-v2-recovery-review.png).
- Restore original files completed and refreshed the analysis. All ten original files matched their pre-apply bytes. [Settled restored state](05-v2-restored.png).
- No browser page errors occurred. [Machine-readable result](result.json). All five captures were opened and inspected.

## Limits and follow-up

The existing v2 history differs from classic: there is no visible Verify files action, and Review recovery exposes a confirmation without fetching the classic restore preflight/diff. Recovery itself passed, but the review/verification parity needs assessment in R08/R10. Preview cancellation was tested; background-analysis cancellation was not. V2 policy save, packaged/offline behavior, actual Windows scaling and Power BI runtime equivalence remain unverified by this walkthrough.
