# ProofShape training fixtures

These fixtures are deterministic training inputs, not customer facts.

- `parts-manifest-mixed.csv`: exactly 2 valid rows; line 4 is rejected for invalid positive integers and material class.
- `ground-truth-mixed.csv`: exactly 8 accepted **demo/stand-in** FDM rows bound to the golden cube by its full source SHA-256; line 10 is rejected for process, quantity, cost, material, currency, date, and evidence-hash errors. Upload the unmodified `cube.step` successfully before importing this CSV. Recalibration must still refuse with `0 real of 8 needed`; these invented training costs must never produce a measured claim. The release suite separately exercises the successful calibration mechanics in an isolated test tenant, without presenting test facts as customer accuracy.
- `parts-master-map.csv`: two mapping rows parse; line 4 is rejected for missing filename. When paired only with the guide's `cube.step`, `cube.step` onboards, `missing.step` is reported missing, and no placeholder geometry is created.
- `sap-s4hana-sandbox.json`: 2 products and 1 BOM edge normalize without warnings in the offline connector replay.
- `windchill-sandbox.json`: 2 parts and 1 usage edge normalize without warnings in the offline connector replay.
- `wire-only-unmeshable.step`: a valid STEP wireframe with no tessellatable solid/shell. Verify must return the documented bounded geometry error and must create no analysis or cost evidence.

Reset training state by deleting only records created in the designated test organization, or start with a fresh organization. Never run destructive reset helpers against a customer tenant.
