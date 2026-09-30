# SAP read readiness — 2026-09-30

SAP BOM explosion preview is implemented locally. SAP assembly import and successful testing against an actual SAP tenant remain open. Nothing in this report establishes live SAP certification or production deployment.

## Delivered scope

- Reuses encrypted credentials, org-admin authorization, bounded HTTP transport, public-address DNS pinning, TLS verification, no redirects, request timeout and the existing integration-run ledger.
- Calls the documented read-only `GET API_BILL_OF_MATERIAL_SRV;v=2/ExplodeBOM` alongside the saved SAP product-service root. User supplies material, BOM number, alternative, plant, application, date and depth; optional version and change document are preserved. Required quantity is explicitly 1, material BOM category M, multi-level enabled, limited explosion disabled. Depth is explicitly bounded to 1–99.
- Shows individual component records with item quantity, header base quantity and exploded component quantity separately. Decimal values remain strings; there is no rounding, inferred parent graph, unit conversion or aggregation into part counts. The UI does not assume the exploded quantity uses the item unit.
- Rejects malformed, paginated, empty, mismatched-root/alternative responses, responses over 1 MB and previews of 9999 or more records. The 9998-record threshold is an application precaution across unverified tenant versions, not a universal current SAP limit.
- SAP import requests are rejected server-side before credential decryption/network access. The UI has no SAP import button. Ledger metadata explicitly records `import_supported=false`, `complete_structure_verified=false`, requested selection and read-only proof scope. Only up to 20 projected component records are stored in preview metadata; raw vendor responses, supplier details and credentials are discarded.

## Verification

`PYTHONPATH=backend /Users/nazeem/.codex/worktrees/5c24/cadverify/backend/.venv/bin/python -m pytest backend/tests/test_sap_bom_preview.py backend/tests/test_windchill_bom_transport.py backend/tests/test_connector_probe_transport.py backend/tests/test_connector_adapters.py -q`

Result: **56 passed**. New SAP tests exercise actual HTTPX request construction with vendor-shaped fixtures, separate quantity meanings, response validation, credential secrecy, rejection of unsupported imports, proof metadata and the FastAPI route/schema. These are fixtures and mocked storage, not a successful SAP account test. No shared database/runtime was changed.

Frontend `tsc --noEmit` and ESLint on the two changed integration files passed. The root lane independently reported 499 frontend tests, TypeScript, changed-file ESLint and production Next build passing.

## Remaining blockers and acceptance evidence

1. Actual tenant/service metadata and an authorized read credential are absent. The root lane's read-only profile inventory found two SAP and three Windchill profiles, all revoked. Run both product connection test and BOM preview against the intended SAP tenant; retain sanitized run IDs, timestamps, service version and selectors.
2. Before enabling assembly import, verify path/predecessor semantics, repeated subassemblies, alternative/version/effectivity identities, completeness/truncation behavior, phantom/configurable/recursive cases, scrap/fixed quantities and unit conversions against actual tenant metadata and independently known assemblies. A successful HTTP read cannot establish these properties.
3. Compare expected versus returned quantities on a real multi-level assembly, including a non-unit header base, repeated child material and non-count units. Current previews deliberately do not turn these values into the existing integer-edge BOM model.

## Primary contract references

- [SAP operations for Bills of Material v2](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9f047b05da4545ca8f9ebfc22acefd06/ac29c05833e44980ab6b236e409f2429.html): documented GET function and selector syntax.
- [SAP Explode BOM example](https://help.sap.com/docs/SAP_S4HANA_CLOUD/7489fa08cede494cbdf08fa3651598af/d6456a46ed7a41e0bbde173e83342569.html): selector requirements and exploded response fields.
- [SAP Cloud SDK generated ExplodeBOM helper](https://javadoc.io/static/com.sap.cloud.sdk.s4hana/s4hana-api-odata-onpremise/3.78.0/com/sap/cloud/sdk/s4hana/onpremise/datamodel/odata/namespaces/billofmaterials/ExplodeBOMFluentHelper.html) and [response type](https://javadoc.io/static/com.sap.cloud.sdk.s4hana/s4hana-api-odata-onpremise/3.78.0/com/sap/cloud/sdk/s4hana/onpremise/datamodel/odata/namespaces/billofmaterials/DBomheaderforexplosionOut.html): parameter lengths, decimal quantities, separate component-unit/base-unit quantities. This historical SDK is contract evidence, not proof of a particular customer's current metadata.
- [SAP KBA 3662490](https://userapps.support.sap.com/sap/support/knowledge/en/3662490): identifies a >9999-component issue for Public Cloud 2508 and states a CE2602 fix; tenant version must be checked rather than assuming this limit remains universal.
