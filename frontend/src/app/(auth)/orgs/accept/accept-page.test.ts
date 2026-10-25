/**
 * Opening an invite link never joins or switches by itself (security review
 * R4, F2). The default /orgs/accept page POSTed the accept as soon as it
 * loaded; with accepting also switching the active org, one visit to an
 * admin-minted link moved the person's next upload into the inviting org.
 * Now both pages read only on load and accept on the button press, which
 * also asks to switch (the page says so before the press).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
const v4 = readFileSync(new URL("../../../../components/v4/moments/invite.tsx", import.meta.url), "utf8");

function body(src: string, start: string, end: string): string {
  const i = src.indexOf(start);
  const j = src.indexOf(end, i);
  assert.ok(i > 0 && j > i, `${start} … ${end} not found`);
  return src.slice(i, j);
}

test("loading the legacy accept page does not accept the invite by itself", () => {
  const onLoad = body(page, "React.useEffect(", "}, [token]);");
  assert.doesNotMatch(onLoad, /invites\/accept|ACCEPT_PATH|accept\(/, "the page POSTs the accept on load, with no button press");
  // It reads what the invite is for (the public summary) and who this browser is (the preview).
  assert.match(onLoad, /fetchInviteSummary\(token\)/);
  assert.match(onLoad, /PREVIEW_PATH/);
  assert.match(page, /const PREVIEW_PATH = "\/api\/proxy\/orgs\/invites\/preview";/);
});

test("the legacy page accepts only from the Accept button, and that press asks to switch", () => {
  const accept = body(page, "async function accept()", "\n  }\n");
  assert.match(accept, /post\(ACCEPT_PATH, \{ token, switch: true \}\)/);
  assert.match(page, /onClick=\{\(\) => void accept\(\)\}/);
  assert.equal(page.match(/ACCEPT_PATH/g)?.length, 2, "accepted from somewhere other than the button");
  // Said before the press, and the two-step sign-out is handled, not swallowed.
  assert.match(page, /Accepting makes \$\{org\} your active organization\./);
  assert.match(page, /res\.data\.signed_out === true\) return setState\(\{ kind: "sign_in_again"/);
});

test("the v4 card accepts on the press, switches in the same request, and sends a signed-out joiner to sign in", () => {
  const onLoad = body(v4, "React.useEffect(", "}, [token, attempt]);");
  assert.doesNotMatch(onLoad, /invites\/accept/);
  assert.match(v4, /post\("\/api\/proxy\/orgs\/invites\/accept", token, \{ switch: true \}\)/);
  assert.match(v4, /d\.signed_out === true\) return setState\(\{ kind: "signin"/);
  assert.match(v4, /const signInAgainHref = `\/login\?next=\$\{encodeURIComponent\(next \?\? `\$\{R\.parts\}\?joined=1`\)\}`;/);
  // The old voluntary step-up after accepting is gone: the API ends the session itself.
  assert.doesNotMatch(v4, /two-step\/step-up/);
});
