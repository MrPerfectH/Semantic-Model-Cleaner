# Native Power BI acceptance

Power BI Desktop 2.158.1177.0 opened the disposable `desktop-v4` derivative of the generated synthetic fixture. The baseline has typed import data, enhanced PBIR metadata and local model measures. The analyzer stress fixture separately retains deliberate malformed/stale cases.

`baseline.json`, `applied.json` and `restored.json` record native ADOMD queries and visible UI Automation visual-error inspection. Each stage ran a TMSL full refresh against the owned Desktop instance's local Analysis Services engine. Revenue=1 and Rows=1 throughout. The unused `Safe Cleanup Candidate` measure is present initially, absent after applying its reviewed deletion, and present again after restore.

`roundtrip.json` ties the file-side operation to the exact beta4 archive, records each metadata hash before/after, confirms preview was read-only, and confirms byte-exact restoration. `native-powerbi.ps1` and `desktop-acceptance.py` in the parent folder contain the probes. The baseline proof was obtained on the same unchanged fixture before the final packaging round; final apply/restore proofs use revision 3462246.

The existing user Power BI sessions were preserved. Owned synthetic Desktop processes were closed after verification. Full-window native captures were kept out of the repository because Desktop chrome can show account information; no user model was used as fixture data.
