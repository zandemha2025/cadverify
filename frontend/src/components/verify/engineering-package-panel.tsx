"use client";

import { useEffect, useId, useState, type ReactNode, type FormEvent } from "react";
import type { CostReport } from "@/lib/api";
import { C, MONO } from "@/lib/verify/tokens";
import { getSelectedPackage, setSelectedPart } from "@/lib/verify/part-selection";
import {
  emptyPackage, evidenceKinds, packageRequest, packageExportUrl, packageSourceUrl, saveEngineeringPackage,
  type EngineeringPackage, type EngineeringPackageSummary, type PackageDocument, type PackageScope,
  type PackageSource, type PackageRequirement, type PackageEvidence, type PackageAction, type PackageOutcome,
  type PackageWrite, type EvidenceKind, type PackageBlocker,
} from "@/lib/verify/engineering-package";

const labelStyle = {display: "flex", flexDirection: "column" as const, gap: 5, fontSize: 12, color: C.ink55};
const inputStyle = {border: `1px solid ${C.hair}`, borderRadius: 6, padding: "8px 10px", fontSize: 13, color: C.ink, background: "white", minWidth: 0};
const buttonStyle = {...inputStyle, cursor: "pointer", fontWeight: 500};
const gridStyle = {display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))", gap: 12};
const cardStyle = {border: `1px solid ${C.hair}`, borderRadius: 8, padding: 14, marginTop: 10};
const words = (s: string) => s.replaceAll("_", " ");
const string = (data: FormData, key: string) => String(data.get(key) ?? "").trim();
const optionalNumber = (data: FormData, key: string) => string(data, key) === "" ? null : Number(string(data, key));
const selection = (data: FormData, key: string) => data.getAll(key).map(String);
const scopeKeys = ["process", "material", "machine", "setup", "inspection_method"] as const;
const scopeLabels = {process: "Process", material: "Exact material", machine: "Machine", setup: "Setup / fixture", inspection_method: "Inspection method"};

function Field({name, label, value, required = false, type = "text"}: {name: string; label: string; value?: string | number | null; required?: boolean; type?: string}) {
  return <label style={labelStyle}>{label}<input style={inputStyle} name={name} defaultValue={value ?? ""} required={required} type={type} step={type === "number" ? "any" : undefined} maxLength={2000}/></label>;
}
function Select({name, label, value, options, multiple = false}: {name: string; label: string; value?: string | string[]; options: {id: string; label: string}[]; multiple?: boolean}) {
  const id = useId();
  return <div style={labelStyle}><label htmlFor={id}>{label}</label><select id={id} style={inputStyle} name={name} defaultValue={value} multiple={multiple} required>
    {!multiple && <option value="">Select…</option>}{options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
  </select>{multiple && <small>Use Ctrl or Command to select more than one.</small>}</div>;
}
function Choices({name, label, value, options}: {name: string; label: string; value: string[]; options: {id: string; label: string}[]}) {
  return <fieldset style={{border: `1px solid ${C.hair}`, borderRadius: 6, maxHeight: 180, overflowY: "auto", fontSize: 12}}>
    <legend>{label}</legend>{options.length === 0 && <p>No entries yet.</p>}
    {options.map(o => <label key={o.id} style={{display: "block", padding: "4px 0"}}><input type="checkbox" name={name} value={o.id} defaultChecked={value.includes(o.id)}/> {o.label}</label>)}
  </fieldset>;
}
function ScopeFields({scope}: {scope: PackageScope}) {
  return <>{scopeKeys.map(key => <Field key={key} name={key} label={scopeLabels[key]} value={scope[key]}/>)}</>;
}
function readScope(data: FormData): PackageScope {
  return Object.fromEntries(scopeKeys.map(k => [k, string(data, k)])) as unknown as PackageScope;
}
function Section({title, children, open = false}: {title: string; children: ReactNode; open?: boolean}) {
  return <details open={open} style={{borderTop: `1px solid ${C.hair}`, padding: "16px 0"}}><summary style={{cursor: "pointer", fontWeight: 550, fontSize: 15}}>{title}</summary><div style={{paddingTop: 14}}>{children}</div></details>;
}
function ReviewButton({reviewed, onClick, disabled}: {reviewed: boolean; onClick: () => void; disabled: boolean}) {
  return <button type="button" style={buttonStyle} disabled={disabled} onClick={onClick}>{reviewed ? "Review again" : "Confirm reviewed"}</button>;
}

export function EngineeringPackageQueue({nav}: {nav: (screen: string) => void}) {
  const [groups, setGroups] = useState<{kind:string; owner:string; actions:number; packages:number}[] | null>(null);
  const [rows, setRows] = useState<EngineeringPackageSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [truncated, setTruncated] = useState(false);
  async function loadGroups() {
    setBusy(true); setError("");
    try {const result = await packageRequest<{groups: NonNullable<typeof groups>; truncated:boolean}>("/queue"); setGroups(result.groups); setTruncated(result.truncated);}
    catch(e) {setError(e instanceof Error ? e.message : "Unable to load evidence actions");}
    finally {setBusy(false);}
  }
  async function loadRows(query: string, append = false) {
    setBusy(true); setError("");
    try {const page = await packageRequest<{packages: EngineeringPackageSummary[]; next_cursor:string|null}>(`?${query}`); setRows(old => append ? [...old, ...page.packages] : page.packages); setCursor(page.next_cursor);}
    catch(e) {setError(e instanceof Error ? e.message : "Unable to load packages");}
    finally {setBusy(false);}
  }
  return <details style={{...cardStyle, margin: "16px 0"}} onToggle={e => {if (e.currentTarget.open && groups === null && !busy) void loadGroups();}}>
    <summary style={{cursor:"pointer", fontSize:14}}>Engineering evidence queue</summary>
    <p style={{fontSize:12}}>Find the shared evidence gaps holding up saved order packages. Each part still requires its own applicability review.</p>
    {error && <p role="alert">{error}</p>}{busy && <p role="status">Loading evidence actions…</p>}
    {groups?.length === 0 && <p>No unresolved actions in saved packages.</p>}
    <div style={{display:"flex", gap:8, flexWrap:"wrap"}}>{groups?.map(group => <button key={`${group.kind}:${group.owner}`} style={buttonStyle} disabled={busy} onClick={() => {
      const query = new URLSearchParams({blocker_kind:group.kind,owner:group.owner}).toString(); setFilter(query); void loadRows(query);
    }}>{words(group.kind)} · {group.owner} · {group.packages} packages / {group.actions} actions</button>)}</div>
    {truncated && <p>Showing the 50 largest groups. Open individual part packages for additional owners.</p>}
    {rows.map(row => <div style={cardStyle} key={row.id}><button style={buttonStyle} onClick={() => {setSelectedPart(row.mesh_hash,row.id); nav("part");}}>{row.part_number} · {row.order} · rev {row.revision}</button> · {row.blocker_count} actions</div>)}
    {cursor && <button style={buttonStyle} disabled={busy} onClick={() => void loadRows(`${filter}&cursor=${cursor}`,true)}>More packages</button>}
    <button type="button" style={{...buttonStyle,marginTop:12}} disabled={busy} onClick={() => void loadGroups()}>Refresh evidence queue</button>
  </details>;
}

export function EngineeringPackagePanel({meshHash, filename, decisionId, report}: {
  meshHash: string; filename: string; decisionId: string | null; report: CostReport | null;
}) {
  const seed = () => {
    const estimate = report?.estimates.find(e => e.process === report.decision?.make_now_process) ?? report?.estimates[0];
    const process = estimate?.process ?? "";
    return emptyPackage(filename, {process, material: estimate?.material ?? "", machine: report?.verification?.per_route?.[process]?.best_machine ?? "", setup: "", inspection_method: ""}, estimate?.quantity ?? 1);
  };
  const [doc, setDoc] = useState<PackageDocument>(seed);
  const [packet, setPacket] = useState<EngineeringPackage | null>(null);
  const [list, setList] = useState<EngineeringPackageSummary[]>([]);
  const [listCursor, setListCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<EngineeringPackageSummary[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sourceEdit, setSourceEdit] = useState<PackageSource | null>(null);
  const [reqEdit, setReqEdit] = useState<PackageRequirement | null>(null);
  const [evidenceEdit, setEvidenceEdit] = useState<PackageEvidence | null>(null);
  const [actionEdit, setActionEdit] = useState<PackageAction | null>(null);
  const [outcomeEdit, setOutcomeEdit] = useState<PackageOutcome | null>(null);
  const [note, setNote] = useState("");
  const [useLatestEvaluation, setUseLatestEvaluation] = useState(false);
  const [formEpoch, setFormEpoch] = useState(0);
  const [reuseList, setReuseList] = useState<EngineeringPackageSummary[]>([]);
  const [reuseCursor, setReuseCursor] = useState<string | null>(null);
  const [reusePacket, setReusePacket] = useState<EngineeringPackage | null>(null);
  const readonly = busy || Boolean(packet && !packet.is_latest);
  const assessment = packet?.current_assessment ?? packet?.evaluation;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    packageRequest<{packages: EngineeringPackageSummary[]; next_cursor: string | null}>(`?mesh_hash=${encodeURIComponent(meshHash)}`).then(async page => {
      if (cancelled) return;
      setList(page.packages); setListCursor(page.next_cursor);
      const selectedId = getSelectedPackage() ?? page.packages[0]?.id;
      setSelectedPart(meshHash);
      if (selectedId) {
        const current = await packageRequest<EngineeringPackage>(`/${selectedId}`);
        if (current.mesh_hash !== meshHash) throw new Error("The selected package belongs to a different part. Select its part to continue.");
        if (!cancelled) { setPacket(current); setDoc(current.document); }
      }
    }).catch(e => {if (!cancelled) setError(e.message);}).finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, [meshHash]);

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (e) {setError(e instanceof Error ? e.message : "Unable to save. Your edits are still available.");}
    finally {setBusy(false);}
  }
  function update<K extends keyof PackageDocument>(key: K, value: PackageDocument[K]) {
    setDoc(current => ({...current, [key]: value})); setDirty(true); setMessage("");
  }
  function upsert<K extends "sources" | "requirements" | "evidence" | "actions" | "outcomes">(key: K, value: PackageDocument[K][number]) {
    const editingId = {sources:sourceEdit,requirements:reqEdit,evidence:evidenceEdit,actions:actionEdit,outcomes:outcomeEdit}[key]?.id;
    if (doc[key].some(row => row.id === value.id) && editingId !== value.id) {setError("That identifier already exists. Use a unique identifier or edit the existing entry."); return;}
    setDoc(current => ({...current, [key]: [...current[key].filter(row => row.id !== value.id), value]}));
    setDirty(true); setFormEpoch(n => n + 1); setMessage("Added to the draft. Save to assess evidence and preserve this version.");
  }
  function remove(key: "sources" | "requirements" | "evidence" | "actions" | "outcomes", id: string) {
    const references = key === "sources" ? [...doc.requirements,...doc.evidence,...doc.outcomes].some(r => r.source_id === id)
      : key === "requirements" ? [...doc.evidence,...doc.actions,...doc.outcomes].some(r => r.requirement_ids.includes(id))
      : key === "evidence" ? doc.actions.some(r => r.closure_evidence_ids.includes(id)) || doc.evidence.some(r => r.supersedes_evidence_ids?.includes(id)) || doc.authorization?.evidence_id === id
      : key === "outcomes" ? doc.evidence.some(r => r.outcome_ids.includes(id)) : false;
    if (references) {setError("This entry is referenced by another requirement, evidence record or action. Update those links before removing it."); return;}
    setDoc(current => ({...current,[key]:current[key].filter(r => r.id !== id)})); setDirty(true); setError("");
  }
  async function save(extra: Partial<PackageWrite> = {}) {
    await run(async () => {
      const chosenDecision = useLatestEvaluation ? decisionId : packet?.decision_id ?? decisionId;
      if (!chosenDecision) throw new Error("Save a geometry and manufacturing evaluation before creating its package.");
      const saved = await saveEngineeringPackage({decision_id: chosenDecision, document: doc, previous_id: packet?.id,
        state: "draft", review_note: note, ...extra});
      setPacket(saved); setDoc(saved.document); setDirty(false); setUseLatestEvaluation(false);
      setList(current => [saved, ...current.filter(row => row.series_id !== saved.series_id)]);
      setMessage(`Version ${saved.version} saved. ${saved.blocker_count} evidence action${saved.blocker_count === 1 ? "" : "s"} remain.`);
    });
  }
  async function open(id: string) {
    await run(async () => {const row = await packageRequest<EngineeringPackage>(`/${id}`); setPacket(row); setDoc(row.document); setDirty(false); resetEditors();});
  }
  function resetEditors() {setSourceEdit(null); setReqEdit(null); setEvidenceEdit(null); setActionEdit(null); setOutcomeEdit(null); setReusePacket(null); setUseLatestEvaluation(false); setNote(""); setFormEpoch(n => n + 1);}
  const sources = doc.sources.map(s => ({id: s.id, label: `${s.name} · ${s.revision || s.kind}`}));
  const requirements = doc.requirements.map(r => ({id: r.id, label: `${r.id}: ${r.characteristic}`}));
  const evidenceOptions = doc.evidence.map(e => ({id: e.id, label: `${e.id}: ${e.kind} · ${e.conclusion}`}));
  const wasReviewed = (kind: string, id: string) => !dirty && Boolean(packet?.reviews[`${kind}:${id}`]);
  const submit = (callback: (data: FormData) => void) => (event: FormEvent<HTMLFormElement>) => {event.preventDefault(); callback(new FormData(event.currentTarget));};
  function assign(blocker: PackageBlocker) {
    setActionEdit(doc.actions.find(a => a.id === blocker.action_id) ?? {id: `action-${doc.actions.length + 1}`, blocker_id: blocker.id,
      title: blocker.consequence.slice(0, 200), owner: "", required_evidence: blocker.required_evidence,
      requirement_ids: blocker.requirement_ids, closure_evidence_ids: [], rationale: ""});
    document.getElementById(`actions-${meshHash}`)?.scrollIntoView({behavior: "smooth", block: "center"});
  }

  return <section aria-label="Engineering package" style={{gridColumn: "1 / -1", border: `1px solid ${C.hair}`, borderRadius: 14, padding: 24, background: "white"}}>
    <h2 style={{fontSize: 22, fontWeight: 500, margin: "0 0 8px"}}>Engineering package</h2>
    <p style={{fontSize: 13, color: C.ink55, lineHeight: 1.6}}>Bring the drawing, specifications and manufacturing evidence together for this order. Each saved version preserves the sources, reviews and remaining actions.</p>
    {loading && <p role="status">Loading saved packages…</p>}
    {error && <p role="alert" style={{color: C.fail, overflowWrap: "anywhere"}}>{error}</p>}
    {message && <p role="status" style={{color: C.measured}}>{message}</p>}
    {!decisionId && !packet && <p>Verify this part and save its evaluation to begin.</p>}
    <div style={{display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end", marginBottom: 16}}>
      {list.length > 0 && <label style={labelStyle}>Order / package<select style={inputStyle} value={packet?.id ?? ""} disabled={busy || dirty} onChange={e => void open(e.target.value)}>
        <option value="">New package</option>{list.map(p => <option key={p.id} value={p.id}>{p.part_number} · {p.order} · rev {p.revision} · v{p.version}</option>)}
        {packet && !list.some(p => p.id === packet.id) && <option value={packet.id}>Historical v{packet.version} · {packet.order}</option>}
      </select></label>}
      {listCursor && <button type="button" style={buttonStyle} disabled={busy} onClick={() => void run(async () => {
        const page = await packageRequest<{packages: EngineeringPackageSummary[]; next_cursor: string | null}>(`?mesh_hash=${meshHash}&cursor=${listCursor}`); setList(current => [...current, ...page.packages]); setListCursor(page.next_cursor);
      })}>More packages</button>}
      <button type="button" style={buttonStyle} disabled={busy || dirty || loading} onClick={() => {setPacket(null); setDoc(seed()); resetEditors(); setHistory([]); setDirty(false); setMessage("");}}>New order package</button>
      {packet && <button type="button" style={buttonStyle} disabled={busy || dirty} onClick={() => void open(packet.id)}>Refresh current assessment</button>}
      {packet && <button type="button" style={buttonStyle} disabled={busy} onClick={() => void run(async () => {
        const page = await packageRequest<{packages: EngineeringPackageSummary[]; next_cursor: string | null}>(`?series_id=${packet.series_id}`); setHistory(page.packages); setHistoryCursor(page.next_cursor);
      })}>Version history</button>}
    </div>
    {history.length > 0 && <div style={{...cardStyle, marginBottom: 16}}>{history.map(p => <button style={{...buttonStyle, margin: 3}} type="button" key={p.id} disabled={busy || dirty} onClick={() => void open(p.id)}>v{p.version} · {p.revision} · {p.state}</button>)}
      {historyCursor && packet && <button style={buttonStyle} type="button" disabled={busy} onClick={() => void run(async () => {
        const page = await packageRequest<{packages: EngineeringPackageSummary[]; next_cursor: string | null}>(`?series_id=${packet.series_id}&cursor=${historyCursor}`); setHistory(current => [...current, ...page.packages]); setHistoryCursor(page.next_cursor);
      })}>Older versions</button>}
    </div>}
    {packet && !packet.is_latest && <p>Historical snapshot. Open the latest version to continue this order.</p>}
    {packet && <div style={{...gridStyle, padding: 16, background: "#f6f8fa", borderRadius: 8}}>
      {[['Screening', assessment!.screening], ['Qualification evidence', assessment!.qualification], ['External authorization', assessment!.authorization]].map(([label, value]) => <div key={label}><small>{label}</small><p style={{margin: "5px 0", fontWeight: 550}}>{words(value)}</p></div>)}
      <p style={{gridColumn: "1 / -1", margin: 0, fontSize: 12}}>{packet.evaluation.boundary} Assessment saved {packet.evaluated_on}.{dirty && " Unsaved edits have not been assessed."}</p>
      {packet.current_assessment && <p style={{gridColumn:"1 / -1",margin:0,fontSize:12}}>Current applicability checked {packet.current_assessment.assessed_on}. {packet.current_assessment.stale_reason} The downloaded packet preserves its original assessment.</p>}
    </div>}
    <fieldset disabled={readonly || loading} style={{border: 0, padding: 0, minWidth: 0}}>
      <Section title="1. Order and manufacturing scope" open>
        <div style={gridStyle}>
          {([['part_number', 'Part number'], ['revision', 'Authorized revision'], ['order', 'Order / configuration'], ['effectivity', 'Effectivity / serial or lot range']] as const).map(([key, label]) => <label key={key} style={labelStyle}>{label}<input style={inputStyle} value={doc[key]} maxLength={key === 'effectivity' ? 2000 : 200} onChange={e => update(key, e.target.value)}/></label>)}
          <label style={labelStyle}>Order quantity<input style={inputStyle} type="number" min="1" max="10000000" value={doc.quantity} onChange={e => update("quantity", Number(e.target.value))}/></label>
          {scopeKeys.map(key => <label key={key} style={labelStyle}>{scopeLabels[key]}<input style={inputStyle} value={doc.scope[key]} list={key === "process" ? `processes-${meshHash}` : undefined} onChange={e => update("scope", {...doc.scope, [key]: e.target.value})}/></label>)}
          <datalist id={`processes-${meshHash}`}>{[...new Set(report?.estimates.map(e => e.process) ?? [])].map(p => <option key={p} value={p}/>)}</datalist>
        </div>
        <p style={{fontSize: 12, color: C.ink55}}>Use the exact material and machine names from the evaluated route. Setup and inspection method define where evidence can be reused.</p>
        {packet && decisionId && packet.decision_id !== decisionId && <label><input type="checkbox" checked={useLatestEvaluation} onChange={e => {setUseLatestEvaluation(e.target.checked); setDirty(true);}}/> Use this part&apos;s latest saved geometry/manufacturing evaluation</label>}
      </Section>
      <Section title={`2. Source documents and authority (${doc.sources.length})`}>
        <p style={{fontSize: 12}}>Retain original files or controlled references. Confirm which source controls this order and what was checked. File upload alone does not extract or validate characteristics.</p>
        {doc.sources.map(s => <div key={s.id} style={cardStyle}><strong>{s.name}</strong> · rev {s.revision || "unspecified"} · {s.authority} · {s.coverage}
          <p style={{fontSize: 12, overflowWrap: "anywhere"}}>{s.reference || s.filename} {s.coverage_note}</p>
          <button type="button" style={buttonStyle} onClick={() => setSourceEdit(s)}>Edit source</button>{" "}
          <button type="button" style={buttonStyle} onClick={() => remove("sources",s.id)}>Remove from draft</button>{" "}
          <ReviewButton reviewed={wasReviewed("source", s.id)} disabled={busy} onClick={() => void save({confirm_sources: [s.id]})}/>{" "}
          {packet?.document.sources.some(old => old.id === s.id && old.sha256 === s.sha256) && s.sha256 && <a href={packageSourceUrl(packet.id, s.id)}>Download original</a>}
        </div>)}
        <form key={`source-${sourceEdit?.id ?? 'new'}-${formEpoch}`} onSubmit={submit(data => void run(async () => {
          const file = data.get("file") as File;
          let uploaded = sourceEdit ? {sha256: sourceEdit.sha256, filename: sourceEdit.filename} : {sha256: null as string | null, filename: ""};
          if (file?.size) {
            if (file.size > 20 * 1024 * 1024) throw new Error("Original documents are limited to 20 MiB each.");
            const upload = new FormData(); upload.append("file", file);
            const result = await packageRequest<{sha256: string; filename: string}>("/documents", {method: "POST", body: upload});
            uploaded = {sha256: result.sha256, filename: result.filename};
          }
          upsert("sources", {id: sourceEdit?.id ?? string(data, "id"), name: string(data, "name"), kind: string(data, "kind") as PackageSource["kind"],
            revision: string(data, "revision"), reference: string(data, "reference"), authority: string(data, "authority") as PackageSource["authority"],
            coverage: string(data, "coverage") as PackageSource["coverage"], coverage_note: string(data, "coverage_note"), ...uploaded}); setSourceEdit(null);
        }))} style={{...cardStyle, ...gridStyle}}>
          <Field name="id" label="Source identifier" value={sourceEdit?.id ?? `source-${doc.sources.length + 1}`} required/>
          <Field name="name" label="Document name" value={sourceEdit?.name} required/>
          <Select name="kind" label="Document type" value={sourceEdit?.kind ?? "drawing"} options={["model","drawing","specification","evidence","comparison"].map(id => ({id, label: words(id)}))}/>
          <Field name="revision" label="Document revision" value={sourceEdit?.revision}/>
          <Field name="reference" label="Controlled reference / document-system link" value={sourceEdit?.reference}/>
          <label style={labelStyle}>Original file<input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg,.csv,.json,.txt,.step,.stp,.stl,.igs,.iges"/></label>
          <Select name="authority" label="Source authority" value={sourceEdit?.authority ?? "supporting"} options={["controlling","supporting","derivative"].map(id => ({id, label: words(id)}))}/>
          <Select name="coverage" label="Characteristic coverage" value={sourceEdit?.coverage ?? "unreviewed"} options={["unreviewed","partial","complete"].map(id => ({id, label: words(id)}))}/>
          <Field name="coverage_note" label="Coverage / unsupported content" value={sourceEdit?.coverage_note}/>
          <button style={buttonStyle} type="submit">{sourceEdit ? "Update source" : "Add source"}</button>
        </form>
      </Section>
      <Section title={`3. Source-linked requirements (${doc.requirements.length})`}>
        <p style={{fontSize: 12}}>Record the original requirement and its drawing zone, PMI identifier or specification clause. Matching characteristic and feature names are checked for conflicting values.</p>
        <label style={labelStyle}>Import characteristic CSV or JSON<input type="file" accept=".csv,.json" onChange={e => {const file = e.target.files?.[0]; if (!file) return; void run(async () => {
          const form = new FormData(); form.append("file", file); const imported = await packageRequest<{requirements: PackageRequirement[]}>("/import-characteristics", {method: "POST", body: form});
          if (imported.requirements.some(r => doc.requirements.some(old => old.id === r.id))) throw new Error("Import identifiers overlap existing requirements. Edit existing rows or use unique identifiers.");
          update("requirements", [...doc.requirements, ...imported.requirements]); setMessage("Characteristics imported for review. Confirm their source references and omissions.");
        }); e.target.value = "";}}/></label>
        <p style={{fontSize: 11}}>Columns: id, characteristic, feature, kind, value, unit, lower, upper, source_id, location, required_evidence. Separate evidence types with semicolons. The exported CSV uses the same columns.</p>
        {doc.requirements.map(r => <div key={r.id} style={cardStyle}><strong>{r.id} · {r.characteristic}</strong> · {r.value} {r.unit}{(r.lower != null || r.upper != null) && ` · limits ${r.lower ?? '—'} to ${r.upper ?? '—'}`}
          <p style={{fontSize: 12}}>{r.source_id} · {r.location} · feature {r.feature || "unmapped"}</p>
          <button style={buttonStyle} type="button" onClick={() => setReqEdit(r)}>Edit requirement</button>{" "}
          <button type="button" style={buttonStyle} onClick={() => remove("requirements",r.id)}>Remove from draft</button>{" "}
          <ReviewButton reviewed={wasReviewed("requirement", r.id)} disabled={busy} onClick={() => void save({confirm_requirements: [r.id]})}/>
        </div>)}
        <form key={`requirement-${reqEdit?.id ?? 'new'}-${formEpoch}`} style={{...cardStyle, ...gridStyle}} onSubmit={submit(data => {
          upsert("requirements", {id: reqEdit?.id ?? string(data, "id"), characteristic: string(data, "characteristic"), feature: string(data, "feature"),
            kind: string(data, "kind") as PackageRequirement["kind"], value: string(data, "value"), unit: string(data, "unit"),
            lower: optionalNumber(data, "lower"), upper: optionalNumber(data, "upper"), source_id: string(data, "source_id"), location: string(data, "location"), required_evidence: selection(data, "required_evidence") as EvidenceKind[]}); setReqEdit(null);
        })}>
          <Field name="id" label="Characteristic identifier" value={reqEdit?.id ?? `requirement-${doc.requirements.length + 1}`} required/>
          <Field name="characteristic" label="Characteristic name" value={reqEdit?.characteristic} required/>
          <Field name="feature" label="Feature / datum identifier" value={reqEdit?.feature}/>
          <Select name="kind" label="Requirement type" value={reqEdit?.kind ?? "dimension"} options={["dimension","gdt","material","finish","service","interface","process","other"].map(id => ({id, label: words(id)}))}/>
          <Field name="value" label="Original value / requirement text" value={reqEdit?.value} required/>
          <Field name="unit" label="Units" value={reqEdit?.unit}/>
          <Field name="lower" label="Lower limit" value={reqEdit?.lower} type="number"/><Field name="upper" label="Upper limit" value={reqEdit?.upper} type="number"/>
          <Select name="source_id" label="Source document" value={reqEdit?.source_id} options={sources}/>
          <Field name="location" label="Sheet / zone / clause / PMI identifier" value={reqEdit?.location} required/>
          <Choices name="required_evidence" label="Required evidence" value={reqEdit?.required_evidence ?? ["manufacturing","inspection"]} options={evidenceKinds.map(id => ({id,label: words(id)}))}/>
          <button style={buttonStyle} type="submit">{reqEdit ? "Update requirement" : "Add requirement"}</button>
        </form>
      </Section>
      <Section title={`4. Evidence and applicability (${doc.evidence.length})`}>
        <p style={{fontSize: 12}}>A supporting document becomes usable only after explicit review. Its process, material, machine, setup, inspection method and requirement dependencies must match.</p>
        <button type="button" style={buttonStyle} onClick={() => void run(async () => {
          const page = await packageRequest<{packages:EngineeringPackageSummary[];next_cursor:string|null}>(""); setReuseList(page.packages); setReuseCursor(page.next_cursor);
        })}>Find prior package evidence</button>
        {reuseList.length > 0 && <div style={cardStyle}><label style={labelStyle}>Prior package<select style={inputStyle} value={reusePacket?.id ?? ""} onChange={e => {if(e.target.value) void run(async () => setReusePacket(await packageRequest<EngineeringPackage>(`/${e.target.value}`)));}}>
          <option value="">Select a prior order to inspect its evidence</option>{reuseList.map(p => <option key={p.id} value={p.id}>{p.part_number} · {p.order} · {p.revision}</option>)}</select></label>
          {reuseCursor && <button type="button" style={buttonStyle} onClick={() => void run(async () => {
            const page = await packageRequest<{packages:EngineeringPackageSummary[];next_cursor:string|null}>(`?cursor=${reuseCursor}`); setReuseList(old => [...old,...page.packages]); setReuseCursor(page.next_cursor);
          })}>More prior packages</button>}
          {reusePacket && <><p>Original requirement scope: {reusePacket.document.requirements.map(r => `${r.id}: ${r.characteristic} ${r.value} ${r.unit} [${r.lower ?? '—'}, ${r.upper ?? '—'}]`).join("; ")}</p>
            <p>Reuse imports an unreviewed candidate. Map the receiving requirements and review applicability; original observations remain tied to their built order.</p>
            {reusePacket.document.evidence.map(e => <div key={e.id} style={cardStyle}><strong>{e.id} · {e.kind} · {e.conclusion}</strong><p>{e.rationale}</p><p>{Object.values(e.scope).join(" · ")}</p>
              <button style={buttonStyle} type="button" onClick={() => {
                const ids = new Map<string,string>(); const originals = reusePacket.document.sources.filter(s => s.id === e.source_id || reusePacket.document.outcomes.some(o => e.outcome_ids.includes(o.id) && o.source_id === s.id));
                const importedSources = originals.map(s => {const id = `source-${crypto.randomUUID()}`; ids.set(s.id,id); return {...s,id,authority:"supporting" as const,coverage:"unreviewed" as const};});
                const outcomeIds = new Map<string,string>();
                const importedOutcomes = reusePacket.document.outcomes.filter(o => e.outcome_ids.includes(o.id)).map(o => {const id = `outcome-${crypto.randomUUID()}`; outcomeIds.set(o.id,id); return {...o,id,source_id:ids.get(o.source_id)!,requirement_ids:[]};});
                const candidate: PackageEvidence = {...e,id:`evidence-${crypto.randomUUID()}`,source_id:ids.get(e.source_id)!,requirement_ids:[],supersedes_evidence_ids:[],outcome_ids:e.outcome_ids.map(id => outcomeIds.get(id)!),
                  rationale:`Candidate from package ${reusePacket.id}, evidence ${e.id}. Confirm receiving requirement mapping and applicability. ${e.rationale}`.slice(0,2000)};
                setDoc(current => ({...current,sources:[...current.sources,...importedSources],outcomes:[...current.outcomes,...importedOutcomes],evidence:[...current.evidence,candidate]})); setEvidenceEdit(candidate); setDirty(true); setMessage("Prior evidence imported as an unreviewed candidate. Map requirements in the evidence form below.");
              }}>Import for applicability review</button>
            </div>)}
          </>}
        </div>}
        {doc.evidence.map(e => <div style={cardStyle} key={e.id}><strong>{e.id} · {words(e.kind)}</strong> · {e.conclusion}
          <p style={{fontSize: 12}}>{e.rationale} · {e.source_id} / {e.location}</p>
          <p style={{fontSize: 12}}>Review: {dirty ? "save to reassess" : words(assessment?.evidence_status.find(s => s.id === e.id)?.reason ?? "review required")}</p>
          <button style={buttonStyle} type="button" onClick={() => setEvidenceEdit(e)}>Edit evidence</button>{" "}<ReviewButton reviewed={wasReviewed("evidence", e.id)} disabled={busy} onClick={() => void save({review_evidence: [e.id]})}/>
          {" "}<button type="button" style={buttonStyle} onClick={() => remove("evidence",e.id)}>Remove from draft</button>
        </div>)}
        <form key={`evidence-${evidenceEdit?.id ?? 'new'}-${formEpoch}`} style={{...cardStyle, ...gridStyle}} onSubmit={submit(data => {
          upsert("evidence", {id: evidenceEdit?.id ?? string(data, "id"), kind: string(data, "kind") as EvidenceKind, source_id: string(data, "source_id"), location: string(data, "location"),
            requirement_ids: selection(data, "requirement_ids"), scope: readScope(data), conclusion: string(data, "conclusion") as PackageEvidence["conclusion"], rationale: string(data, "rationale"), expires_on: string(data, "expires_on") || null, outcome_ids: selection(data, "outcome_ids"), supersedes_evidence_ids: selection(data, "supersedes_evidence_ids")}); setEvidenceEdit(null);
        })}>
          <Field name="id" label="Evidence identifier" value={evidenceEdit?.id ?? `evidence-${doc.evidence.length + 1}`} required/>
          <Select name="kind" label="Evidence type" value={evidenceEdit?.kind ?? "manufacturing"} options={evidenceKinds.map(id => ({id,label: words(id)}))}/>
          <Select name="source_id" label="Evidence source" value={evidenceEdit?.source_id} options={sources}/>
          <Field name="location" label="Page / section / result identifier" value={evidenceEdit?.location} required/>
          <Select name="conclusion" label="What does it establish?" value={evidenceEdit?.conclusion ?? "inconclusive"} options={["supports","fails","inconclusive"].map(id => ({id,label: words(id)}))}/>
          <Field name="rationale" label="Engineering rationale / limitations" value={evidenceEdit?.rationale} required/>
          <ScopeFields scope={evidenceEdit?.scope ?? doc.scope}/>
          <Field name="expires_on" label="Review / expiry date" value={evidenceEdit?.expires_on} type="date"/>
          <Choices name="requirement_ids" label="Requirements this evidence addresses" value={evidenceEdit?.requirement_ids ?? []} options={requirements}/>
          <Choices name="outcome_ids" label="Measured outcomes supporting the evidence" value={evidenceEdit?.outcome_ids ?? []} options={doc.outcomes.map(o => ({id:o.id,label:`${o.id} · ${o.samples} samples / ${o.failures} failures`}))}/>
          <Choices name="supersedes_evidence_ids" label="Earlier evidence this reviewed disposition supersedes" value={evidenceEdit?.supersedes_evidence_ids ?? []} options={evidenceOptions.filter(e => e.id !== evidenceEdit?.id)}/>
          <button style={buttonStyle} type="submit">{evidenceEdit ? "Update evidence" : "Add evidence"}</button>
        </form>
      </Section>
      <Section title="5. Required actions and closure" open>
        {!packet && <p>Save the package to derive its evidence actions.</p>}
        {assessment?.blockers.map(b => <div style={cardStyle} key={b.id}><strong>{b.consequence}</strong><p style={{fontSize: 12}}>Owner: {b.owner} · Close with: {b.required_evidence}</p><button style={buttonStyle} type="button" onClick={() => assign(b)}>Assign / plan closure</button></div>)}
        {packet && assessment?.blockers.length === 0 && <p>Recorded evidence requirements are resolved. External manufacturing authorization remains separate.</p>}
        <div id={`actions-${meshHash}`}>
          {doc.actions.map(a => <div style={cardStyle} key={a.id}><strong>{a.title}</strong> · {a.owner} · {assessment?.action_status.find(s => s.id === a.id)?.status ?? "open"}<p>{a.required_evidence}</p><button type="button" style={buttonStyle} onClick={() => setActionEdit(a)}>Edit action</button>{" "}<button type="button" style={buttonStyle} onClick={() => void save({close_actions: [a.id]})}>Review closure evidence</button>{" "}<button type="button" style={buttonStyle} onClick={() => remove("actions",a.id)}>Remove from draft</button></div>)}
          <form key={`action-${actionEdit?.id ?? 'new'}-${formEpoch}`} style={{...cardStyle,...gridStyle}} onSubmit={submit(data => {
            upsert("actions", {id: actionEdit?.id ?? string(data,"id"), blocker_id: actionEdit?.blocker_id ?? "", title: string(data,"title"), owner: string(data,"owner"), required_evidence: string(data,"required_evidence"),
              requirement_ids: selection(data,"requirement_ids"), closure_evidence_ids: selection(data,"closure_evidence_ids"), rationale: string(data,"rationale")}); setActionEdit(null);
          })}>
            <Field name="id" label="Action identifier" value={actionEdit?.id ?? `action-${doc.actions.length + 1}`} required/>
            <Field name="title" label="Action" value={actionEdit?.title} required/><Field name="owner" label="Responsible person / team" value={actionEdit?.owner} required/>
            <Field name="required_evidence" label="Evidence required to close" value={actionEdit?.required_evidence} required/>
            <Choices name="requirement_ids" label="Affected requirements" value={actionEdit?.requirement_ids ?? []} options={requirements}/>
            <Choices name="closure_evidence_ids" label="Closure evidence" value={actionEdit?.closure_evidence_ids ?? []} options={evidenceOptions}/>
            <Field name="rationale" label="Closure rationale" value={actionEdit?.rationale}/><button style={buttonStyle} type="submit">Save action to draft</button>
          </form>
        </div>
      </Section>
      <Section title="6. Revision consequences and conditional routes">
        {packet && <><p>Changed requirements: {packet.evaluation.changes.changed_requirements.join(", ") || "none"}. Added: {packet.evaluation.changes.added_requirements.join(", ") || "none"}. Removed: {packet.evaluation.changes.removed_requirements.join(", ") || "none"}.</p>
          <p>Unchanged requirement content: {packet.evaluation.changes.unchanged_requirements.join(", ") || "none compared"}. Source mapping still requires confirmation when its document changes.</p>
          {packet.evaluation.changes.scope_changed && <p>Manufacturing scope changed. Previous evidence needs an applicability review.</p>}
          {assessment!.alternatives.map((a,i) => <div style={cardStyle} key={i}><strong>{words(a.process)} · {a.material}</strong> · {a.machine || "machine not established"}<ul>{a.conditions.map((c,j) => <li key={j}>{c}</li>)}</ul>
            <p style={{fontSize: 12}}>{a.basis} Quantity {a.quantity}{a.unit_cost_usd != null && ` · conditional unit estimate $${a.unit_cost_usd.toFixed(2)}`}.</p>
            <details><summary>Resource assumptions</summary><ul>{a.resources.map((r,j) => <li key={j}>{words(r.name)}: {r.value} {r.unit} · {r.provenance} · {r.source}</li>)}</ul></details>
          </div>)}
          {packet.evaluation.alternatives.length === 0 && <p>No evaluated route at this exact order quantity. Re-run verification at the declared quantity to obtain conditional resources.</p>}
        </>}
      </Section>
      <Section title={`7. Actual manufacturing outcomes (${doc.outcomes.length})`}>
        <p style={{fontSize: 12}}>Record successes and failures against their original configuration. An observation can support a reviewed evidence record; it never qualifies another setup automatically.</p>
        {doc.outcomes.map(o => <div style={cardStyle} key={o.id}><strong>{o.id}</strong> · {o.samples} samples · {o.failures} failures · {o.order} / {o.revision}<p>{o.note}</p><button style={buttonStyle} type="button" onClick={() => setOutcomeEdit(o)}>Edit outcome</button>{" "}<button type="button" style={buttonStyle} onClick={() => remove("outcomes",o.id)}>Remove from draft</button></div>)}
        <form key={`outcome-${outcomeEdit?.id ?? 'new'}-${formEpoch}`} style={{...cardStyle,...gridStyle}} onSubmit={submit(data => {
          upsert("outcomes", {id: outcomeEdit?.id ?? string(data,"id"), source_id:string(data,"source_id"), location:string(data,"location"), revision:string(data,"revision"), order:string(data,"order"),
            scope:readScope(data), requirement_ids:selection(data,"requirement_ids"), samples:Number(string(data,"samples")), failures:Number(string(data,"failures")), observed_on:string(data,"observed_on"), note:string(data,"note"),
            actual_setup_minutes:optionalNumber(data,"actual_setup_minutes"), actual_cycle_minutes:optionalNumber(data,"actual_cycle_minutes"), actual_material_kg:optionalNumber(data,"actual_material_kg")}); setOutcomeEdit(null);
        })}>
          <Field name="id" label="Outcome identifier" value={outcomeEdit?.id ?? `outcome-${doc.outcomes.length + 1}`} required/>
          <Select name="source_id" label="Measurement / production record" value={outcomeEdit?.source_id} options={sources}/><Field name="location" label="Record location" value={outcomeEdit?.location} required/>
          <Field name="revision" label="Built revision" value={outcomeEdit?.revision ?? doc.revision} required/><Field name="order" label="Built order" value={outcomeEdit?.order ?? doc.order} required/>
          <ScopeFields scope={outcomeEdit?.scope ?? doc.scope}/><Choices name="requirement_ids" label="Measured requirements" value={outcomeEdit?.requirement_ids ?? []} options={requirements}/>
          <Field name="samples" label="Sample count" value={outcomeEdit?.samples} required type="number"/><Field name="failures" label="Failure count" value={outcomeEdit?.failures ?? 0} required type="number"/>
          <Field name="observed_on" label="Observation date" value={outcomeEdit?.observed_on ?? new Date().toISOString().slice(0,10)} type="date" required/>
          <Field name="actual_setup_minutes" label="Actual setup minutes" value={outcomeEdit?.actual_setup_minutes} type="number"/><Field name="actual_cycle_minutes" label="Actual cycle minutes per part" value={outcomeEdit?.actual_cycle_minutes} type="number"/><Field name="actual_material_kg" label="Actual material kg" value={outcomeEdit?.actual_material_kg} type="number"/>
          <Field name="note" label="Outcome / limitations" value={outcomeEdit?.note} required/><button style={buttonStyle} type="submit">Save outcome to draft</button>
        </form>
      </Section>
      <Section title="8. External authorization record">
        <p style={{fontSize: 12}}>Record an authorization issued by the responsible customer or engineering authority. CadVerify records the evidence and its scope; it does not issue that authorization.</p>
        <form key={`auth-${formEpoch}`} style={gridStyle} onSubmit={submit(data => update("authorization", {authority:string(data,"authority"), reference:string(data,"reference"), activity:string(data,"activity"), revision:string(data,"revision"), order:string(data,"order"), evidence_id:string(data,"evidence_id")}))}>
          <Field name="authority" label="Issuing authority" value={doc.authorization?.authority} required/><Field name="reference" label="Authorization reference" value={doc.authorization?.reference} required/>
          <Field name="activity" label="Permitted activity / restrictions" value={doc.authorization?.activity} required/><Field name="revision" label="Authorized revision" value={doc.authorization?.revision ?? doc.revision} required/><Field name="order" label="Authorized order" value={doc.authorization?.order ?? doc.order} required/>
          <Select name="evidence_id" label="Reviewed authorization evidence" value={doc.authorization?.evidence_id} options={doc.evidence.filter(e => e.kind === "authorization").map(e => ({id:e.id,label:e.id}))}/>
          <button type="submit" style={buttonStyle}>Attach authorization record</button>
        </form>
      </Section>
      <label style={labelStyle}>Reviewer note / decision rationale<textarea style={inputStyle} value={note} maxLength={2000} onChange={e => setNote(e.target.value)}/></label>
      <div style={{display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap"}}>
        <button type="button" style={{...buttonStyle, background: C.ink, color: "white"}} disabled={busy || (!decisionId && !packet)} onClick={() => void save()}>Save and assess package</button>
        <button type="button" style={buttonStyle} disabled={busy || !note.trim() || (!decisionId && !packet)} onClick={() => void save({state:"issued"})}>Issue decision packet</button>
      </div>
      <p style={{fontSize: 12, color: C.ink55}}>Issuing preserves an immutable packet, including unresolved blockers. It does not authorize production.</p>
    </fieldset>
    {packet && <div style={{display: "flex", flexWrap:"wrap", gap:14, paddingTop: 14, borderTop:`1px solid ${C.hair}`, fontFamily:MONO, fontSize:12}}>
      <span>Saved v{packet.version}:</span>{["pdf","json","csv","html"].map(format => <a key={format} href={packageExportUrl(packet.id,format)} download>Download {format.toUpperCase()}</a>)}
    </div>}
  </section>;
}
