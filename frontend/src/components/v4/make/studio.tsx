"use client";

/**
 * Design Studio (board F1). Describe a part in plain words and local rules fill
 * the form (no AI), or pick a template; Generate makes a real, immutable CAD
 * revision in an isolated kernel. Each design keeps its revisions: view any of
 * them on the turntable, compare two (plan and generated summary, with both
 * previews), download a revision's STEP, or open it in a check.
 *
 * Writes are role-gated (canMutateWorkspace) and on every plan, the free trial
 * included; viewers get the library read-only. The server limits how many
 * designs or revisions a free account generates an hour and a day, and says so.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import {
  DEFAULT_DESIGN_FORM,
  buildDesignPlan,
  designRevisionRefreshKey,
  formFromDesign,
  formFromPlan,
  resolveViewedRevisionNo,
  validateDesignForm,
  type DesignForm,
  type TemplateKind,
} from "@/lib/design-plan";
import {
  archiveDesign,
  compareDesignRevisions,
  createDesign,
  createDesignRevision,
  DesignApiError,
  designRevisionPreviewUrl,
  designRevisionStepUrl,
  interpretDesignPrompt,
  listDesignRevisions,
  listDesigns,
  type Design,
  type DesignRevision,
  type DesignRevisionComparison,
} from "@/lib/designs-api";
import { R } from "../routes";
import { useRegisterPaletteItems } from "../palette";
import { Chip, Empty, Loading, Row, cx } from "../ui";
import { MakeHead, MakeWorld, errorText, useToast } from "./head";
import { Turntable, type StageLayer, type StageState } from "./turntable";
import {
  INTERPRET_IDLE,
  TEMPLATES,
  checkHref,
  countText,
  defaultPair,
  designChip,
  diffRows,
  draftField,
  envelopeText,
  fieldProblem,
  fieldsFor,
  formatBytes,
  interpretView,
  kindLabel,
  revisionSub,
  sameRevisionPair,
  viewText,
  volumeText,
  type InterpretView,
} from "./studio-model";

type History = { owner: string | null; state: "idle" | "loading" | "ready" | "error"; revs: DesignRevision[]; err: string | null };

function KindGlyph({ kind }: { kind: string | undefined }) {
  const s = { stroke: "currentColor", strokeWidth: 1.6, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      {kind === "bracket" ? (
        <path {...s} d="M5 19h16v3H5zM5 5h3v14H5z" />
      ) : kind === "enclosure" ? (
        <path {...s} d="M4 8h18v12H4zM4 8l3-3h12l3 3" />
      ) : (
        <>
          <path {...s} d="M3 10h20v6H3z" />
          <circle cx="7" cy="13" r="1.2" fill="currentColor" />
          <circle cx="19" cy="13" r="1.2" fill="currentColor" />
        </>
      )}
    </svg>
  );
}

function previewLayers(designId: string | null, rev: Pick<DesignRevision, "number" | "status" | "geometry_hash"> | null | undefined): StageLayer[] {
  if (!designId || !rev) return [];
  const url = designRevisionPreviewUrl(designId, rev);
  return url ? [{ key: `r${rev.number}`, source: { kind: "stl-url", url }, look: "solid" }] : [];
}

export function StudioScreen() {
  const { user } = useAuth();
  const canMutate = canMutateWorkspace(user?.role);
  const writable = canMutate;

  const [designs, setDesigns] = React.useState<Design[] | null>(null);
  const [listErr, setListErr] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [history, setHistory] = React.useState<History>({ owner: null, state: "idle", revs: [], err: null });
  const [historyKey, setHistoryKey] = React.useState(0);
  const [view, setView] = React.useState<number | null>(null);
  const [from, setFrom] = React.useState<number | null>(null);
  const [to, setTo] = React.useState<number | null>(null);
  const [diff, setDiff] = React.useState<DesignRevisionComparison | null>(null);
  const [diffBusy, setDiffBusy] = React.useState(false);
  const [diffErr, setDiffErr] = React.useState<string | null>(null);
  const diffRun = React.useRef(0);
  const [form, setForm] = React.useState<DesignForm>({ ...DEFAULT_DESIGN_FORM });
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [prompt, setPrompt] = React.useState("");
  const [interp, setInterp] = React.useState<InterpretView>(INTERPRET_IDLE);
  const [interpreting, setInterpreting] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const submitLock = React.useRef(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [asking, setAsking] = React.useState(false);
  const [archiving, setArchiving] = React.useState(false);
  const [previewState, setPreviewState] = React.useState<StageState>("loading");
  const [previewTry, setPreviewTry] = React.useState(0);
  const [toastNode, toast] = useToast();
  const archiveBtn = React.useRef<HTMLButtonElement>(null);
  const keepBtn = React.useRef<HTMLButtonElement>(null);
  const nameRef = React.useRef<HTMLInputElement>(null);

  const selected = React.useMemo(() => designs?.find((d) => d.id === selectedId) ?? designs?.[0] ?? null, [designs, selectedId]);

  /* ---------- the designs list (polls while one generates) ---------- */
  const refresh = React.useCallback(async (quiet = false) => {
    if (!quiet) setRefreshing(true);
    try {
      const next = await listDesigns();
      setDesigns(next);
      setSelectedId((cur) => (cur && next.some((d) => d.id === cur) ? cur : next[0]?.id ?? null));
      setListErr(null);
    } catch (e) {
      setListErr(errorText(e, "Designs didn’t load."));
      setDesigns((cur) => cur ?? []);
    } finally {
      if (!quiet) setRefreshing(false);
    }
  }, []);
  React.useEffect(() => {
    void refresh();
  }, [refresh]);
  const generating = !!designs?.some((d) => d.status === "generating");
  React.useEffect(() => {
    if (!generating) return;
    const t = window.setInterval(() => void refresh(true), 1500);
    return () => window.clearInterval(t);
  }, [generating, refresh]);

  /* ---------- revision history of the selected design ---------- */
  const refreshKey = designRevisionRefreshKey(selected);
  const selId = selected?.id ?? null;
  const selCurrent = selected?.current_revision ?? null;
  const lastOwner = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!refreshKey || !selId || selCurrent == null) {
      setHistory({ owner: null, state: "idle", revs: [], err: null });
      setView(null);
      lastOwner.current = null;
      return;
    }
    const changed = lastOwner.current !== selId;
    lastOwner.current = selId;
    setHistory((h) => ({ owner: selId, state: "loading", revs: changed ? [] : h.revs, err: null }));
    if (changed) setView(selCurrent);
    let live = true;
    listDesignRevisions(selId).then(
      (revs) => {
        if (!live) return;
        setHistory({ owner: selId, state: "ready", revs, err: null });
        setView((cur) => resolveViewedRevisionNo(cur, revs, selCurrent, changed));
      },
      (e) => {
        if (live) setHistory((h) => ({ ...h, state: "error", err: errorText(e, "Revision history didn’t load.") }));
      },
    );
    return () => {
      live = false;
    };
  }, [refreshKey, selId, selCurrent, historyKey]);

  const revs = (selected && history.owner === selected.id && history.revs.length ? history.revs : selected?.revision ? [selected.revision] : [])
    .slice()
    .sort((a, b) => a.number - b.number);
  const viewed = revs.find((r) => r.number === view) ?? selected?.revision ?? null;
  const viewNo = viewed?.number ?? selected?.current_revision ?? 1;
  const geometry = viewed?.geometry ?? null;
  const readyRevs = revs.filter((r) => r.status === "ready").sort((a, b) => a.number - b.number);
  const readySig = readyRevs.map((r) => r.id).join("|");

  // Compare defaults to the two newest ready revisions; a new pair clears the old answer.
  React.useEffect(() => {
    const pair = defaultPair(readyRevs);
    if (!pair) {
      setFrom(null);
      setTo(null);
    } else {
      setFrom((cur) => (cur != null && readyRevs.some((r) => r.number === cur) ? cur : pair[0]));
      setTo((cur) => (cur != null && readyRevs.some((r) => r.number === cur) ? cur : pair[1]));
    }
    // Revision identity is the server ids, not array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selId, readySig]);
  React.useEffect(() => {
    ++diffRun.current;
    setDiff(null);
    setDiffErr(null);
    setDiffBusy(false);
  }, [refreshKey, from, to]);

  const runCompare = async () => {
    if (!selected || from == null || to == null || from === to || diffBusy) return;
    const id = ++diffRun.current;
    setDiffBusy(true);
    setDiffErr(null);
    try {
      const c = await compareDesignRevisions(selected.id, from, to);
      if (id === diffRun.current) setDiff(c);
    } catch (e) {
      if (id === diffRun.current) setDiffErr(errorText(e, "The compare didn’t finish."));
    } finally {
      if (id === diffRun.current) setDiffBusy(false);
    }
  };

  /* ---------- the form ---------- */
  const update = <K extends keyof DesignForm>(key: K, value: DesignForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const pickTemplate = (kind: TemplateKind) => {
    const t = TEMPLATES.find((x) => x.kind === kind)!;
    setForm((f) => ({ ...f, kind, name: editingId ? f.name : t.label }));
  };

  const interpret = async () => {
    if (!writable || interpreting) return;
    const text = prompt.trim();
    if (!text) {
      setInterp({ tone: "warn", label: "Needs input", text: "Describe the starting shape and its dimensions first." });
      return;
    }
    setInterpreting(true);
    setInterp({ tone: "unk", label: "Reading", text: "Local rules, no AI" });
    try {
      const r = await interpretDesignPrompt(text);
      if (r.status === "ready") setForm(formFromPlan(r.plan, editingId ? form.name : r.name, form.designNote));
      else
        setForm((f) => ({
          ...f,
          ...(r.kind ? { kind: r.kind } : {}),
          ...(r.prefill.width_mm !== undefined ? { width: r.prefill.width_mm } : {}),
          ...(r.prefill.depth_mm !== undefined ? { depth: r.prefill.depth_mm } : {}),
          ...(r.prefill.height_mm !== undefined ? { height: r.prefill.height_mm } : {}),
          ...(r.prefill.thickness_mm !== undefined ? { thickness: r.prefill.thickness_mm } : {}),
          ...(r.prefill.wall_thickness_mm !== undefined ? { wallThickness: r.prefill.wall_thickness_mm } : {}),
          ...(r.prefill.draft_angle_deg !== undefined ? { draftAngle: r.prefill.draft_angle_deg } : {}),
        }));
      setInterp(interpretView(r));
    } catch (e) {
      setInterp(INTERPRET_IDLE);
      setErr(errorText(e, "The description couldn’t be read."));
    } finally {
      setInterpreting(false);
    }
  };

  const newDesign = () => {
    setEditingId(null);
    setForm({ ...DEFAULT_DESIGN_FORM });
    setAsking(false);
    setErr(null);
    window.setTimeout(() => nameRef.current?.focus(), 0);
  };
  const startRevision = (d: Design) => {
    if (!writable) return;
    setEditingId(d.id);
    setSelectedId(d.id);
    setForm(formFromDesign(d));
    setAsking(false);
    setErr(null);
  };
  const cancelRevision = () => {
    setEditingId(null);
    setForm({ ...DEFAULT_DESIGN_FORM });
    setErr(null);
  };

  const generate = async () => {
    if (!writable || submitLock.current) return;
    const problem = fieldProblem(form) ?? validateDesignForm(form);
    if (problem) {
      setErr(problem);
      return;
    }
    submitLock.current = true;
    setSubmitting(true);
    setErr(null);
    try {
      const planBody = buildDesignPlan(form);
      const note = form.designNote.trim() || null;
      const d = editingId
        ? await createDesignRevision(editingId, { plan: planBody, design_note: note })
        : await createDesign({ name: form.name.trim(), plan: planBody, design_note: note });
      setDesigns((cur) => [d, ...(cur ?? []).filter((x) => x.id !== d.id)]);
      setSelectedId(d.id);
      setView(d.current_revision);
      setEditingId(null);
      setForm({ ...DEFAULT_DESIGN_FORM });
      setPrompt("");
      setInterp(INTERPRET_IDLE);
      toast(`Generating revision ${d.current_revision}. You can leave this page.`);
    } catch (e) {
      if (e instanceof DesignApiError && e.design) {
        const failed = e.design;
        setDesigns((cur) => [failed, ...(cur ?? []).filter((x) => x.id !== failed.id)]);
        setSelectedId(failed.id);
        setView(failed.current_revision);
        setEditingId(failed.id);
        setForm(formFromDesign(failed));
      }
      setErr(errorText(e, "Generation didn’t start."));
    } finally {
      submitLock.current = false;
      setSubmitting(false);
    }
  };

  /* ---------- archive (in-sheet confirm) ---------- */
  React.useEffect(() => {
    if (asking) keepBtn.current?.focus();
  }, [asking]);
  const closeAsk = () => {
    setAsking(false);
    window.setTimeout(() => archiveBtn.current?.focus(), 0);
  };
  const archive = async () => {
    if (!selected || archiving) return;
    setArchiving(true);
    try {
      await archiveDesign(selected.id);
      setDesigns((cur) => (cur ?? []).filter((d) => d.id !== selected.id));
      setSelectedId(null);
      if (editingId === selected.id) cancelRevision();
      setAsking(false);
      toast("Archived. Audit evidence kept.");
    } catch (e) {
      setAsking(false);
      setErr(errorText(e, "The design wasn’t archived."));
    } finally {
      setArchiving(false);
    }
  };

  /* ---------- palette ---------- */
  useRegisterPaletteItems(
    "make-studio",
    selected && viewed?.status === "ready" && canMutate
      ? [{ id: "studio-check", group: "This design", label: `Verify revision ${viewNo} of ${selected.name}`, href: checkHref(R.check, selected.id, viewNo), words: "design studio check verify revision" }]
      : [],
  );

  /* ---------- render ---------- */
  const count = designs?.length ?? 0;
  const chip = selected ? designChip(selected.status) : null;
  const viewLayers = previewLayers(selected?.id ?? null, viewed);
  const viewedBusy = viewed && (viewed.status === "generating" || viewed.status === "queued");
  const viewedFailed = viewed?.status === "failed";

  let overlay: React.ReactNode = null;
  if (!selected)
    overlay = designs ? (
      <span className="gen plain">
        <b>No design yet</b>
        <span>{writable ? "Describe a part or pick a template, then generate it." : "Designs your team generates show here."}</span>
      </span>
    ) : (
      <span className="gen plain" aria-hidden="true">
        <span className="spin" />
      </span>
    );
  else if (viewedBusy)
    overlay = (
      <span className="gen wait">
        <b>Generating real CAD</b>
        <span>Revision {viewNo} · you can leave this page</span>
      </span>
    );
  else if (viewedFailed)
    overlay = (
      <span className="gen bad">
        <b>This revision wasn’t generated</b>
        <span>{viewed?.error?.message ?? "Generation failed without an artifact."}</span>
      </span>
    );
  else if (previewState === "failed")
    overlay = (
      <span className="gen bad">
        <b>The preview didn’t load</b>
        <span>The revision and its STEP file are unaffected.</span>
      </span>
    );

  const editingDesign = editingId ? designs?.find((d) => d.id === editingId) ?? null : null;
  const formTitle = editingDesign ? `Revision ${editingDesign.current_revision + 1}` : "New design";
  const formSub = editingDesign ? `From R${editingDesign.current_revision} · name locked` : "Starts revision 1";
  const fields = fieldsFor(form.kind);
  const draft = draftField(form.kind);
  const sameRev = sameRevisionPair(from, to);
  const objLabel = selected
    ? `Revision ${viewNo} of ${selected.name}. Drag, or use the arrow keys, to turn it.`
    : "No design to show yet.";

  return (
    <MakeWorld label="Design Studio">
      <MakeHead
        title="Design Studio"
        meta={[
          "Templates: plate, L bracket, open enclosure",
          "Millimeters",
          designs ? (
            <>
              <b>{count}</b> {count === 1 ? "design" : "designs"}
            </>
          ) : (
            "Designs loading"
          ),
          "Generating doesn’t use a check",
        ]}
        tools={
          <button
            className="btn sm"
            type="button"
            disabled={refreshing}
            onClick={() => {
              void refresh();
              setHistoryKey((k) => k + 1);
            }}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      {writable ? (
        <div className="ask2">
          <div className="row">
            <label className="sr" htmlFor="mk-describe">
              Describe a starting shape
            </label>
            <input
              id="mk-describe"
              type="text"
              maxLength={500}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void interpret();
                }
              }}
              placeholder="Plate, L bracket, or open enclosure with mm dimensions"
            />
            <button className="btn ink sm" type="button" onClick={() => void interpret()} aria-disabled={interpreting}>
              {interpreting ? "Reading…" : "Interpret"}
            </button>
          </div>
          <div className="matched" aria-live="polite">
            <Chip tone={interp.tone}>{interp.label}</Chip>
            <span>{interp.text}</span>
          </div>
        </div>
      ) : null}

      <div className="sbody" style={writable ? undefined : { top: 132 }}>
        <div className="sview">
          <Turntable
            key={`${selId ?? "none"}:${previewTry}`}
            className="sobj"
            label={objLabel}
            layers={viewedBusy || viewedFailed ? [] : viewLayers}
            overlay={overlay}
            onState={setPreviewState}
          />
          {selected && viewedFailed && writable ? (
            <button className="btn sm ink" type="button" style={{ alignSelf: "center" }} onClick={() => startRevision(selected)}>
              Revise and retry
            </button>
          ) : null}
          {selected && previewState === "failed" && !viewedFailed && !viewedBusy ? (
            <button className="btn sm" type="button" style={{ alignSelf: "center" }} onClick={() => setPreviewTry((n) => n + 1)}>
              Retry preview
            </button>
          ) : null}
          <div className="stats num">
            <span>
              Envelope<b>{envelopeText(geometry?.bbox_mm)}</b>
            </span>
            <span>
              Volume<b>{geometry ? `${volumeText(geometry.volume_cm3)} cm³` : "—"}</b>
            </span>
            <span>
              STEP<b>{formatBytes(viewed?.step_size_bytes)}</b>
            </span>
            <span>
              Evidence hash<b title={viewed?.geometry_hash ?? undefined}>{viewed?.geometry_hash ? viewed.geometry_hash.slice(0, 12) : "—"}</b>
            </span>
          </div>
        </div>

        <section className="panel yd" aria-labelledby="mk-yd">
          <div className="ph">
            <h2 id="mk-yd">Your designs</h2>
            <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="num">{designs ? count : "—"}</span>
              {writable ? (
                <button className="btn sm" type="button" onClick={newDesign}>
                  New design
                </button>
              ) : null}
            </span>
          </div>
          {listErr ? (
            <div className="errx" role="alert">
              <b>Designs didn’t load</b>
              <span>{listErr}</span>
              <span>
                <button className="btn sm" type="button" onClick={() => void refresh()}>
                  Try again
                </button>
              </span>
            </div>
          ) : null}
          {!designs ? (
            <Loading rows={2} label="Loading designs" />
          ) : designs.length === 0 ? (
            listErr ? null : (
              <Empty title="No designs yet">{writable ? "The form on the right starts one. Each generate makes a new, immutable revision." : "No designs in this organization yet."}</Empty>
            )
          ) : (
            <div className="list" role="list" aria-label="Your designs" style={{ padding: "0 8px 8px" }}>
              {designs.map((d) => {
                const c = designChip(d.status);
                return (
                  <div role="listitem" key={d.id}>
                    <Row
                      onClick={() => {
                        setSelectedId(d.id);
                        setAsking(false);
                      }}
                      on={selected?.id === d.id}
                      thumb={
                        <span className="th">
                          <KindGlyph kind={d.revision?.plan.kind} />
                        </span>
                      }
                      title={d.name}
                      sub={`${kindLabel(d.revision?.plan.kind)} · revision ${d.current_revision}`}
                      chip={<Chip tone={c.tone}>{c.label}</Chip>}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="panel revp" aria-labelledby="mk-revs">
          <div className="ph">
            <h2 id="mk-revs">Revisions</h2>
            <span>{selected ? viewText(viewNo, selected.current_revision) : ""}</span>
          </div>
          {!selected ? (
            <Empty title="No revisions yet">Each Generate makes a new revision. Older ones stay downloadable and verifiable.</Empty>
          ) : (
            <>
              <div className="chips" role="group" aria-label="Revision">
                {revs.map((r) => (
                  <button key={r.id} type="button" className={cx("rc", r.number === viewNo && "on")} aria-pressed={r.number === viewNo} onClick={() => setView(r.number)}>
                    <b>R{r.number}</b>
                    {revisionSub(r, selected.current_revision)}
                  </button>
                ))}
              </div>
              <p className="fine" style={{ margin: "0 16px 6px", fontSize: 12 }}>
                Older revisions stay downloadable and verifiable.
              </p>
              {history.state === "error" ? (
                <div className="errx" role="alert">
                  <b>Revision history didn’t load</b>
                  <span>{history.err}</span>
                  <span>
                    <button className="btn sm" type="button" onClick={() => setHistoryKey((k) => k + 1)}>
                      Try again
                    </button>
                  </span>
                </div>
              ) : null}

              <div className="gh" style={{ padding: "8px 16px 2px" }}>
                <span>Compare</span>
                <span>Plan and generated summary only</span>
              </div>
              {readyRevs.length < 2 ? (
                <p className="fine" style={{ margin: "2px 16px 8px" }}>
                  Compare needs two ready revisions. Revise this design to make another.
                </p>
              ) : (
                <>
                  <div className="cmp">
                    <label className="field">
                      From
                      <select aria-label="Compare from revision" value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value))}>
                        {readyRevs.map((r) => (
                          <option key={r.id} value={r.number}>
                            R{r.number}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      To
                      <select aria-label="Compare to revision" value={to ?? ""} onChange={(e) => setTo(Number(e.target.value))}>
                        {readyRevs.map((r) => (
                          <option key={r.id} value={r.number}>
                            R{r.number}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button className="btn sm" type="button" aria-disabled={sameRev || diffBusy} onClick={() => void runCompare()}>
                      {diffBusy ? "Comparing…" : "Compare"}
                    </button>
                    {diff ? <span className={cx("hash", diff.same_geometry && "same")}>{diff.same_geometry ? "Same geometry hash" : "Geometry hash changed"}</span> : null}
                  </div>
                  {sameRev ? (
                    <p className="fine" style={{ margin: "0 16px 8px" }}>
                      Pick two different revisions.
                    </p>
                  ) : null}
                  {diffErr ? (
                    <p className="err" role="alert" style={{ margin: "0 16px 8px" }}>
                      {diffErr}
                    </p>
                  ) : null}
                  {diff ? <DiffView diff={diff} designId={selected.id} /> : null}
                </>
              )}

              <div className="gh" style={{ padding: "8px 16px 2px" }}>
                <span>Files</span>
                <span>R{viewNo}</span>
              </div>
              {viewed?.status === "ready" ? (
                <div style={{ display: "flex", gap: 8, padding: "4px 16px 14px", flexWrap: "wrap" }}>
                  <a className="btn sm" href={designRevisionStepUrl(selected.id, viewNo)} download>
                    Download R{viewNo} STEP
                  </a>
                  {canMutate ? (
                    <Link className="btn sm ink" href={checkHref(R.check, selected.id, viewNo)}>
                      Verify revision {viewNo}
                    </Link>
                  ) : null}
                </div>
              ) : (
                <p className="fine" style={{ margin: "2px 16px 14px" }}>
                  {viewedFailed ? "This revision has no files." : "Files appear when this revision is ready."}
                </p>
              )}
            </>
          )}
        </section>
      </div>

      <aside className="sheet" aria-label="The design">
        <div className="top">
          {selected ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                <div style={{ minWidth: 0 }}>
                  <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
                    {selected.name}
                  </h2>
                  <p className="smeta">
                    {kindLabel(selected.revision?.plan.kind)} · revision {selected.current_revision} is current · {chip?.label}
                  </p>
                </div>
                {canMutate ? (
                  <span style={{ display: "flex", gap: 6, flex: "none" }}>
                    {writable ? (
                      <button className="btn sm" type="button" onClick={() => startRevision(selected)} disabled={selected.status === "generating"}>
                        Revise
                      </button>
                    ) : null}
                    <button ref={archiveBtn} className="btn sm" type="button" aria-label="Archive design" onClick={() => setAsking(true)} disabled={selected.status === "generating"}>
                      Archive
                    </button>
                  </span>
                ) : null}
              </div>
              <div className="figs" aria-live="polite">
                <div className="fig">
                  <span>Volume</span>
                  <b className="num">{geometry ? volumeText(geometry.volume_cm3) : "—"}</b>
                  <small>cm³ · R{viewNo}</small>
                </div>
                <div className="fig">
                  <span>Surface triangles</span>
                  <b className="num">{countText(geometry?.surface_elements)}</b>
                </div>
                <div className="fig">
                  <span>Solids</span>
                  <b className="num">{countText(geometry?.solid_count)}</b>
                </div>
              </div>
            </>
          ) : (
            <>
              <h2 className="stitle">{writable ? "New design" : "No design selected"}</h2>
              <p className="smeta">{!designs ? "Loading your designs" : writable ? "Starts revision 1 · millimeters" : "Pick one from Your designs"}</p>
            </>
          )}
        </div>
        <div className="scroll">
          {asking && selected ? (
            <div
              className="confirm"
              role="alertdialog"
              aria-label="Archive design"
              aria-describedby="mk-arch-d"
              onKeyDown={(e) => {
                if (e.key === "Escape" && !archiving) {
                  e.preventDefault();
                  closeAsk();
                }
              }}
            >
              <b>Archive “{selected.name}”?</b>
              <span id="mk-arch-d">It leaves Your designs. Its audit evidence is kept.</span>
              <span className="row-btns">
                <button className="btn danger sm" type="button" onClick={() => void archive()} disabled={archiving}>
                  {archiving ? "Archiving…" : "Archive"}
                </button>
                <button ref={keepBtn} className="btn sm" type="button" onClick={closeAsk} disabled={archiving}>
                  Keep it
                </button>
              </span>
            </div>
          ) : null}
          {err ? (
            <div className="errb" role="alert">
              <span>{err}</span>
              <button className="btn sm" type="button" onClick={() => setErr(null)}>
                Dismiss
              </button>
            </div>
          ) : null}

          {writable ? (
            <>
              {selected || editingId ? (
                <div className="gh">
                  <span>{formTitle}</span>
                  <span>{formSub}</span>
                </div>
              ) : null}
              <div style={{ padding: "2px 12px 8px" }}>
                <span className="seg" role="group" aria-label="Template">
                  {TEMPLATES.map((t) => (
                    <button key={t.kind} type="button" className={cx(t.kind === form.kind && "on")} aria-pressed={t.kind === form.kind} title={t.desc} onClick={() => pickTemplate(t.kind)}>
                      {t.label}
                    </button>
                  ))}
                </span>
              </div>
              <div className="frm">
                <label className="field full">
                  Design name
                  <input ref={nameRef} type="text" maxLength={120} value={form.name} disabled={!!editingId} onChange={(e) => update("name", e.target.value)} />
                </label>
                {fields.map((f) => (
                  <label className="field" key={f.key}>
                    {f.label}
                    <input
                      type="number"
                      inputMode="decimal"
                      value={Number.isFinite(form[f.key]) ? form[f.key] : ""}
                      min={f.min}
                      max={f.max}
                      step={f.step}
                      onChange={(e) => update(f.key, e.target.value === "" ? Number.NaN : Number(e.target.value))}
                    />
                    <span className="lim">{f.lim}</span>
                  </label>
                ))}
                {draft ? (
                  <div className="full drow">
                    <label className="field">
                      {draft.label}
                      <input
                        type="number"
                        inputMode="decimal"
                        value={Number.isFinite(form.draftAngle) ? form.draftAngle : ""}
                        min={draft.min}
                        max={draft.max}
                        step={draft.step}
                        aria-describedby="mk-draft-note"
                        onChange={(e) => update("draftAngle", e.target.value === "" ? Number.NaN : Number(e.target.value))}
                      />
                      <span className="lim">{draft.lim}</span>
                    </label>
                    <span className="lim" id="mk-draft-note">
                      {draft.note}
                    </span>
                  </div>
                ) : null}
                {form.kind === "plate" ? (
                  <>
                    <label className="chk full">
                      <input type="checkbox" checked={form.fourCornerHoles} onChange={(e) => update("fourCornerHoles", e.target.checked)} />
                      Four corner holes
                    </label>
                    {form.fourCornerHoles ? (
                      <>
                        <label className="field">
                          Hole diameter, mm
                          <input
                            type="number"
                            inputMode="decimal"
                            value={Number.isFinite(form.holeDiameter) ? form.holeDiameter : ""}
                            min={1}
                            max={100}
                            step={0.5}
                            onChange={(e) => update("holeDiameter", e.target.value === "" ? Number.NaN : Number(e.target.value))}
                          />
                          <span className="lim">1 to 100</span>
                        </label>
                        <label className="field">
                          Edge inset, mm
                          <input
                            type="number"
                            inputMode="decimal"
                            value={Number.isFinite(form.holeInset) ? form.holeInset : ""}
                            min={2}
                            max={500}
                            step={0.5}
                            onChange={(e) => update("holeInset", e.target.value === "" ? Number.NaN : Number(e.target.value))}
                          />
                          <span className="lim">2 to 500</span>
                        </label>
                      </>
                    ) : null}
                  </>
                ) : null}
                <label className="field full">
                  <span>
                    Design note <span className="lim">Optional · no effect on geometry</span>
                  </span>
                  <textarea maxLength={1000} placeholder="For your team" value={form.designNote} onChange={(e) => update("designNote", e.target.value)} />
                </label>
              </div>
              <div style={{ display: "flex", gap: 8, padding: "6px 12px 10px", flexWrap: "wrap" }}>
                <button className="btn ink" type="button" onClick={() => void generate()} aria-disabled={submitting}>
                  {submitting ? "Generating…" : editingId ? "Generate new revision" : "Generate design"}
                </button>
                {editingId ? (
                  <button className="btn" type="button" onClick={cancelRevision} disabled={submitting}>
                    Cancel
                  </button>
                ) : null}
              </div>
              <p className="fine">Validated operations in an isolated CAD process. No generated code, no third-party model.</p>
            </>
          ) : (
            <div className="note">
              <b>Read only for your role</b>
              <span>Analysts and admins create, revise and archive designs. You can view every revision, compare them and download STEP files.</span>
            </div>
          )}
        </div>
      </aside>
      {toastNode}
    </MakeWorld>
  );
}

function DiffView({ diff, designId }: { diff: DesignRevisionComparison; designId: string }) {
  const plan = diffRows(diff.plan_changes);
  const geo = diffRows(diff.geometry_changes);
  const sides = [diff.before, diff.after];
  return (
    <div style={{ padding: "0 0 8px" }}>
      <div className="pair">
        {sides.map((side, i) => (
          <figure key={side.number}>
            <figcaption>
              <b>
                {i === 0 ? "From" : "To"} R{side.number}
              </b>
              <span className="mono" title={side.geometry_hash ?? undefined}>
                {side.geometry_hash?.slice(0, 12) ?? "no hash"}
              </span>
            </figcaption>
            <Turntable label={`Revision ${side.number}. Drag, or use the arrow keys, to turn it.`} layers={previewLayers(designId, side)} hint={null} />
          </figure>
        ))}
      </div>
      <div style={{ padding: "0 12px" }}>
        <DiffTable title="Plan change" rows={plan} from={diff.before.number} to={diff.after.number} />
        <DiffTable title="Generated geometry" rows={geo} from={diff.before.number} to={diff.after.number} />
        <p className="fine" style={{ margin: "6px 4px 0", fontSize: 12 }}>
          {diff.limits}
        </p>
      </div>
    </div>
  );
}

function DiffTable({ title, rows, from, to }: { title: string; rows: ReturnType<typeof diffRows>; from: number; to: number }) {
  return (
    <table className="dt" style={{ marginTop: 8 }}>
      <thead>
        <tr>
          <th scope="col">{title}</th>
          <th scope="col">R{from}</th>
          <th scope="col">R{to}</th>
          <th scope="col" className="r">
            Change
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={4} style={{ color: "var(--ink3)" }}>
              No saved values changed.
            </td>
          </tr>
        ) : (
          rows.map((r) => (
            <tr key={r.path}>
              <td className="m">{r.path}</td>
              <td className="num">{r.before}</td>
              <td className="num">{r.after}</td>
              <td className="r num">{r.change}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
