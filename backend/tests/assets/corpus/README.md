# Public corpus manifest fixture

`manifest.jsonl` contains six metadata records for public BCN3D Moveo parts from
https://github.com/BCN3D/BCN3D-Moveo, imported by the corpus gatherer on 2026-06-29.
Only public source URLs, filenames, normalized mesh hashes, provenance and the
original heuristic guesses are retained. No private CAD or human labels are
included. The upstream MIT license is retained in `LICENSE`.

This is a manifest-selection fixture, not a mesh or routing-accuracy dataset.
It exercises the real JSONL loader and both matching and fallback smoke-seed
selection without requiring the private local corpus or network downloads.
The heuristic guesses are unverified and must never count as human labels.
