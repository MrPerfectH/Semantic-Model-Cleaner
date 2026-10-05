# Culture translations are per-object evidence, not analysis limitations

## Status

accepted

## Context

After ADR 0002, table files were scanned structurally, but `cultures/*.tmdl`
was still scanned with file-scoped text extraction (issue #93). Any
`Table[Name]`-shaped token anywhere in a culture file, including captions,
descriptions and the linguistic metadata JSON, became a reference, and the
resulting Analysis Limitation was owned by "culture file pl-PL.tmdl" rather
than by the translated object. That is the substring-matching class of fault
#82 removed elsewhere, and it hid the concrete consequence of a deletion:
the translated object loses its translation.

The TMDL grammar places translations in a declaration tree:
`culture <name>` / `translations` / `model Model` / `table <T>` /
`measure|column|hierarchy <N>`, each carrying `caption`, `description` or
`displayFolder` properties. `linguisticMetadata` is a separate expression
property of the culture holding a JSON payload (Q&A linguistic schema).

## Decision

1. **Translations are Translation Membership, informational evidence only.**
   Each table or item under `translations` that carries a translated property
   yields one evidence entry with owner (`Table` or `Table[Item]`), culture,
   source file and line. A translation is just a translation: it is never
   evidence that an item should be kept, so it adds no Review trigger and never
   changes the Cleanup Recommendation. The entry exists so users can see which
   translations are removed together with the item. Items carry it as
   `translations` (`translationMemberships` in the browser payload), tables get
   an informational signal and `translations`. It is never a Report Reference
   and never an Analysis Limitation. This differs deliberately from Perspective
   Membership, which curates what consumers see.
2. **Linguistic metadata stays an Analysis Limitation**, owned by
   `culture <name>` with its location. Its JSON payload is not parsed and never
   produces item references; the limitation is targeted with no targets, so it
   changes no Cleanup Recommendation.
3. **No text-level extraction in culture files.** Names inside captions,
   descriptions, comments or the linguistic payload never produce references.
   The `definition/translations` directory and `.json` files under `cultures/`
   are no longer scanned; they are not part of the TMDL folder layout.

## Consequences

- Translated unused measures and columns stay Safe when no other evidence
  applies, so fully translated models keep their Safe counts. (The first
  version of this decision moved them to Review; owner decision of 2026-10-05,
  issue #102, amends that.)
- Limitation counts drop for models whose culture files previously produced a
  file-scoped limitation without a `linguisticMetadata` block; models with
  linguistic metadata keep one targeted limitation per culture.
- Renames and deletions still do not rewrite culture files (the same gap
  exists for perspective members). Issue #99 covers removing the translation
  entries in the same reviewed plan; until then the evidence tells users what
  to clean up by hand.
