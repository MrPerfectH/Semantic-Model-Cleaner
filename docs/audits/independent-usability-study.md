# Independent first-use study

Status: **not conducted — zero participants**. Automated UI checks and the maintainer's own use are not independent research. This ready-to-run study needs 2–3 first-time participants; no invitations have been sent.

Recruit one occasional Power BI author, one regular model maintainer, and, if possible, one CLI/automation user. Use the public 0.4.0b4 Windows beta and its bundled demo for UI tasks. Record version, Windows/display scaling, Power BI familiarity and prior exposure. For the new AI contract use a build from the follow-up commit and record that separately; it is not in 0.4.0b4.

## Invitation draft

“Could you spend 20 minutes trying Semantic Model Cleaner for the first time? We'd like to observe what is clear or confusing. Use only its demo, without confidential files. You can stop at any time. With your permission we'll take notes; recording is optional. We are testing the app, not you.”

## Participant tasks

Give one task at a time without naming the controls. Ask the participant to think aloud. Do not coach; record help as assisted completion. Explain the current unsigned download honestly before installation rather than asking participants to bypass an unexplained warning.

1. Download, extract and launch the app. Find a safe way to explore without your own project.
2. Identify which model and reports are being analyzed. Explain one finding and what evidence would make you comfortable changing it.
3. Organize the Revenue measure into a display folder. Before committing, explain exactly what will change and which files are affected.
4. Apply that change, verify it, then recover the original state. Explain whether recovery would overwrite a later edit.
5. Find the guidance for an unsupported project and describe the next step you would take.
6. Optional automation participant: find CLI help, analyze the demo into JSON, and prepare a plan. Explain where approval belongs before applying an agent's proposal.

Stop any task after five minutes of being stuck. Stop immediately for an unexpected write outside the demo. Do not collect project contents, credentials or identifying information in public notes. Obtain separate permission before sharing quotes or recordings.

## Results template — one copy per participant

Participant ID / date / app version or commit / background / display scaling:

| Task | Unassisted / assisted / failed | Time | Observed behavior and exact quote | Severity | Follow-up issue |
| --- | --- | --- | --- | --- | --- |
| Launch and demo | Pending | | | | |
| Scope and finding | Pending | | | | |
| Preview change | Pending | | | | |
| Apply, verify, recover | Pending | | | | |
| Unsupported input | Pending | | | | |
| Automation (optional) | Pending | | | | |

After each task: “How easy or difficult was that?” (1 very difficult–7 very easy). At the end: “What would stop you using this on your own project?” and “What should change first?”

## Decision rule

Fix and retest any accidental mutation, misunderstood scope/approval, or failure to recover. Treat a repeated first-use blocker in two participants as a beta priority. Record single-participant issues too; this small study cannot estimate population success rates. Summarize actual completion counts, help required, confidence quotes and unresolved issues only after sessions occur. Keep raw private notes out of the repository; commit a de-identified report with participant consent.
