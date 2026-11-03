"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { CAD_ACCEPT, isSupportedCad } from "@/lib/cad-file";
import { browserPendingPartStore, holdPendingPart, PENDING_PART_MAX_BYTES } from "@/lib/pending-part";
import { SignupEmailForm } from "./signup-email-form";
import { useSiteSession } from "./site-shell";

export function HeroUpload({ children }: { children: React.ReactNode }) {
  const { user, siteKey } = useSiteSession();
  const router = useRouter();
  const [part, setPart] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  async function choose(file?: File) {
    if (!file || busy) return;
    setError(null);
    if (!isSupportedCad(file.name) || !file.size) { setError("ScaleCAD works with non-empty STEP, STL and IGES files. Save your part as STEP in your CAD program, then choose it again."); return; }
    if (file.size > PENDING_PART_MAX_BYTES) { setError("Sign in first to upload a file larger than 100 MB."); return; }
    setBusy(true);
    try {
      if (user) {
        if (!await holdPendingPart(browserPendingPartStore(), file, user.email)) throw new Error("File storage unavailable");
        router.push("/verify");
      } else setPart(file);
    } catch { setError("Could not keep this file in your browser. Please try again, or sign in and upload it in ScaleCAD."); }
    finally { setBusy(false); }
  }
  return <div className="cv-hero-upload" data-dragging={dragging} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); void choose(event.dataTransfer.files[0]); }}>
    {children}
    <div className="cv-upload-choice"><label>Have a part? <span>Choose its 3D file</span> to check it.<input type="file" accept={CAD_ACCEPT} disabled={busy} onChange={event => { void choose(event.target.files?.[0]); event.target.value = ""; }} /></label>{busy && <span role="status">Preparing your part…</span>}</div>
    {error && <p className="cv-upload-error" role="alert">{error}</p>}
    {dragging && <div className="cv-drop-hint">Drop to check this part</div>}
    {part && <div className="cv-upload-signup"><strong className="cv-upload-filename">{part.name}</strong><h2>Your part is ready.</h2><p>{siteKey ? "Enter your email and we’ll send you a sign-in link. Your part runs as soon as you click it." : "Create your account to check this part. It stays in this browser until you sign up."}</p><SignupEmailForm part={part} /><button className="cv-text-link" type="button" onClick={async () => { try { await browserPendingPartStore().clear(); setPart(null); } catch { setError("Could not clear the saved file. Please try again."); } }}>Use a different file</button></div>}
  </div>;
}
