import assert from "node:assert/strict";
import test from "node:test";

import { parseOrganizationAccess } from "./organization-access.ts";

test("parses one exact active organization", () => {
  assert.deepEqual(
    parseOrganizationAccess({
      active_org_id: "org-a",
      organizations: [
        { org_id: "org-a", name: "Acme", org_role: "member", is_active: true },
        { org_id: "org-b", name: "Beta", org_role: "viewer", is_active: false },
      ],
    }),
    {
      activeOrgId: "org-a",
      organizations: [
        { orgId: "org-a", orgName: "Acme", role: "member", isActive: true },
        { orgId: "org-b", orgName: "Beta", role: "viewer", isActive: false },
      ],
    },
  );
});

test("keeps a valid no-organization account distinct from unavailable data", () => {
  assert.deepEqual(parseOrganizationAccess({ active_org_id: null, organizations: [] }), {
    activeOrgId: null,
    organizations: [],
  });
});

test("uses the single server-marked active membership when the pointer is null", () => {
  assert.equal(
    parseOrganizationAccess({
      active_org_id: null,
      organizations: [
        { org_id: "org-a", name: "Acme", org_role: "admin", is_active: true },
      ],
    })?.activeOrgId,
    "org-a",
  );
});

test("fails closed on malformed or contradictory organization state", () => {
  const invalid = [
    null,
    {},
    { active_org_id: "", organizations: [] },
    { active_org_id: "   ", organizations: [] },
    { active_org_id: "missing", organizations: [] },
    {
      active_org_id: "org-a",
      organizations: [
        { org_id: "org-a", name: "Acme", org_role: "owner", is_active: true },
      ],
    },
    {
      active_org_id: "org-a",
      organizations: [
        { org_id: "org-a", name: "Acme", org_role: "admin", is_active: false },
        { org_id: "org-b", name: "Beta", org_role: "admin", is_active: true },
      ],
    },
    {
      active_org_id: null,
      organizations: [
        { org_id: "org-a", name: "Acme", org_role: "admin", is_active: true },
        { org_id: "org-b", name: "Beta", org_role: "admin", is_active: true },
      ],
    },
  ];
  for (const value of invalid) assert.equal(parseOrganizationAccess(value), null);
});
