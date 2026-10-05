# R13 Publish a machine-readable operations contract for AI agents

Status: Breakdown approved on 2026-10-03; local ticket, not a published GitHub issue. Start only when assigned and dependencies are satisfied.
Type: AFK — implementable from this specification once dependencies are satisfied.
Priority: Follow-up; optional only after release gates.

## User story

As an AI-agent or automation author, I can discover supported operations and produce valid reviewed plans without guessing fields.

## What to build

Expose a versioned operations schema/capability description and small examples that match runtime validation. Build on the existing CLI, check fingerprints, and saved-plan contract. Document a read -> inspect -> plan -> approve -> apply -> verify workflow.

## Acceptance criteria

- [ ] The published schema describes supported operation kinds, required/optional fields, constraints, and compatibility/version behavior.
- [ ] Examples validate against both the schema and actual plan creation on synthetic projects.
- [ ] Capability discovery is machine-readable and includes tool/schema versions; unsupported operations fail predictably.
- [ ] Document scope requirements, source freshness, metadata confidentiality, and treatment of item names/DAX/annotations as untrusted data rather than instructions.
- [ ] Agent guidance preserves explicit approval before mutation and does not introduce an automatic apply bypass.
- [ ] A sample external-agent workflow completes a reviewed change and verification using the documented contract.

## Blocked by

- [R06: Make the existing CLI discoverable and predictable for automation](r06-cli-discovery-and-errors.md)

## Verification

Validate representative good/bad operations through schema and runtime, then execute a complete synthetic workflow using only the published interface.

## Out of scope

MCP server, embedded chat, remote models/API keys, autonomous cleanup, or changing analysis semantics.

## Session handoff

Read the [release plan](../README.md), repository agent instructions, domain glossary, and applicable ADRs. Use a separate branch/worktree. Recheck the current implementation because the audit describes revision 6d29ce2, not necessarily your starting revision. Stay within this ticket; record dependencies, changed behavior, executed checks, and outstanding acceptance. Do not publish a release or perform unreviewed mutations on real Power BI Projects.

