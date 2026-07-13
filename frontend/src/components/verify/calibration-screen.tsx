"use client";

/**
 * CALIBRATION & TRUTH — the governed-truth surface of the product "light
 * instrument", recreated from `Product - Verify.dc.html` (SCREEN: SETTINGS) and
 * wired to the REAL engine. What the engine knows about your floor, and how it
 * earns accuracy.
 *
 * Every number here is a real engine/DB output or is WITHHELD:
 *   - RATES        → rate-library /effective + versions (governed card the engine
 *                    actually costs against, or the built-in default v0).
 *   - THE HALLMARK → ground-truth records + /recalibrate. A band flips SOLID only
 *                    when recalibrate returns validated=true from REAL held-out
 *                    residuals; below the floor it is REFUSED and stays hatched.
 *   - GOVERNED CHANGE → governance change-requests (versioned, approve/reject).
 *   - MEMBERS      → admin /users (+ role PATCH). Gated to org-admin (honest).
 *   - AUDIT LOG    → admin /audit-log (immutable, CSV-exportable).
 *   - API KEYS     → /api/v1/keys (real; prefix only).
 *   - USAGE        → admin /usage-summary (real persisted counters).
 *   - WEBHOOKS     → admin /webhook-deliveries (real delivery log).
 *
 * The design's demo org (Midwest Precision CNC, v13, $52→$54, 214 verifications,
 * fake webhook deliveries) is ILLUSTRATIVE mockup data and is NOT reproduced.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { C, MONO } from "@/lib/verify/tokens";
import { GROUND_TRUTH_CSV_INPUT } from "@/lib/verify/file-inputs";
import {
  Card,
  Kicker,
  ProvChip,
  GhostButton,
  Spinner,
} from "./primitives";
import {
  ApiError,
  listRateVersions,
  effectiveRateCard,
  readCardRates,
  countMaterialPrices,
  listChangeRequests,
  approveChangeRequest,
  rejectChangeRequest,
  listGroundTruth,
  recalibrate,
  importGroundTruthCsv,
  listMembers,
  updateMemberRole,
  getAuditLog,
  auditLogCsvUrl,
  getUsageSummary,
  listWebhookDeliveries,
  listKeys,
  ASSIGNABLE_ROLES,
  type RateVersionsPage,
  type EffectiveRateCard,
  type RateEntry,
  type ChangeRequest,
  type GroundTruthRecord,
  type RecalibrateResult,
  type InsufficientGroundTruth,
  type Member,
  type AuditEntry,
  type UsageSummary,
  type WebhookDelivery,
  type ApiKey,
} from "@/lib/verify/calibration-api";

function isGated(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 403 || e.status === 401);
}
function msg(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

// ── screen ──────────────────────────────────────────────────────────────────

export function CalibrationScreen() {
  return (
    <main
      style={{
        animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both",
        flex: 1,
        overflowY: "auto",
        padding: "30px 34px",
        background: C.bg,
      }}
    >
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>
        Calibration &amp; truth
      </h1>
      <p style={{ margin: "8px 0 0", maxWidth: 640, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        What the engine knows about your floor, and how it earns accuracy. Governed rates are
        versioned, not edited; gaps stay visible defaults; validation only ever comes from your
        actuals.
      </p>

      <div style={{ marginTop: 24, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, maxWidth: 1100, alignItems: "start" }}>
        <RatesPanel />
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <HallmarkPanel />
          <ApiUsagePanel />
          <GovernedChangePanel />
        </div>
      </div>

      <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, maxWidth: 1100, alignItems: "start" }}>
        <MembersPanel />
        <WebhooksPanel />
      </div>

      <AuditLogPanel />
    </main>
  );
}

// ── RATES — rate-library effective card + versions ───────────────────────────

function RatesPanel() {
  const [eff, setEff] = useState<EffectiveRateCard | null>(null);
  const [page, setPage] = useState<RateVersionsPage | null>(null);
  const [rates, setRates] = useState<RateEntry[] | null>(null);
  const [matCount, setMatCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const [e, p] = await Promise.all([effectiveRateCard(), listRateVersions()]);
        if (dead) return;
        setEff(e);
        setPage(p);
        // If a governed card is in effect, read the actual rate values it carries.
        if (e.using_governed && e.payload) {
          setRates(readCardRates(e.payload));
          setMatCount(countMaterialPrices(e.payload));
        } else {
          setRates([]);
        }
      } catch (err) {
        if (!dead) {
          setError(msg(err, "could not load rate library"));
          setRates([]);
        }
      }
    })();
    return () => {
      dead = true;
    };
  }, []);

  const versions = page?.versions ?? [];
  const published = versions.filter((v) => v.status === "published" || v.is_published);
  const drafts = versions.filter((v) => v.status === "draft");
  const governed = !!eff?.using_governed;
  const effRow = governed ? published.find((v) => v.status === "published") ?? published[0] : null;

  return (
    <Card style={{ padding: "20px 22px" }}>
      {rates === null ? (
        <Spinner label="loading rate library…" />
      ) : governed ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <Kicker color={C.ink}>GOVERNED CARD IN EFFECT</Kicker>
            <ProvChip p="DEFAULT" />
          </div>
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
            {effRow ? `v${effRow.version ?? "?"}${effRow.name ? ` · ${effRow.name}` : ""}` : "published card"}
            {effRow?.effective_from ? ` · effective ${fmtDate(effRow.effective_from)}` : ""}
          </p>
          {rates.length > 0 ? (
            <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 7 }}>
              {rates.map((r) => (
                <span
                  key={r.key}
                  style={{
                    display: "inline-flex",
                    whiteSpace: "nowrap",
                    gap: 5,
                    border: `1px solid ${C.hair}`,
                    borderRadius: 8,
                    padding: "6px 12px",
                    fontFamily: MONO,
                    fontSize: 11.5,
                    color: C.ink70,
                  }}
                >
                  {r.key} <span style={{ color: C.ink }}>{r.value}</span>
                </span>
              ))}
            </div>
          ) : (
            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>
              card in effect · rate values withheld by the API on this view
            </p>
          )}
          {matCount > 0 && (
            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
              + {matCount} material price{matCount === 1 ? "" : "s"} overridden
            </p>
          )}
          <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink40 }}>
            a governed card is org-authored DEFAULT assumptions — never a measurement. Every verdict
            pins the rate version it was computed with.
          </p>
        </>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <Kicker>DEFAULT RATE TABLE (v0)</Kicker>
            <ProvChip p="DEFAULT" />
          </div>
          <p style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.6, color: C.ink55 }}>
            No governed rate card is in effect — the engine is costing against the built-in default
            table (v0): generic assumptions, not your floor.
          </p>
          <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 7, fontFamily: MONO, fontSize: 11.5 }}>
            <RowKV k="authored versions" v={String(versions.length)} />
            <RowKV k="published" v={String(published.length)} />
            <RowKV k="drafts" v={String(drafts.length)} />
            <RowKV
              k="rate-library flag"
              v={page?.flag_enabled ? "enabled" : "off"}
              vColor={page?.flag_enabled ? C.pass : C.ink45}
            />
          </div>
          {!page?.flag_enabled && (
            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink40 }}>
              rate-library is behind a backend flag; until it is enabled and a card is published,
              costing uses the default table.
            </p>
          )}
        </>
      )}
      {error && (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>
          couldn&apos;t load rate library — {error}
        </p>
      )}
    </Card>
  );
}

// ── THE HALLMARK — ground-truth flywheel ─────────────────────────────────────

function HallmarkPanel() {
  const [records, setRecords] = useState<GroundTruthRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RecalibrateResult | null>(null);
  const [shortfall, setShortfall] = useState<InsufficientGroundTruth | null>(null);
  const csvRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const page = await listGroundTruth();
      setRecords(page.records);
      setError(null);
    } catch (err) {
      // ground-truth GET returns 403 when the caller has no org — honest empty.
      setRecords([]);
      setError(isGated(err) ? null : msg(err, "could not load ground truth"));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const nReal = (records ?? []).filter((r) => !r.stand_in).length;
  const nStandin = (records ?? []).filter((r) => r.stand_in).length;
  const validated = !!result?.validated;

  const onRecalibrate = useCallback(async () => {
    setBusy(true);
    setShortfall(null);
    try {
      const r = await recalibrate();
      setResult(r);
      if (r.validated) {
        toast.success(`Bands flipped: measured · ${r.claim ?? "held-out residuals"}`);
      } else {
        toast.message("Recalibrated — bands stay hatched", {
          description: "no REAL held-out residuals yet; 'validated' only ever means measured",
        });
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const body = err.body as { detail?: InsufficientGroundTruth } | null;
        if (body?.detail) setShortfall(body.detail);
        toast.message("Recalibration refused — below the floor", {
          description: body?.detail
            ? `${body.detail.n_real} real of ${body.detail.min_real} needed · band stays hatched`
            : "insufficient real ground truth",
        });
      } else {
        toast.error(msg(err, "recalibration failed"));
      }
    } finally {
      setBusy(false);
    }
  }, []);

  const onCsv = useCallback(
    async (file: File) => {
      setBusy(true);
      try {
        const s = await importGroundTruthCsv(file);
        toast.success(`Sent reality back: ${s.imported} imported · skipped ${s.skipped}`);
        if (s.errors.length) {
          toast.message(`${s.errors.length} row error(s)`, {
            description: s.errors.slice(0, 3).map((e) => `line ${e.line}: ${e.reason}`).join(" · "),
          });
        }
        await refresh();
      } catch (err) {
        toast.error(msg(err, "import failed"));
      } finally {
        setBusy(false);
      }
    },
    [refresh]
  );

  const statusText = validated
    ? `validated (measured)${result?.claim ? ` · ${result.claim}` : ""} · from ${result?.n_real} real held-out records`
    : `validation status: n=${nReal} real · every band hatched · 'validated' here will only ever mean measured`;

  return (
    <section style={{ border: `1.5px solid ${C.ink}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <Kicker color={C.ink}>THE HALLMARK — GROUND-TRUTH FLYWHEEL</Kicker>

      <div style={{ marginTop: 12, border: `1.5px dashed #c9cbd0`, borderRadius: 12, padding: 18, textAlign: "center" }}>
        <p style={{ margin: 0, fontSize: 13.5, fontWeight: 500 }}>Send reality back</p>
        <p style={{ margin: "6px 0 0", fontSize: 11.5, color: C.ink45 }}>
          drop actual hours &amp; invoiced costs (CSV) — the engine validates on parts it never saw
        </p>
        <div style={{ marginTop: 12, display: "flex", justifyContent: "center", gap: 10, flexWrap: "wrap" }}>
          <GhostButton
            primary
            disabled={busy}
            aria-label="Choose ground-truth actuals CSV"
            aria-controls={GROUND_TRUTH_CSV_INPUT.id}
            onClick={() => csvRef.current?.click()}
          >
            {busy ? "Working…" : "Send actuals (CSV)"}
          </GhostButton>
          <GhostButton disabled={busy} onClick={onRecalibrate}>
            Recalibrate
          </GhostButton>
          <input
            ref={csvRef}
            id={GROUND_TRUTH_CSV_INPUT.id}
            name={GROUND_TRUTH_CSV_INPUT.name}
            data-testid={GROUND_TRUTH_CSV_INPUT.testId}
            aria-label={GROUND_TRUTH_CSV_INPUT.ariaLabel}
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void onCsv(f);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      {/* current ground-truth state — REAL counts, never a fixture */}
      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 7, fontFamily: MONO, fontSize: 11.5 }}>
        {records === null ? (
          <Spinner label="loading ground truth…" />
        ) : (
          <>
            <RowKV k="real records (held-out pool)" v={String(nReal)} vColor={nReal > 0 ? C.ink : C.ink45} />
            <RowKV k="stand-ins (never validate)" v={String(nStandin)} vColor={C.ink45} />
            <RowKV k="floor to validate" v="8 real" vColor={C.ink45} />
          </>
        )}
      </div>

      {/* the band: SOLID only when validated=true from REAL residuals */}
      <div style={{ marginTop: 14, position: "relative", height: 7, borderRadius: 4, background: "#ececef", overflow: "hidden" }}>
        {!validated && (
          <span
            style={{
              position: "absolute",
              inset: 0,
              backgroundImage: "repeating-linear-gradient(135deg, rgba(23,24,26,0.35) 0 2px, transparent 2px 7px)",
            }}
          />
        )}
        {validated && (
          <span style={{ position: "absolute", inset: 0, background: "rgba(31,138,91,0.8)" }} />
        )}
        <span aria-hidden style={{ position: "absolute", top: -2, bottom: -2, left: "50%", width: 2, background: C.ink }} />
      </div>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: validated ? C.pass : C.cond }}>
        {statusText}
      </p>

      {shortfall && (
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.cond }}>
          recalibration refused: {shortfall.n_real} real of {shortfall.min_real} needed —{" "}
          {shortfall.reason}
        </p>
      )}

      {result && result.n_skipped > 0 && (
        <div
          role="status"
          style={{ marginTop: 10, border: `1px solid ${C.cond}`, borderRadius: 8, padding: "9px 10px" }}
        >
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.cond }}>
            {result.n_skipped} record{result.n_skipped === 1 ? "" : "s"} could not be costed; the
            calibration excluded them.
          </p>
          {(result.skipped ?? []).slice(0, 3).map((item) => (
            <p key={`${item.part_id}-${item.process}-${item.quantity}`} style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
              {item.part_id} · {item.process} × {item.quantity}: {item.reason}
            </p>
          ))}
        </div>
      )}

      <div style={{ marginTop: 14, borderTop: `1px solid #efeff2`, paddingTop: 10 }}>
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.7 }}>
          what happens when enough actuals arrive: received → residuals on held-out parts the model
          never saw → the flip (hatched → solid, the word becomes &ldquo;measured&rdquo;) → the org
          ripple across records.
        </p>
      </div>
      {error && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>
          couldn&apos;t load ground truth — {error}
        </p>
      )}
    </section>
  );
}

// ── API & USAGE — real keys + persisted usage counters ──────────────────────

function ApiUsagePanel() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    listKeys().then(
      (k) => !dead && setKeys(k),
      (e) => {
        if (!dead) {
          setKeys([]);
          setError(isGated(e) ? null : msg(e, "could not load keys"));
        }
      }
    );
    return () => {
      dead = true;
    };
  }, []);

  useEffect(() => {
    let dead = false;
    getUsageSummary(30).then(
      (u) => !dead && setUsage(u),
      (e) => {
        if (!dead) {
          setUsage(null);
          setUsageError(isGated(e) ? "org-admin required to read usage" : msg(e, "could not load usage"));
        }
      }
    );
    return () => {
      dead = true;
    };
  }, []);

  const active = (keys ?? []).filter((k) => !k.revoked_at);
  const counts = usage?.counts;

  return (
    <Card style={{ padding: "20px 22px" }}>
      <Kicker>API &amp; USAGE</Kicker>

      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 7, fontFamily: MONO, fontSize: 11.5 }}>
        {usage === null && !usageError ? (
          <Spinner label="loading usage…" />
        ) : (
          <>
            <RowKV k="DFM analyses (30d)" v={String(counts?.analyses ?? 0)} vColor={counts?.analyses ? C.ink : C.ink45} />
            <RowKV k="saved cost decisions (30d)" v={String(counts?.cost_decisions ?? 0)} vColor={counts?.cost_decisions ? C.ink : C.ink45} />
            <RowKV k="usage-event rows (30d)" v={String(counts?.usage_events ?? 0)} vColor={counts?.usage_events ? C.ink : C.ink45} />
            <RowKV k="webhook deliveries (30d)" v={String(counts?.webhook_deliveries ?? 0)} vColor={counts?.webhook_deliveries ? C.ink : C.ink45} />
          </>
        )}
      </div>
      {usageError ? (
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.cond }}>
          {usageError}
        </p>
      ) : (
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
          read from analyses, cost_decisions, usage_events, and webhook_deliveries — live persisted counters
        </p>
      )}

      {/* real developer keys (prefix only; the secret is shown once at creation) */}
      <div style={{ marginTop: 16 }}>
        <Kicker>DEVELOPER KEYS</Kicker>
        {keys === null ? (
          <div style={{ marginTop: 10 }}>
            <Spinner label="loading keys…" />
          </div>
        ) : active.length === 0 ? (
          <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>
            no API keys yet — create one in Settings → Developer
          </p>
        ) : (
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
            {active.map((k) => (
              <div key={k.id} style={{ display: "flex", alignItems: "center", gap: 10, fontFamily: MONO, fontSize: 11.5 }}>
                <span style={{ border: `1px solid ${C.hair}`, borderRadius: 8, padding: "7px 12px", color: C.ink60, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {k.prefix}••••••••••••
                </span>
                <span style={{ color: C.ink45 }}>{k.name}</span>
              </div>
            ))}
          </div>
        )}
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
          POST /api/v1/validate returns the same record this UI renders — nothing withheld · secret
          shown once at creation
        </p>
      </div>
      {error && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>
          couldn&apos;t load keys — {error}
        </p>
      )}
    </Card>
  );
}

// ── GOVERNED CHANGE — governance change-requests ─────────────────────────────

function GovernedChangePanel() {
  const [reqs, setReqs] = useState<ChangeRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const p = await listChangeRequests();
      setReqs(p.change_requests);
      setError(null);
    } catch (err) {
      setReqs([]);
      setError(isGated(err) ? null : msg(err, "could not load change requests"));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onApprove = useCallback(
    async (id: number) => {
      setActing(id);
      try {
        await approveChangeRequest(id);
        toast.success("Approved — the draft is published as a new version");
        await refresh();
      } catch (err) {
        toast.error(isGated(err) ? "requires org-admin to approve" : msg(err, "approve failed"));
      } finally {
        setActing(null);
      }
    },
    [refresh]
  );

  const onReject = useCallback(
    async (id: number) => {
      setActing(id);
      try {
        await rejectChangeRequest(id);
        toast.success("Rejected — the draft stays a draft");
        await refresh();
      } catch (err) {
        toast.error(isGated(err) ? "requires org-admin to reject" : msg(err, "reject failed"));
      } finally {
        setActing(null);
      }
    },
    [refresh]
  );

  const pending = (reqs ?? []).filter((r) => r.status === "proposed");

  return (
    <Card style={{ padding: "20px 22px" }}>
      <Kicker>GOVERNED CHANGE — RATES ARE VERSIONED, NOT EDITED</Kicker>
      {reqs === null ? (
        <div style={{ marginTop: 12 }}>
          <Spinner label="loading change requests…" />
        </div>
      ) : reqs.length === 0 ? (
        <p style={{ margin: "12px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
          No pending rate changes. A change is proposed, reviewed, and published as a new version —
          never edited in place. Every verdict pins the version it was computed with.
        </p>
      ) : (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 14 }}>
          {reqs.slice(0, 5).map((r) => (
            <ChangeRequestRow
              key={r.id}
              r={r}
              acting={acting === r.id}
              onApprove={() => onApprove(r.id)}
              onReject={() => onReject(r.id)}
            />
          ))}
        </div>
      )}
      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink40 }}>
        {pending.length > 0
          ? `${pending.length} awaiting review · approving publishes the target draft`
          : "reopen a record from last quarter, see that quarter's rates, not today's"}
      </p>
      {error && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>
          couldn&apos;t load change requests — {error}
        </p>
      )}
    </Card>
  );
}

function ChangeRequestRow({
  r,
  acting,
  onApprove,
  onReject,
}: {
  r: ChangeRequest;
  acting: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div style={{ borderTop: `1px solid #f0f0f3`, paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 12, flexWrap: "wrap" }}>
        <span style={{ color: C.ink }}>{r.title || `${r.asset_type} change #${r.id}`}</span>
        <span style={{ color: C.ink40 }}>· {r.asset_type} v{r.target_version_id}</span>
        {r.proposed_by != null && <span style={{ color: C.ink40 }}>· proposed by user #{r.proposed_by}</span>}
      </div>
      {r.note && <p style={{ margin: "4px 0 0", fontSize: 12, color: C.ink55 }}>{r.note}</p>}
      <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 10, flexWrap: "wrap" }}>
        <Stage on label="PROPOSED ✓" tone="pass" />
        <Arrow />
        {r.status === "proposed" ? (
          <>
            <Stage on solid label="IN REVIEW" tone="ink" />
            <Arrow />
            <Stage label="APPROVE" />
            <Arrow />
            <Stage label="PUBLISH new version" />
          </>
        ) : r.status === "approved" ? (
          <>
            <Stage on label="REVIEWED ✓" tone="pass" />
            <Arrow />
            <Stage on label="APPROVED ✓" tone="pass" />
            <Arrow />
            <Stage on label="PUBLISHED ✓" tone="pass" />
          </>
        ) : (
          <Stage on label="REJECTED ✕" tone="fail" />
        )}
      </div>
      {r.status === "proposed" && (
        <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
          <GhostButton primary disabled={acting} onClick={onApprove} style={{ padding: "6px 14px", fontSize: 12 }}>
            {acting ? "…" : "Approve & publish"}
          </GhostButton>
          <GhostButton disabled={acting} onClick={onReject} style={{ padding: "6px 14px", fontSize: 12 }}>
            Reject
          </GhostButton>
        </div>
      )}
    </div>
  );
}

function Stage({ on, solid, label, tone = "ink" }: { on?: boolean; solid?: boolean; label: string; tone?: "pass" | "fail" | "ink" }) {
  const color = tone === "pass" ? C.pass : tone === "fail" ? C.fail : C.ink;
  return (
    <span
      style={{
        borderRadius: 999,
        padding: "4px 11px",
        border: on ? `${solid ? 1.5 : 1}px solid ${color}` : `1px dashed #d3d3d8`,
        color: on ? color : C.ink40,
        background: "transparent",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
function Arrow() {
  return <span style={{ color: C.ink35 }}>→</span>;
}

// ── MEMBERS & ROLES — admin /users ───────────────────────────────────────────

function MembersPanel() {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const p = await listMembers();
      setMembers(p.users);
      setGated(false);
      setError(null);
    } catch (err) {
      if (isGated(err)) {
        setGated(true);
        setMembers([]);
      } else {
        setMembers([]);
        setError(msg(err, "could not load members"));
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onRole = useCallback(
    async (m: Member, role: string) => {
      setSaving(m.id);
      try {
        await updateMemberRole(m.id, role);
        toast.success(`${m.email} → ${role}`);
        await refresh();
      } catch (err) {
        toast.error(msg(err, "role change failed"));
        await refresh();
      } finally {
        setSaving(null);
      }
    },
    [refresh]
  );

  return (
    <Card style={{ padding: "20px 22px" }}>
      <Kicker>MEMBERS &amp; ROLES</Kicker>
      {members === null ? (
        <div style={{ marginTop: 12 }}>
          <Spinner label="loading members…" />
        </div>
      ) : gated ? (
        <p style={{ margin: "12px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
          Org-admin required to view and manage members. Roles gate actions, never visibility of
          provenance — every member can open every number.
        </p>
      ) : members.length === 0 ? (
        <p style={{ margin: "12px 0 0", fontSize: 12.5, color: C.ink55 }}>No members to show.</p>
      ) : (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column" }}>
          {members.map((m) => (
            <div key={m.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 2px", borderBottom: `1px solid #f0f0f3` }}>
              <span style={{ width: 26, height: 26, borderRadius: "50%", background: "#e4e5e8", color: C.ink, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 600, textTransform: "uppercase" }}>
                {(m.email || "?").slice(0, 1)}
              </span>
              <span style={{ flex: 1, fontSize: 13, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {m.email}
                {m.org_role && (
                  <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}> · org {m.org_role}</span>
                )}
              </span>
              <select
                value={ASSIGNABLE_ROLES.includes(m.role as (typeof ASSIGNABLE_ROLES)[number]) ? m.role : "viewer"}
                disabled={saving === m.id}
                onChange={(e) => onRole(m, e.target.value)}
                style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink, border: `1px solid #d8d8dc`, borderRadius: 999, padding: "4px 10px", background: C.panel, cursor: "pointer" }}
              >
                {ASSIGNABLE_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
                {!ASSIGNABLE_ROLES.includes(m.role as (typeof ASSIGNABLE_ROLES)[number]) && (
                  <option value={m.role}>{m.role}</option>
                )}
              </select>
            </div>
          ))}
        </div>
      )}
      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
        roles gate actions, never visibility of provenance — every member can open every number
      </p>
      {error && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>
          couldn&apos;t load members — {error}
        </p>
      )}
    </Card>
  );
}

// ── WEBHOOKS — real delivery log ─────────────────────────────────────────────

function WebhooksPanel() {
  const [deliveries, setDeliveries] = useState<WebhookDelivery[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    listWebhookDeliveries(12).then(
      (p) => !dead && setDeliveries(p.deliveries),
      (e) => {
        if (!dead) {
          setDeliveries([]);
          setError(isGated(e) ? "org-admin required to read delivery log" : msg(e, "could not load deliveries"));
        }
      }
    );
    return () => {
      dead = true;
    };
  }, []);

  return (
    <Card style={{ padding: "20px 22px" }}>
      <Kicker>WEBHOOKS — THE RECORD, PUSHED</Kicker>
      <p style={{ margin: "12px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
        Push the full verification record — with provenance, the same JSON the API returns — to your
        PLM/ERP on <span style={{ fontFamily: MONO, fontSize: 11.5, color: C.ink }}>verification.completed</span>,{" "}
        <span style={{ fontFamily: MONO, fontSize: 11.5, color: C.ink }}>validation.flipped</span>, and more.
      </p>
      <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 7, fontFamily: MONO, fontSize: 10.5 }}>
        {["verification.completed", "validation.flipped", "triage.finished", "decision.recorded"].map((e) => (
          <span key={e} style={{ border: `1px solid #dcdce0`, color: C.ink50, borderRadius: 999, padding: "5px 12px" }}>
            {e}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 12, borderTop: `1px solid #efeff2`, paddingTop: 10 }}>
        {deliveries === null ? (
          <Spinner label="loading deliveries…" />
        ) : deliveries.length === 0 ? (
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: error ? C.cond : C.ink45, lineHeight: 1.6 }}>
            {error ?? "no webhook deliveries recorded yet — the log is empty because no batch webhook has fired"}
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", fontFamily: MONO, fontSize: 10.5 }}>
            {deliveries.map((d) => (
              <div key={d.id} style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr 0.6fr 1fr", gap: 10, alignItems: "center", padding: "9px 0", borderBottom: `1px solid #f0f0f3` }}>
                <span style={{ color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.event_type}</span>
                <span style={{ color: d.status === "delivered" ? C.pass : d.status === "failed" ? C.fail : C.cond }}>{d.status}</span>
                <span style={{ color: C.ink45 }}>{d.response_code ?? "—"} · {d.attempts}x</span>
                <span style={{ color: C.ink45, textAlign: "right" }}>{fmtStamp(d.last_attempt_at ?? d.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

// ── AUDIT LOG — admin /audit-log ─────────────────────────────────────────────

function AuditLogPanel() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [gated, setGated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    getAuditLog(30).then(
      (p) => !dead && setEntries(p.entries),
      (err) => {
        if (dead) return;
        if (isGated(err)) {
          setGated(true);
          setEntries([]);
        } else {
          setEntries([]);
          setError(msg(err, "could not load audit log"));
        }
      }
    );
    return () => {
      dead = true;
    };
  }, []);

  return (
    <section style={{ marginTop: 16, maxWidth: 1100, border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Kicker>AUDIT LOG — IMMUTABLE, EXPORTABLE</Kicker>
        {!gated && entries && entries.length > 0 && (
          <a
            href={auditLogCsvUrl(30)}
            style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10.5, color: C.measured, textDecoration: "none" }}
          >
            export CSV →
          </a>
        )}
      </div>
      {entries === null ? (
        <div style={{ marginTop: 12 }}>
          <Spinner label="loading audit log…" />
        </div>
      ) : gated ? (
        <p style={{ margin: "12px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
          Org-admin required to read the audit log — the record behind the records.
        </p>
      ) : entries.length === 0 ? (
        <p style={{ margin: "12px 0 0", fontSize: 12.5, color: C.ink55 }}>
          No audit entries in the last 30 days. Every verdict, decision, and rate change lands here.
        </p>
      ) : (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", fontFamily: MONO, fontSize: 11.5 }}>
          {entries.slice(0, 40).map((e) => (
            <div key={e.id} style={{ display: "flex", gap: 16, padding: "10px 2px", borderBottom: `1px solid #f0f0f3` }}>
              <span style={{ color: C.ink40, minWidth: 132, flexShrink: 0 }}>{fmtStamp(e.timestamp)}</span>
              <span style={{ color: C.ink, minWidth: 150, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {e.user_email || (e.user_id != null ? `user #${e.user_id}` : "system")}
              </span>
              <span style={{ color: C.ink60 }}>
                {e.action}
                {e.resource_type ? ` · ${e.resource_type}${e.resource_id ? ` ${e.resource_id}` : ""}` : ""}
                {e.result_summary ? ` · ${e.result_summary}` : ""}
              </span>
            </div>
          ))}
        </div>
      )}
      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
        every verdict, decision, and rate change lands here — the record behind the records
      </p>
      {error && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>
          couldn&apos;t load audit log — {error}
        </p>
      )}
    </section>
  );
}

// ── shared bits ──────────────────────────────────────────────────────────────

function RowKV({ k, v, vColor = C.ink }: { k: string; v: string; vColor?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span style={{ color: C.ink45 }}>{k}</span>
      <span style={{ color: vColor }}>{v}</span>
    </div>
  );
}

function fmtDate(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
