# ProofShape CAD plugins

Status: **M2 adapter** (Onshape). The shared client, the Onshape active-part
STEP export adapter, the OAuth2 flow and the local install/run relay exist and
are unit-tested against mocked Onshape API responses. The adapter has **not**
been installed or exercised in a real CAD host; there are no live receipts yet.
Do not label it working, published, or live until the M2 live-receipt steps at
the bottom of this file are done.

## Shared client

`core/src/client.js` sends a user-selected STEP file to `POST /api/v1/validate`
as multipart `file`. It supports the current synchronous response and a
future/optional `202` job contract through `/api/v1/jobs/{id}`. It normalizes
the current `/validate` contract - `overall_verdict`, `priority_fixes`
(flat, severity-ordered, deduped) or `process_scores[].issues`, plus
`share_url` - down to the panel fields: `PASS | ISSUES | FAIL`, issue text
(with fix suggestions), sampled/provenance honesty marks, and the record URL.

The API key is required at runtime and is never checked in. Use a user-supplied
`cv_live_...` key.

```js
import { ProofShapeClient } from "./core/src/index.js";
const client = new ProofShapeClient({
  baseUrl: "https://cadverify-api.onrender.com",
  apiKey: process.env.PROOFSHAPE_API_KEY,
});
const verdict = await client.validateStep({ bytes, filename: "part.step" });
```

## Onshape M2 adapter

```
onshape/
  src/context.js      Parse the extension iframe context (documentId,
                      workspaceOrVersion[w|v], workspaceOrVersionId, elementId,
                      partId, server) per the Onshape extension docs.
  src/oauth.js        Authorization URL, code exchange, refresh, token store.
  src/api-client.js   Onshape REST: list parts, async STEP export (whole
                      studio or selected partIds), translation polling,
                      external-data download with 307 + 401 handling.
  src/export-step.js  Active-part resolution (selection > only visible part >
                      honest error) wired to the export.
  src/host-bridge.js  postMessage handshake: keepAlive + host-origin checks.
  server/oauth-relay.mjs  Loopback OAuth/token boundary for local install.
  panel/              The panel journey: Check -> progress -> verdict badge ->
                      issues -> Open full record.
```

Endpoint paths and payload fields follow the published Onshape OpenAPI
documents and the async export guide
(https://onshape-public.github.io/docs/api-adv/translation/):
`POST /api/partstudios/d/{did}/{wv}/{wvid}/e/{eid}/translations` with
`formatName: "STEP"` + `partIds` for the selected part (or `.../export/step`
for a whole studio), poll `GET /api/translations/{tid}` until
`requestState` is `DONE | FAILED`, then download
`GET /api/documents/d/{did}/externaldata/{fid}`.

## Local install/run test path (M2)

1. Create a free Onshape account, open Developer Settings, and register an
   OAuth application. Set the redirect URL to
   `http://127.0.0.1:8787/oauth/onshape/callback` and grant `OAuth2Read`
   (+`OAuth2Write` if needed).
2. Run the relay with the app's credentials and your own ProofShape key:

   ```sh
   ONSHAPE_CLIENT_ID=... \
   ONSHAPE_CLIENT_SECRET=... \
   PROOFSHAPE_API_KEY=cv_live_... \
   node plugins/onshape/server/oauth-relay.mjs
   ```

3. Open `http://127.0.0.1:8787/` - it redirects into Onshape sign-in and back,
   then loads the panel with a one-time session. To emulate the host context
   without an extension registration, append the document context:
   `&documentId=<did>&workspaceOrVersion=w&workspaceOrVersionId=<wid>&elementId=<eid>`
   (from an open Onshape document URL).
4. For the real in-Onshape path, serve `panel/` (+ `src/`, `core/`) over HTTPS
   and register an element-tab extension whose action URL points at it. The
   panel reads the context from the iframe URL itself; sign-in still goes
   through the relay or your hosting service.
5. Click **Check with ProofShape**. Expected: STEP export of the selected (or
   only) part, verdict badge, issues with fixes, and **Open full record**.
6. Capture the receipts: Onshape translation id, `/api/v1/validate` response,
   screenshots. Until those exist from a real document, status stays
   **M2 adapter**.

## Tests

```sh
cd plugins
npm test
```

36 deterministic tests: shared client contract (sync, 202 polling, failure,
current `/validate` shape), extension context, OAuth exchange/refresh/store,
Onshape API client (export payloads, polling, failure, timeout, 401 refresh,
307 redirect), active-part resolution, host bridge, and the relay's full
OAuth round trip against a mocked token endpoint.

## M2 live receipts still owed

- Real Onshape developer app registered (client id exists; secret in relay env).
- Extension installed in a test document; one real part exported and checked
  through staging with screenshots + API receipts.
- App-store checklist items (hosting over HTTPS, store entry) if we publish.

Host references:
- https://onshape-public.github.io/docs/app-dev/
- https://onshape-public.github.io/docs/app-dev/extensions/
- https://onshape-public.github.io/docs/auth/oauth/
- https://onshape-public.github.io/docs/api-adv/translation/
- https://onshape-public.github.io/docs/app-store/checklist/
