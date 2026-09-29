"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  listConnectorCredentials, probeConnectorCredential, revokeConnectorCredential, saveConnectorCredential,
  type ConnectorAuthType, type ConnectorCredentialProfile, type ConnectorProbe,
} from "@/lib/integrations-api";

const INPUT = "h-10 w-full rounded-md border border-border bg-background px-3 text-sm";
const AUTH_FIELDS: Record<ConnectorAuthType, { name: string; label: string; type?: string; optional?: boolean; defaultValue?: string }[]> = {
  bearer: [{ name: "token", label: "Access token", type: "password" }],
  basic: [{ name: "username", label: "Username" }, { name: "password", label: "Password", type: "password" }],
  oauth2_client_credentials: [
    { name: "token_url", label: "Token endpoint URL", type: "url" },
    { name: "client_id", label: "Client ID" },
    { name: "client_secret", label: "Client secret", type: "password" },
    { name: "scope", label: "Scope (optional)", optional: true },
  ],
  api_key: [{ name: "header_name", label: "API key header", defaultValue: "X-API-Key" }, { name: "api_key", label: "API key", type: "password" }],
};

export function ConnectorCredentials({ connectorId }: { connectorId: string }) {
  const [profiles, setProfiles] = useState<ConnectorCredentialProfile[]>([]);
  const [authType, setAuthType] = useState<ConnectorAuthType>("bearer");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const [probes, setProbes] = useState<Record<string, ConnectorProbe | undefined>>({});
  const sap = connectorId.startsWith("sap_");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    listConnectorCredentials(connectorId).then((rows) => { if (active) setProfiles(rows); })
      .catch((err) => { if (active) setLoadError(err instanceof Error ? err.message : "Could not load saved connections."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [connectorId, reload]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    const text = (name: string) => String(values.get(name) ?? "");
    setBusy("save"); setError(""); setSaved(false);
    try {
      const profile = await saveConnectorCredential({
        connector_id: connectorId, label: text("label"), base_url: text("base_url"), auth_type: authType,
        secret: Object.fromEntries(AUTH_FIELDS[authType].map(({ name }) => [name, text(name)]).filter(([, value]) => value !== "")),
      });
      setProfiles((rows) => [profile, ...rows]);
      form.reset();
      setAuthType("bearer");
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save connection.");
    } finally { setBusy(""); }
  }

  async function act(profile: ConnectorCredentialProfile, action: "test" | "revoke") {
    if (busy) return;
    setBusy(`${action}:${profile.id}`); setError(""); setSaved(false);
    setProbes((prev) => ({ ...prev, [profile.id]: undefined }));
    try {
      if (action === "test") {
        const probe = await probeConnectorCredential(profile.id);
        setProbes((prev) => ({ ...prev, [profile.id]: probe }));
      } else {
        const revoked = await revokeConnectorCredential(profile.id);
        setProfiles((rows) => rows.map((row) => row.id === revoked.id ? revoked : row));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection action failed. Try again.");
    } finally { setBusy(""); }
  }

  return <section aria-label="Vendor connection settings" className="space-y-5 lg:col-span-4">
    <div className="space-y-1 text-sm text-muted-foreground">
      <h3 className="font-semibold text-foreground">Test a vendor connection</h3>
      <p>Save a read-only credential, then test product-read access. The test requests at most one product and discards its contents. BOM reads and API imports are not available yet.</p>
      <p>Use your {sap ? "SAP host or API_PRODUCT_SRV service root" : "Windchill host or ProdMgmt service root"}. The service must be reachable over public HTTPS.</p>
    </div>
    {loadError && <div role="alert" className="text-sm text-destructive">{loadError} <Button variant="secondary" disabled={!!busy} onClick={() => setReload((n) => n + 1)}>Retry loading connections</Button></div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {saved && <p role="status" className="text-sm text-foreground">Connection saved. Use Test connection to check access.</p>}
    <form onSubmit={(event) => void save(event)} className="space-y-4">
      <fieldset disabled={!!busy || loading || !!loadError} className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-3 text-sm font-medium">New connection</legend>
        <label className="space-y-1 text-sm"><span>Connection name</span><input className={INPUT} name="label" required maxLength={120} autoComplete="off" /></label>
        <label className="space-y-1 text-sm"><span>Service URL</span><input className={INPUT} name="base_url" type="url" required maxLength={500} placeholder={sap ? "https://your-sap-host" : "https://your-windchill-host/Windchill/servlet/odata/ProdMgmt"} autoComplete="off" /></label>
        <label className="space-y-1 text-sm"><span>Authentication</span><select className={INPUT} value={authType} onChange={(event) => setAuthType(event.target.value as ConnectorAuthType)}>
          <option value="bearer">Bearer token</option><option value="basic">Username and password</option>
          <option value="oauth2_client_credentials">OAuth client credentials</option><option value="api_key">API key header</option>
        </select></label>
        {AUTH_FIELDS[authType].map((field) => <label key={`${authType}:${field.name}`} className="space-y-1 text-sm"><span>{field.label}</span><input className={INPUT} name={field.name} type={field.type ?? "text"} required={!field.optional} maxLength={8192} defaultValue={field.defaultValue} autoComplete={field.type === "password" ? "new-password" : "off"} /></label>)}
        {authType === "oauth2_client_credentials" && <p className="text-xs text-muted-foreground sm:col-span-2">Uses client_secret_basic authentication at the token endpoint.</p>}
        <p className="text-xs text-muted-foreground sm:col-span-2">Credentials are encrypted on the server and are never returned in the saved profile. Use an account limited to read access.</p>
        <Button type="submit">{busy === "save" ? "Saving…" : "Save connection"}</Button>
      </fieldset>
    </form>
    <div className="space-y-3">
      <h3 className="text-sm font-semibold">Saved connections</h3>
      {loading && <p className="text-sm text-muted-foreground">Loading connections…</p>}
      {!loading && !loadError && profiles.length === 0 && <p className="text-sm text-muted-foreground">No saved connections.</p>}
      {profiles.map((profile) => <article key={profile.id} aria-label={profile.label} className="space-y-2 rounded-md border border-border p-3 text-sm">
        <h4 className="font-medium">{profile.label}</h4>
        <p className="break-all text-muted-foreground">{profile.base_url}</p>
        <p>{profile.revoked_at ? "Revoked" : "Credential saved"}</p>
        {!profile.revoked_at && <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={!!busy} onClick={() => void act(profile, "test")}>{busy === `test:${profile.id}` ? "Testing…" : "Test connection"}</Button>
          <Button variant="secondary" disabled={!!busy} onClick={() => void act(profile, "revoke")}>{busy === `revoke:${profile.id}` ? "Revoking…" : "Revoke connection"}</Button>
        </div>}
        {probes[profile.id] && <p role={probes[profile.id]!.connected ? "status" : "alert"} className={probes[profile.id]!.connected ? "text-emerald-700" : "text-destructive"}>
          {probes[profile.id]!.connected ? `Product read succeeded (${probes[profile.id]!.records_read} record checked). BOM reads and imports have not been tested.` : `Connection failed: ${probes[profile.id]!.reason}`}
        </p>}
      </article>)}
    </div>
  </section>;
}
