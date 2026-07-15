import {
  Building2,
  ShieldAlert,
  Users,
  Mail,
  KeyRound,
  Activity,
  Network,
} from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { Tone } from "@/lib/status";
import { getUser } from "@/lib/dal";
import {
  getOrganizationAccess,
  listMembers,
  listInvites,
  listSamlMappings,
  getHealthDeep,
  getSsoStatus,
  type Invite,
  type HealthDeep,
} from "./actions";
import {
  OrganizationSwitcher,
  InviteForm,
  RevokeInviteButton,
  RemoveMemberButton,
  SamlMappingForm,
  DeleteMappingButton,
} from "./ui";

/**
 * Settings → Organization. The org-admin surface: members, invites, SAML
 * group→role mappings (real CRUD), plus read-only SSO/SCIM endpoint status and
 * an ops health readout. Server component on the same session-cookie-proxied
 * rails as Settings → Developer. Org-admin RBAC is enforced by the backend;
 * this page additionally gates its own render to admins with an honest
 * "admins only" state, matching how the platform gates elsewhere.
 */

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toISOString().slice(0, 10);
}

const INVITE_TONE: Record<Invite["status"], Tone> = {
  pending: "warn",
  accepted: "pass",
  expired: "neutral",
  revoked: "fail",
};

function bool(ok: boolean): { tone: Tone; label: string } {
  return ok ? { tone: "pass", label: "Healthy" } : { tone: "fail", label: "Unhealthy" };
}

function workerTone(state: string): { tone: Tone; label: string } {
  switch (state) {
    case "ok":
      return { tone: "pass", label: "ok" };
    case "stale":
      return { tone: "warn", label: "stale" };
    case "unknown":
      return { tone: "neutral", label: "unknown" };
    default:
      return { tone: "fail", label: state || "unavailable" };
  }
}

export default async function OrganizationSettingsPage() {
  const [access, user] = await Promise.all([getOrganizationAccess(), getUser()]);
  const active =
    access.organizations.find((org) => org.orgId === access.activeOrgId) ??
    access.organizations[0];
  const ctx = active
    ? { orgId: active.orgId, orgName: active.orgName, role: active.role }
    : null;
  const switcher = access.organizations.length > 0 ? (
    <OrganizationSwitcher
      organizations={access.organizations}
      activeOrgId={ctx?.orgId ?? null}
    />
  ) : null;

  // Honest RBAC-in-UI gate: only org admins manage the org. Non-admins (and any
  // caller the backend would 403) see a clear "admins only" state, never a
  // half-rendered surface or a crash.
  if (!ctx || ctx.role !== "admin") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Organization"
          subtitle="Members, invites, and SSO for your organization."
        />
        {switcher}
        <EmptyState
          icon={ShieldAlert}
          title="Admins only"
          description={
            ctx
              ? `You're a ${ctx.role} of ${ctx.orgName}. Managing members, invites, and SSO requires an organization admin.`
              : "You don't belong to an organization yet, or your session has no active org."
          }
        />
      </div>
    );
  }

  const [members, invites, mappings, health, sso] = await Promise.all([
    listMembers(),
    listInvites(),
    listSamlMappings(),
    getHealthDeep(),
    getSsoStatus(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Organization"
        subtitle={`Manage members, invites, and SSO for ${ctx.orgName}.`}
        badge={
          <span className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            <Building2 className="size-3.5" /> admin
          </span>
        }
      />

      {switcher}

      {/* ── Members ── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Users className="size-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Members</h2>
          <span className="text-xs text-muted-foreground">({members.length})</span>
        </div>
        {members.length === 0 ? (
          <EmptyState icon={Users} title="No members" />
        ) : (
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => (
                  <TableRow key={m.user_id} className="h-12">
                    <TableCell className="font-medium text-foreground">
                      {m.email}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={m.org_role === "admin" ? "info" : "neutral"}
                        label={m.org_role}
                        size="sm"
                        icon={false}
                        className="capitalize"
                      />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmtDate(m.joined_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end">
                        <RemoveMemberButton
                          userId={m.user_id}
                          email={m.email}
                          isSelf={!!user && m.user_id === user.id}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>

      {/* ── Invites ── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Mail className="size-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Invitations</h2>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Invite a teammate</CardTitle>
            <CardDescription>
              Sends a single-use, expiring accept link. If email isn&apos;t
              configured, forward the one-time link shown after creating.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <InviteForm />
          </CardContent>
        </Card>
        {invites.length === 0 ? (
          <EmptyState icon={Mail} title="No invitations yet" />
        ) : (
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invites.map((inv) => (
                  <TableRow key={inv.id} className="h-12">
                    <TableCell className="font-medium text-foreground">
                      {inv.email}
                    </TableCell>
                    <TableCell className="capitalize text-muted-foreground">
                      {inv.role}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={INVITE_TONE[inv.status]}
                        label={inv.status}
                        size="sm"
                        icon={false}
                        className="capitalize"
                      />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmtDate(inv.expires_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end">
                        {inv.status === "pending" ? (
                          <RevokeInviteButton inviteId={inv.id} />
                        ) : (
                          <span className="text-xs text-subtle-foreground">—</span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>

      {/* ── SSO: SAML group → role mappings ── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <KeyRound className="size-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">
            SSO · SAML group → role mappings
          </h2>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Map an IdP group to an org role</CardTitle>
            <CardDescription>
              Just-in-time on SAML login: a matching group grants or promotes
              membership at the mapped role. Missing groups never demote or
              deprovision an existing member.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-4">
            <SamlMappingForm />
          </CardContent>
        </Card>
        {mappings.length === 0 ? (
          <EmptyState
            icon={KeyRound}
            title="No SAML group mappings"
            description="Add one above to assign org roles from your IdP's group claims."
          />
        ) : (
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>SAML attribute</TableHead>
                  <TableHead>Group value</TableHead>
                  <TableHead>Grants role</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mappings.map((mp) => (
                  <TableRow key={mp.id} className="h-12">
                    <TableCell className="num text-foreground">
                      {mp.attribute_name}
                    </TableCell>
                    <TableCell className="num text-foreground">
                      {mp.group_value}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        tone={mp.org_role === "admin" ? "info" : "neutral"}
                        label={mp.org_role}
                        size="sm"
                        icon={false}
                        className="capitalize"
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end">
                        <DeleteMappingButton mappingId={mp.id} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>

      {/* ── SSO / SCIM status (read-only) ── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Network className="size-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">
            SSO / SCIM endpoints
          </h2>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Endpoints for your IdP</CardTitle>
            <CardDescription>
              Base SAML / OIDC / SCIM enablement is configured at deploy time
              (AUTH_MODE + IdP environment). This panel shows current status and
              the exact URLs to hand your IdP — it is not an editable form.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground">SAML SP metadata:</span>
              <StatusBadge
                tone={
                  sso.saml.state === "reachable"
                    ? "pass"
                    : sso.saml.state === "misconfigured"
                      ? "warn"
                      : sso.saml.state === "not_enabled"
                        ? "neutral"
                        : "neutral"
                }
                label={
                  sso.saml.state === "reachable"
                    ? "Reachable"
                    : sso.saml.state === "misconfigured"
                      ? "Enabled · check IdP config"
                      : sso.saml.state === "not_enabled"
                        ? "Not enabled in this deployment"
                        : "Unknown"
                }
                size="sm"
                icon={false}
              />
              {sso.saml.httpStatus != null && (
                <span className="num text-xs text-subtle-foreground">
                  HTTP {sso.saml.httpStatus}
                </span>
              )}
            </div>
            <UrlRow label="SAML ACS (Assertion Consumer Service)" url={sso.urls.samlAcs} />
            <UrlRow label="SAML SP metadata" url={sso.urls.samlMetadata} />
            <UrlRow label="SAML login (SP-initiated)" url={sso.urls.samlLogin} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground">OIDC relying party:</span>
              <StatusBadge
                tone={
                  sso.oidc.state === "reachable"
                    ? "pass"
                    : sso.oidc.state === "misconfigured"
                      ? "warn"
                      : "neutral"
                }
                label={
                  sso.oidc.state === "reachable"
                    ? "Enabled"
                    : sso.oidc.state === "misconfigured"
                      ? "Enabled · check provider config"
                      : sso.oidc.state === "not_enabled"
                        ? "Not enabled in this deployment"
                        : "Unknown"
                }
                size="sm"
                icon={false}
              />
              {sso.oidc.httpStatus != null && (
                <span className="num text-xs text-subtle-foreground">
                  HTTP {sso.oidc.httpStatus}
                </span>
              )}
            </div>
            <UrlRow
              label="OIDC login"
              url={sso.urls.oidcLogin}
              hint={
                sso.oidc.state === "reachable"
                  ? undefined
                  : sso.oidc.state === "not_enabled"
                    ? "Setup URL only; login becomes available after OIDC is enabled for this deployment."
                    : "Available for setup and recovery; login will not work until the provider configuration is healthy."
              }
            />
            <UrlRow
              label="OIDC redirect / callback"
              url={sso.urls.oidcCallback}
              hint={
                sso.oidc.state === "reachable"
                  ? undefined
                  : sso.oidc.state === "not_enabled"
                    ? "Register this callback with the IdP before enabling OIDC in the deployment."
                    : "Register this callback with the IdP, then re-check the deployment status above."
              }
            />
            <UrlRow
              label="SCIM 2.0 base URL"
              url={sso.urls.scimBase}
              hint="Provisioning requires an org-scoped admin API key (issued at deploy time)."
            />
          </CardContent>
        </Card>
      </section>

      {/* ── Ops health ── */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Ops health</h2>
        </div>
        <HealthCard health={health} />
      </section>
    </div>
  );
}

function UrlRow({
  label,
  url,
  hint,
}: {
  label: string;
  url: string;
  hint?: string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <span className="text-muted-foreground">{label}</span>
        <code className="num truncate rounded-xs border border-border bg-muted px-2 py-1 text-[11px] text-foreground">
          {url}
        </code>
      </div>
      {hint && <p className="text-xs text-subtle-foreground">{hint}</p>}
    </div>
  );
}

function HealthCard({ health }: { health: HealthDeep }) {
  if (!health.reachable) {
    return (
      <Card tone="fail">
        <CardHeader tone="fail">
          <CardTitle>Health endpoint unreachable</CardTitle>
          <CardDescription>
            Could not reach <code className="num">/health/deep</code>
            {health.httpStatus ? ` (HTTP ${health.httpStatus})` : ""}. This
            readout degrades gracefully rather than fabricating a status.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const overall =
    health.status === "ok"
      ? { tone: "pass" as Tone, label: "Healthy" }
      : { tone: "warn" as Tone, label: "Degraded" };
  const c = health.checks ?? {};
  const pg = bool(!!c.postgres?.ok);
  const rd = c.redis;
  const wk = workerTone(c.worker?.state ?? "unavailable");

  return (
    <Card tone={overall.tone} className="overflow-hidden">
      <CardHeader tone={overall.tone}>
        <div className="flex items-center justify-between">
          <CardTitle>Dependencies</CardTitle>
          <StatusBadge tone={overall.tone} label={overall.label} size="sm" />
        </div>
        <CardDescription>
          Live probe of <code className="num">/health/deep</code>
          {health.version ? ` · release ${health.version}` : ""}. HTTP{" "}
          {health.httpStatus}.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-4">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <HealthItem
            label="Postgres"
            badge={pg}
            detail={c.postgres?.error ?? "SELECT 1 ok"}
          />
          <HealthItem
            label="Redis"
            badge={
              rd
                ? rd.ok
                  ? { tone: "pass", label: "Healthy" }
                  : rd.configured
                    ? { tone: "fail", label: "Unhealthy" }
                    : { tone: "neutral", label: "Not configured" }
                : { tone: "neutral", label: "Unknown" }
            }
            detail={
              rd
                ? rd.error
                  ? rd.error
                  : rd.expected
                    ? "expected · reachable"
                    : "not expected in this env"
                : "—"
            }
          />
          <HealthItem
            label="Worker"
            badge={wk}
            detail={
              c.worker?.heartbeat_age_seconds != null
                ? `heartbeat ${c.worker.heartbeat_age_seconds}s ago`
                : "no heartbeat"
            }
          />
          <HealthItem
            label="Queue depth"
            badge={{
              tone: "neutral",
              label:
                c.queue?.depth != null ? String(c.queue.depth) : "unknown",
            }}
            detail={c.queue?.name ?? "—"}
          />
        </dl>
      </CardContent>
    </Card>
  );
}

function HealthItem({
  label,
  badge,
  detail,
}: {
  label: string;
  badge: { tone: Tone; label: string };
  detail: string;
}) {
  return (
    <div className="rounded-[var(--radius)] border border-border bg-card p-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-subtle-foreground">
        {label}
      </dt>
      <dd className="mt-1.5">
        <StatusBadge tone={badge.tone} label={badge.label} size="sm" icon={false} />
      </dd>
      <p className="mt-1.5 truncate text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}
