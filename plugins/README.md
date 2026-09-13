# ProofShape CAD plugins

Status: **M1 skeleton**. This code has not been installed or exercised in a real CAD host. Do not label it working, published, or live until M2 receipts exist.

## Shared client

`core/src/client.js` sends a user-selected STEP file to `POST /api/v1/validate` as multipart `file`. It supports the current synchronous response and a future/optional `202` job contract through `/api/v1/jobs/{id}`. It normalizes only the panel fields: `PASS | ISSUES | FAIL`, issue text, sampled/provenance honesty marks, and the record URL when the API returns one.

The API key is required at runtime and is never checked in. Use a user-supplied `cv_live_...` key. M1 does not include token storage.

```js
import { ProofShapeClient } from "./core/src/index.js";
const client = new ProofShapeClient({
  baseUrl: "https://cadverify-api.onrender.com",
  apiKey: process.env.PROOFSHAPE_API_KEY,
});
const verdict = await client.validateStep({ bytes, filename: "part.step" });
```

Run deterministic client tests:

```sh
cd plugins
npm test
```

## Onshape shell

`onshape/manifest.json` is reference metadata for Developer Portal setup, not an installable claim. `onshape/config/oauth.example.json` carries public OAuth endpoints and placeholders only. `onshape/panel/` is the exact M1 panel journey:

1. **Check with ProofShape**
2. progress
3. verdict badge and issue list
4. **Open full record** when the API returns a share URL

The panel remains disabled until the host provides `onshapeExportCurrentPartAsStep()` and runtime configuration:

```js
globalThis.PROOFSHAPE_PLUGIN_CONFIG = {
  baseUrl: "https://cadverify-api.onrender.com",
  apiKey: userSuppliedApiKey,
};
```

## M2 requirements

- Create a free Onshape developer account and register the OAuth application from the Developer Portal.
- Implement the OAuth callback/token boundary without exposing client secret or ProofShape API key to other users.
- Bind the in-element action to the current document/element/part and export the selected part as STEP through Onshape's documented API.
- Install in a test document, run one real part through staging, and verify the badge, issues, sampled/provenance marks, and full-record link.
- Capture API request/job/result receipts and screenshots. Until those exist, status remains **skeleton**.

Host references:
- https://onshape-public.github.io/docs/app-dev/
- https://onshape-public.github.io/docs/app-store/checklist/
