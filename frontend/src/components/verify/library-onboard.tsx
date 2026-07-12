"use client";

/**
 * PARTS-MASTER onboarding panel — the flywheel's COLD START (customer-context
 * Slice 2). Bulk-onboard a customer's existing part library (CAD files + an
 * identity mapping) so the org identity corpus has REAL declared identities on day
 * one — then a later upload of a similar part surfaces "Looks like your <name>".
 *
 * Minimal, in the Verify light-instrument idiom (tokens + primitives). It shows the
 * live library size, lets an analyst pick CAD files + an identity CSV/JSON, POSTs to
 * /identity/library/onboard, and shows the HONEST readout — onboarded N, library now
 * M, and every skipped file with its reason (never a fabricated success).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { C, MONO } from "@/lib/verify/tokens";
import { Kicker, GhostButton } from "./primitives";
import { onboardLibrary, fetchLibrary } from "@/lib/verify/library-api";
import { onboardReadout, type OnboardSummary } from "@/lib/verify/library";

const CAD_EXTS = ".stl,.step,.stp,.iges,.igs";

export function LibraryOnboard({ onChanged }: { onChanged?: () => void }) {
  const [size, setSize] = useState<number | null>(null);
  const [cadFiles, setCadFiles] = useState<File[]>([]);
  const [mapping, setMapping] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<OnboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cadRef = useRef<HTMLInputElement | null>(null);
  const mapRef = useRef<HTMLInputElement | null>(null);

  const refreshSize = useCallback(async () => {
    try {
      const lib = await fetchLibrary();
      setSize(lib.library_size);
    } catch {
      setSize(null); // quiet — the size is a nicety, not load-bearing
    }
  }, []);

  useEffect(() => {
    void refreshSize();
  }, [refreshSize]);

  const submit = useCallback(async () => {
    if (busy || cadFiles.length === 0) return;
    setBusy(true);
    setError(null);
    setSummary(null);
    const res = await onboardLibrary(cadFiles, mapping);
    if (res.ok) {
      setSummary(res.summary);
      setSize(res.summary.library_size);
      setCadFiles([]);
      setMapping(null);
      if (cadRef.current) cadRef.current.value = "";
      if (mapRef.current) mapRef.current.value = "";
      onChanged?.();
    } else {
      setError(res.error);
    }
    setBusy(false);
  }, [busy, cadFiles, mapping, onChanged]);

  return (
    <div
      style={{
        marginTop: 18,
        maxWidth: 1100,
        border: `1px solid ${C.hair}`,
        borderRadius: 16,
        background: C.panel,
        padding: "18px 20px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Kicker>PARTS-MASTER · IDENTITY LIBRARY</Kicker>
        <span
          style={{
            fontFamily: MONO,
            fontSize: 11,
            border: `1px solid ${C.hair}`,
            borderRadius: 999,
            padding: "3px 10px",
            color: C.ink55,
          }}
        >
          library: {size === null ? "—" : size} part{size === 1 ? "" : "s"}
        </span>
      </div>
      <p style={{ margin: "8px 0 0", maxWidth: 680, fontSize: 12.5, lineHeight: 1.6, color: C.ink50 }}>
        Onboard your existing part library — CAD files plus an identity mapping (CSV or JSON with{" "}
        <span style={{ fontFamily: MONO }}>filename, part_id, name, program, material_class</span>) — so the corpus
        knows your parts by name on day one. A file with no declared name onboards as bare geometry, never a guess.
      </p>

      <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
        <label style={pickerStyle}>
          <input
            ref={cadRef}
            type="file"
            multiple
            accept={CAD_EXTS}
            style={{ display: "none" }}
            onChange={(e) => setCadFiles(Array.from(e.target.files ?? []))}
          />
          {cadFiles.length ? `${cadFiles.length} CAD file${cadFiles.length === 1 ? "" : "s"}` : "Choose CAD files…"}
        </label>
        <label style={pickerStyle}>
          <input
            ref={mapRef}
            type="file"
            accept=".csv,.json,text/csv,application/json"
            style={{ display: "none" }}
            onChange={(e) => setMapping(e.target.files?.[0] ?? null)}
          />
          {mapping ? mapping.name : "Identity mapping (optional)…"}
        </label>
        <GhostButton primary disabled={busy || cadFiles.length === 0} onClick={() => void submit()}>
          {busy ? "Onboarding…" : "Onboard library"}
        </GhostButton>
      </div>

      {error && (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          onboard failed — {error}
        </p>
      )}

      {summary && (
        <div style={{ marginTop: 12, borderTop: `1px solid #efeff2`, paddingTop: 12 }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 12, color: C.pass }}>{onboardReadout(summary)}</p>
          {summary.manifest_registered > 0 && (
            <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
              {summary.manifest_registered} registered in the declared parts master
            </p>
          )}
          {summary.skipped.length > 0 && (
            <ul style={{ margin: "8px 0 0", padding: "0 0 0 16px", listStyle: "none" }}>
              {summary.skipped.map((sk) => (
                <li key={sk.filename} style={{ fontFamily: MONO, fontSize: 10.5, color: C.cond, lineHeight: 1.7 }}>
                  skipped {sk.filename} — {sk.reason}
                </li>
              ))}
            </ul>
          )}
          {summary.mapping_errors.length > 0 && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.cond }}>
              {summary.mapping_errors.length} mapping row{summary.mapping_errors.length === 1 ? "" : "s"} ignored
              (see reasons) — nothing fabricated
            </p>
          )}
        </div>
      )}
    </div>
  );
}

const pickerStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  fontFamily: "inherit",
  fontSize: 12,
  cursor: "pointer",
  borderRadius: 999,
  padding: "8px 16px",
  border: `1px dashed #c9c9ce`,
  background: "transparent",
  color: C.ink70,
};
