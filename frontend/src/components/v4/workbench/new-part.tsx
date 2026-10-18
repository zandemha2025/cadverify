"use client";

/**
 * F9 · New part: drop one CAD file with the costing options beside it. The
 * Workbench runs its own cost (POST /validate/cost) and DFM check
 * (POST /validate) with those options; "Open decision" lands on the lens's tab.
 */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { fetchCatalog, type CatalogRowApi } from "@/lib/api";
import { isQuotaErrorMessage } from "@/lib/api-recovery";
import { fileExt, isSupportedCad, unsupportedCadGuidance } from "@/lib/cad-file";
import { clientStlIntegrityError } from "@/lib/stl-validation";
import { analysisFailureCopy } from "@/lib/verify/failure-copy";
import { R, TABS } from "../routes";
import { CAD_ACCEPT, setPendingFile } from "../pending-file";
import { Failed, Loading, SubNav, cx } from "../ui";
import { DEFAULT_FORM, formProblem, formToOptions, cavProblem, qtyParts, qtyProblem, type FormDraft } from "./derive";
import { beginPart, getWb, retryBegin, useWb } from "./session";
import { WbLink, lensDef, takeNewPartFile, useLens, wbHref, useWbNav } from "./chrome";
import { COMPLEXITY_OPTIONS, MATERIAL_OPTIONS, REGION_OPTIONS, methodName, money, qtyListText, qtyText, whenText } from "./words";

type ErrKind = "timeout" | "qty" | "type" | "geom" | "quota" | "unreadable";
type Err = { kind: ErrKind; title: string; text: string };

export function PartGlyph({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

export function OptionsForm({
  form,
  setForm,
  unitsEnabled,
  unitsHint,
  idp,
  disabled,
}: {
  form: FormDraft;
  setForm: (f: FormDraft) => void;
  unitsEnabled: boolean;
  unitsHint: string;
  idp: string;
  disabled?: boolean;
}) {
  const qBad = qtyProblem(form.qty);
  const cBad = cavProblem(form.cav);
  const up = (k: keyof FormDraft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <>
      <label className="field full">
        Quantities
        <input type="text" inputMode="numeric" value={form.qty} onChange={up("qty")} aria-invalid={!!qBad} aria-describedby={`${idp}-q`} disabled={disabled} />
        <span className={qBad ? "fe" : "fh"} id={`${idp}-q`}>
          {qBad ?? "Costed at each. The slider estimates between them."}
        </span>
      </label>
      <label className="field">
        Material class
        <select value={form.mat} onChange={up("mat")} disabled={disabled}>
          {MATERIAL_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Region
        <select value={form.reg} onChange={up("reg")} disabled={disabled}>
          {REGION_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        CAD source units
        <select value={form.units} onChange={up("units")} disabled={disabled || !unitsEnabled} aria-describedby={`${idp}-u`}>
          <option value="mm">Millimeters</option>
          <option value="inch">Inches</option>
        </select>
        <span className="fh" id={`${idp}-u`}>
          {unitsHint}
        </span>
      </label>
      <label className="field">
        Complexity
        <select value={form.cx} onChange={up("cx")} disabled={disabled} aria-describedby={`${idp}-c`}>
          {COMPLEXITY_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <span className="fh" id={`${idp}-c`}>
          Tooling routes only
        </span>
      </label>
      <label className="field">
        Mold cavities
        <input type="number" min={1} step={1} value={form.cav} onChange={up("cav")} aria-invalid={!!cBad} aria-describedby={`${idp}-v`} disabled={disabled} />
        <span className={cBad ? "fe" : "fh"} id={`${idp}-v`}>
          {cBad ?? "Molds and dies only"}
        </span>
      </label>
    </>
  );
}

// The draft survives leaving and coming back in this tab.
let draftMem: FormDraft = DEFAULT_FORM;

function Recent() {
  const [rows, setRows] = React.useState<CatalogRowApi[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setErr(null);
    fetchCatalog({ pageSize: 50, state: "Costed" })
      .then((p) => live && setRows([...(p.rows ?? [])].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 3)))
      .catch((e) => live && setErr(e instanceof Error ? e.message : "Recent parts didn’t load."));
    return () => {
      live = false;
    };
  }, [n]);
  return (
    <section className="panel rec" aria-labelledby="rec-h">
      <div className="ph">
        <h2 id="rec-h">Recent</h2>
        <span>
          <a className="lk" href={R.records} style={{ fontSize: 12.5 }}>
            All records
          </a>
        </span>
      </div>
      {err ? (
        <Failed title="Recent parts didn’t load" detail={err} onRetry={() => setN((x) => x + 1)} />
      ) : rows == null ? (
        <Loading rows={2} label="Loading recent parts" />
      ) : rows.length === 0 ? (
        <p className="smeta" style={{ padding: "0 16px 14px" }}>
          No saved decisions yet. A costed part lands here.
        </p>
      ) : (
        <div className="list" style={{ padding: "0 8px 8px" }} role="list" aria-label="Recent saved decisions">
          {rows.map((r) => {
            const route = r.recommended_route ? methodName(r.recommended_route.process) : null;
            const price = r.unit_cost?.usd != null && r.unit_cost.qty != null ? `${money(r.unit_cost.usd)} at ${qtyText(r.unit_cost.qty)}` : r.unit_cost?.withheld ? "Price withheld" : "";
            return (
              <div role="listitem" key={r.part_key}>
                <WbLink className="lrow" href={wbHref(null, r.part_key)}>
                  <span className="th th-g" aria-hidden="true">
                    <PartGlyph />
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <b>{r.filename}</b>
                    <small>{[route, whenText(r.updated_at)].filter(Boolean).join(" · ")}</small>
                  </span>
                  <span className="c num">{price}</span>
                </WbLink>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function NewPart() {
  const s = useWb();
  const lens = useLens();
  const nav = useWbNav();
  const sp = useSearchParams();
  const issue = sp.get("issue");
  const issueEvidence = sp.get("issue_evidence");
  const [form, setFormState] = React.useState<FormDraft>(draftMem);
  const setForm = (f: FormDraft) => {
    draftMem = f;
    setFormState(f);
  };
  const [phase, setPhase] = React.useState<"idle" | "up" | "err" | "done">("idle");
  const [err, setErr] = React.useState<Err | null>(null);
  const [name, setName] = React.useState<string | null>(null);
  const [sentQty, setSentQty] = React.useState<string>("");
  const [over, setOver] = React.useState(false);
  const input = React.useRef<HTMLInputElement>(null);
  const isStl = name ? fileExt(name) === "stl" : true;

  const settle = React.useCallback(() => {
    const st = getWb();
    if (st.report) {
      setPhase("done");
      setErr(null);
      return;
    }
    const e = st.cost.error ?? "The cost didn’t finish.";
    if (st.cost.geom) setErr({ kind: "geom", title: "No cost: the mesh isn’t closed", text: `${st.cost.geom.reason ?? "The geometry isn’t watertight."} Repair the mesh, then cost it again.` });
    else if (isQuotaErrorMessage(e)) setErr({ kind: "quota", title: "No checks left", text: analysisFailureCopy(e).explanation || "This period’s checks are used up." });
    else setErr({ kind: "timeout", title: "Cost didn’t finish", text: `${e} File and options are kept.` });
    setPhase("err");
  }, []);

  const start = React.useCallback(
    async (file: File) => {
      setName(file.name);
      if (!isSupportedCad(file.name)) {
        const g = unsupportedCadGuidance(file.name);
        const ext = fileExt(file.name);
        setErr({ kind: "type", title: ext && g.title.startsWith("This CAD") ? `Can’t read .${ext} files` : g.title, text: "Use STL, STEP, STP, IGES or IGS." });
        setPhase("err");
        return;
      }
      const bad = formProblem(draftMem);
      if (bad) {
        setErr({ kind: "qty", title: qtyProblem(draftMem.qty) ? "Fix the quantity list first" : "Fix the cavity count first", text: bad });
        setPhase("err");
        return;
      }
      if (file.name.toLowerCase().endsWith(".stl")) {
        const integrity = await clientStlIntegrityError(file);
        if (integrity) {
          const c = analysisFailureCopy(integrity);
          setErr({ kind: "unreadable", title: c.title, text: `${c.explanation} ${c.action}` });
          setPhase("err");
          return;
        }
      }
      setErr(null);
      setPhase("up");
      setSentQty(qtyListText(qtyParts(draftMem.qty).map(Number)));
      await beginPart(file, formToOptions(draftMem));
      settle();
    },
    [settle],
  );

  // A file handed over from "Open it as a new part".
  React.useEffect(() => {
    const f = takeNewPartFile();
    if (f) void start(f);
  }, [start]);

  const choose = () => input.current?.click();
  const retry = async () => {
    setErr(null);
    setPhase("up");
    await retryBegin();
    settle();
  };
  const landing = lensDef(lens).tab;
  const openHref = s.key
    ? issue
      ? wbHref("routing", s.key, { issue, issue_evidence: issueEvidence })
      : wbHref(landing, s.key, lens === "buyer" ? { trust: 1 } : undefined)
    : R.workbench;

  return (
    <>
      <div className="pagehead">
        <h1 className="ptitle">Workbench</h1>
        <p className="pmeta">
          <span>No part loaded</span>
          <span>STL, STEP, STP, IGES, IGS</span>
          <span>Uploaded CAD kept as evidence for your organization</span>
        </p>
        <SubNav tabs={TABS.make} label="Make and fit" />
      </div>
      <div className="wb-main">
        <div
          className={cx("drop", (over || phase === "up") && "over")}
          role="region"
          aria-label="File drop"
          onDragOver={(e) => {
            if (phase === "up") return;
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            if (phase === "up") return;
            const f = e.dataTransfer.files?.[0];
            if (f) void start(f);
          }}
        >
          {phase === "idle" ? (
            <>
              <b>No part loaded</b>
              <span>Drop one CAD file to cost it and check it.</span>
              <button className="btn ink" type="button" onClick={choose}>
                Choose file
              </button>
              <small>STL, STEP, STP, IGES or IGS · options on the right apply</small>
            </>
          ) : phase === "up" ? (
            <>
              <b>Costing</b>
              <span className="fn">{name}</span>
              <span className="bar2" aria-hidden="true">
                <i />
              </span>
              <small role="status">Pricing every method at {sentQty}</small>
            </>
          ) : phase === "err" ? (
            <>
              <b className="fn" style={{ fontSize: 18 }}>
                {name}
              </b>
              <span>Not costed yet</span>
            </>
          ) : (
            <>
              <b className="fn" style={{ fontSize: 18 }}>
                {name}
              </b>
              <span role="status">{s.dfm.phase === "running" ? "Costed · still checking DFM" : "Costed and checked"}</span>
              <WbLink className="btn ink" href={openHref}>
                Open decision
              </WbLink>
            </>
          )}
          <input
            ref={input}
            type="file"
            accept={CAD_ACCEPT}
            aria-label="Choose a CAD file to cost"
            tabIndex={-1}
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void start(f);
            }}
          />
        </div>
        {issue && phase === "idle" ? (
          <div className="iss" role="note">
            <b>Issue link · {issue.split("|")[0]}</b>
            <span>Drop the same file to open that finding. The link doesn’t contain the file.</span>
          </div>
        ) : null}
        {phase === "err" && err ? (
          <div className="errc" role="alert">
            <b>{err.title}</b>
            <span>{err.text}</span>
            <span style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
              {err.kind === "timeout" ? (
                <button className="btn ink sm" type="button" onClick={() => void retry()}>
                  Try again
                </button>
              ) : null}
              {err.kind === "geom" ? (
                <button
                  className="btn ink sm"
                  type="button"
                  onClick={() => {
                    const f = getWb().file;
                    if (f) setPendingFile(f);
                    nav(R.check);
                  }}
                >
                  Repair the mesh
                </button>
              ) : null}
              {err.kind === "quota" ? (
                <a className="btn ink sm" href={R.billing}>
                  See plans
                </a>
              ) : null}
              <button className="btn sm" type="button" onClick={choose}>
                Choose another file
              </button>
            </span>
          </div>
        ) : null}
        <Recent />
      </div>
      <aside className="sheet" aria-label="Costing options">
        <div className="top">
          <h2 className="stitle">Costing options</h2>
          <p className="smeta">Applied to the next file · change later in Decision</p>
        </div>
        <div className="scroll">
          <div className="wb-frm">
            <OptionsForm
              form={form}
              setForm={setForm}
              unitsEnabled={isStl}
              unitsHint="STL only. STEP and IGES carry their own units."
              idp="np"
              disabled={phase === "up"}
            />
          </div>
          <div className="note">
            <b>Defaults</b>
            <span>Quantities 50 and 5,000 · polymer · auto region · millimeters · moderate · 1 cavity.</span>
          </div>
          <div style={{ padding: 12 }}>
            <button className="btn sm" type="button" onClick={() => setForm(DEFAULT_FORM)} disabled={phase === "up"}>
              Reset to defaults
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
