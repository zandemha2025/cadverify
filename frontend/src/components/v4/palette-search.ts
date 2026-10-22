/**
 * What search finds a part and a record by (buyer-06, buyer-16). "anodize", "AS9100" and
 * "spec" found nothing, and "plate" listed "Open Design Studio" first, then two "Cost
 * record 01M5J2B8" rows with no hint which was current and no part. Parts now come first,
 * found by file name, program or a declared spec, and a record row names the short id the
 * records list shows ("#90ZH0C") and whether it is the latest for its file. Pure, for node --test.
 */

export interface SearchPart {
  mesh_hash: string;
  filename: string | null;
  program: string | null;
  /** The declared specs in words ("Finish: Anodize, Type II, Ra 1.6 µm", "General tolerance: ±0.1 mm"). */
  specs: string[];
}

export interface SearchRecord {
  id: string;
  filename: string;
  created_at: string;
  approval_status?: string;
}

export interface Found {
  id: string;
  label: string;
  sub: string;
  href: string;
}

const partHref = (key: string) => `/app/part/${encodeURIComponent(key)}`;

/** Parts whose file name, program or a declared spec holds every word typed. File-name matches first. */
export function findParts(parts: SearchPart[], query: string, max = 4): Found[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const has = (text: string | null | undefined) => !!text && words.every((w) => text.toLowerCase().includes(w));
  const named: Found[] = [];
  const bySpec: Found[] = [];
  for (const p of parts) {
    const label = p.filename || `Part ${p.mesh_hash.slice(0, 8)}`;
    if (has(p.filename) || has(p.program)) {
      named.push({ id: `p-${p.mesh_hash}`, label, sub: [p.program ? `Program ${p.program}` : "Part", p.specs.length ? p.specs.join(" · ") : null].filter(Boolean).join(" · "), href: partHref(p.mesh_hash) });
      continue;
    }
    const spec = p.specs.find((s) => has(s)) ?? (has(p.specs.join(" ")) ? p.specs.join(" · ") : null);
    if (spec) bySpec.push({ id: `p-${p.mesh_hash}`, label, sub: spec, href: `${partHref(p.mesh_hash)}?lens=use` });
  }
  return [...named, ...bySpec].slice(0, max);
}

/** Record rows: "Cost record #90ZH0C · Oct 22 · latest for this file · not reviewed". */
export function findRecords(recs: SearchRecord[], query: string, max = 4): Found[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const newest = new Map<string, string>();
  for (const r of recs) {
    const prev = newest.get(r.filename);
    if (!prev || r.created_at > (recs.find((x) => x.id === prev)?.created_at ?? "")) newest.set(r.filename, r.id);
  }
  return recs
    .filter((r) => r.filename.toLowerCase().includes(q) || r.id.toLowerCase().includes(q) || r.id.slice(-6).toLowerCase() === q.replace(/^#/, ""))
    .slice(0, max)
    .map((r) => {
      const day = new Date(r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
      const latest = newest.get(r.filename) === r.id ? " · latest for this file" : "";
      return { id: `r-${r.id}`, label: r.filename, sub: `Cost record #${r.id.slice(-6)} · ${day}${latest}${r.approval_status === "approved" ? " · approved" : " · not reviewed"}`, href: `/app/parts/records/${encodeURIComponent(r.id)}` };
    });
}
