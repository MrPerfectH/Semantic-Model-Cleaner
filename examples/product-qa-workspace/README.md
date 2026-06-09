# Product QA Workspace

This directory contains a synthetic Power BI Project workspace for internal product QA.
It is safe to share publicly, but it is intentionally richer than `public-demo-workspace`.

Use it when checking trust-critical web workflows:

- Cleanup Recommendations: `Safe`, `Review`, and `Blocked`
- Report Health groups for stale Report References, broken model references, invalid PBIR JSON,
  and Unsupported Metadata
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

- `Sales[Cleanup Note]` is a Safe cleanup candidate.
- `Sales[Perspective Revenue]` is a Review candidate because a perspective references it.
- `Store[Store Code]` is Blocked by RLS metadata.
- `Sales[Stale Margin]` appears only in stale PBIR metadata.
- `Sales[Broken Forecast]` has broken model references.
- `Report Metrics[Report Margin]` is a Report Extension Measure.
