"use client";

import { useRef, useState } from "react";
import { isSupportedCad } from "@/lib/cad-file";

/** Optional part picker on sign-in: the part waits in this browser and checks
 * itself as soon as the email link signs the person in. */
export function PartDrop({ file, onFile }: { file: File | null; onFile: (file: File | null) => void }) {
  const input = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function accept(candidate: File | undefined) {
    if (!candidate) return;
    if (!isSupportedCad(candidate.name)) {
      setError("Use a STEP, STL or IGES file.");
      return;
    }
    setError(null);
    onFile(candidate);
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); accept(e.dataTransfer.files?.[0]); }}
      style={{
        border: `1px dashed ${dragging ? "#183d32" : "#aab8a8"}`,
        borderRadius: 8,
        background: dragging ? "#f0f3ec" : "#fbfcfa",
        padding: "12px 14px",
        fontSize: 13,
        lineHeight: 1.5,
        color: "#53635a",
      }}
    >
      <input
        ref={input}
        id="pending-part"
        type="file"
        accept=".step,.stp,.stl,.iges,.igs"
        className="sr-only"
        onChange={(e) => { accept(e.target.files?.[0]); e.target.value = ""; }}
      />
      {file ? (
        <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ color: "#183d32", fontWeight: 500, overflowWrap: "anywhere" }}>{file.name}</span>
          <span>checks itself when you open the link.</span>
          <button type="button" onClick={() => onFile(null)} style={{ border: 0, background: "none", padding: 0, color: "#183d32", textDecoration: "underline", cursor: "pointer", font: "inherit" }}>
            Remove
          </button>
        </span>
      ) : (
        <span>
          <label htmlFor="pending-part" style={{ color: "#183d32", fontWeight: 500, textDecoration: "underline", cursor: "pointer" }}>Add your part now</label>{" "}
          (optional). Drop a STEP, STL or IGES file and it checks itself when you open the link.
        </span>
      )}
      {error && <span role="alert" style={{ display: "block", marginTop: 6, color: "#b42318" }}>{error}</span>}
    </div>
  );
}
