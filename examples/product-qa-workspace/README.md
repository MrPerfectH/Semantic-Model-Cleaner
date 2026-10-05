# Product QA Workspace

This directory contains a synthetic Power BI Project workspace for internal product QA.
It is safe to share publicly, but it is intentionally richer than the bundled demo
workspace at `src/semantic_model_cleaner/demo_workspace`.

Use it when checking trust-critical web workflows:

- Cleanup Recommendations: `Safe`, `Review`, and `Blocked`
- Report Health groups for stale Report References, broken model references and invalid PBIR JSON
- the separate Analysis limitations surface (the unreadable visual JSON is an analysis limitation,
  not a report-side repair)
- RLS `tablePermission` model-backed usage
- Report Extension Measures
- stale PBIR cleanup previews
- measure/table rename and move preview flows

Suggested commands:

```bash
semantic-model-cleaner examples/product-qa-workspace --format full
semantic-model-cleaner-web examples/product-qa-workspace
```

Highlights:

- `Sales[Cleanup Note]` has no use in scope but stays at Review because the unreadable visual JSON
  is a shared Analysis Limitation.
- `Sales[Perspective Revenue]` is a member of the Executive perspective. Membership is informational
  evidence (deleting the measure also removes the member); it is never a Review trigger. The measure
  is Review here only because of the same shared limitation, and would be Safe without it.
- `Store[Store Code]` is Blocked by RLS metadata.
- `Sales[Stale Margin]` appears only in stale PBIR metadata.
- `Sales[Broken Forecast]` has broken model references.
- `Report Metrics[Report Margin]` is a Report Extension Measure.
