# Enterprise Answer Fidelity Gate

This gate exists because a completed browser flow is not enough for enterprise
trust. The platform must prove that the answer it gives a CAD engineer or
sourcing team is tied to the right input, honest methodology, correct math,
preserved service context, visible UI evidence, and role-governed interactions.

## What CI Checks

- Input integrity: `backend/tests/assets/cube.step` byte length and SHA-256 must
  match the mesh hash used by the enterprise journey.
- Methodology honesty: should-cost confidence remains labeled as
  assumption-based and unvalidated unless real validation exists.
- Calculation fidelity: annualized exposure must equal unit cost times declared
  annual volume, and it must be withheld before volume is declared.
- Environment context: service temperature, sour-service flag, pressure,
  parent assembly, units per parent, and user provenance must survive into the
  enterprise artifact.
- Machine truth: declared machine processes, rates, and user provenance must
  match the simulated enterprise floor, while recalibration refuses below the
  real-record validation floor.
- Display fidelity: key human and enterprise screenshots must be real PNGs with
  credible dimensions, size, color variation, and contrast.
- Interaction fidelity: command palette, notifications, API-key reveal,
  approval reopen, stale warning, and low-role denial all have to pass as
  browser or API interactions.

## Truth Boundary

This is a strenuous synthetic enterprise lab. It simulates an Exxon-style
organization with SSO, ERP, PLM, procurement, supplier, security, and CAD
workflow pressure. It is not a certification from Exxon, SAP, a PLM vendor, a
supplier network, a formal auditor, or a live procurement counterparty.
