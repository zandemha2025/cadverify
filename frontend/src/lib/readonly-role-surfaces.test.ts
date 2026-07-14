import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("cost-decision mutations are absent for read-only session roles", async () => {
  const source = await readFile(
    new URL("../app/(app)/cost-decisions/[id]/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /const \{ user \} = useAuth\(\);/);
  assert.match(source, /const canMutate = canMutateWorkspace\(user\?\.role\);/);
  assert.match(source, /if \(!canMutate\) return;/);
  assert.match(source, /\{canMutate && \(\s*<ShareButton/);
  assert.match(source, /\{canMutate && \(\s*<Button[\s\S]*?RFQ ZIP/);
  assert.match(source, /<GovernancePanel[\s\S]*?canMutate=\{canMutate\}/);
  assert.match(source, /data-testid="cost-decision-read-only"/);
  assert.match(source, /!approved && canMutate &&/);
});

test("Design Studio hides and guards every create, revise, and archive surface", async () => {
  const source = await readFile(
    new URL("../app/(app)/designs/page.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /const \{ user \} = useAuth\(\);/);
  assert.match(source, /const canMutate = canMutateWorkspace\(user\?\.role\);/);
  assert.match(
    source,
    /\{canMutate \? \(\s*<Card[^>]+data-testid="design-mutation-workspace"[\s\S]*?data-testid="designs-read-only"/,
  );
  assert.match(source, /\{canMutate && \(\s*<div[^>]+data-testid="design-mutation-actions"/);
  assert.match(source, /const beginRevision = \(design: Design\) => \{\s*if \(!canMutate\) return;/);
  assert.match(source, /const submit = async \(\) => \{\s*if \(!canMutate\) return;/);
  assert.match(source, /const remove = async \(design: Design\) => \{\s*if \(!canMutate\) return;/);
  assert.match(source, /\{canMutate && \(\s*<Button[^>]+onClick=\{\(\) => beginRevision\(selected\)\}/);
  assert.match(source, /\{canMutate && \(\s*<Button asChild>[\s\S]*?\/verify\?design=/);
});
