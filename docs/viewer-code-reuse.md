# Viewer definition reader reuse

Source: [MrPerfectH/Semantic-Model-Viewer](https://github.com/MrPerfectH/Semantic-Model-Viewer),
based on commit b6e5c9daacf6f007685761f797e443e019448359 (verified on 2026-10-14).
The source may contain uncommitted work; hashes below identify the exact reused bytes.

- viewer-dax-format.js: exact copy of Models/tools/viewer/js/dax-format.js.
- viewer-code-tokens.js: PowerQuery.tokens IIFE from power-query.js and daxToks
  from measures.js, adapted only to export standalone globals without the Viewer app.
- Definition reader uses Viewer syntax categories, IBM Plex Mono fallback stack,
  numbered lines and separate source/formatted copying. No M formatter is claimed.
- MIT license retained in static/viewer-LICENSE.txt and included in Python packages.
- Formatting is a presentation projection. Original analyzed source and edit drafts
  are never overwritten by formatting, syntax coloring or copying.
- Viewer comment color #94a0b0 has insufficient contrast on white. Cleaner uses
  #68778e for readable comments; this deliberate accessibility difference is recorded
  rather than claiming pixel-identical presentation.

Exact upstream SHA256:
{
  "dax-format.js": "478f9a6c45bb226d09d7cd8fea4cac5d2322384534b6e11268a0b4f21716cea8",
  "power-query.js": "89f493d091fd4040324b57b83077a8039ece3afa4a1f99e71811b6ed72ef77b5",
  "measures.js": "d397c67068518d5b4ddf0107293ea6b9065c3f0040ddd4586a26f3befcae32ff"
}
