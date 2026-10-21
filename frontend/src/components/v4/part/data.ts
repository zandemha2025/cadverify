/** Shape the part page's data from a live check or from what's saved about the part. */
import { readIdentity } from "@/lib/verify/identity";
import { storedServiceEnvironment } from "@/lib/verify/service-conditions";
import type { PartData } from "./ctx";
import type { SavedPart } from "./api";
import type { CheckSession } from "./store";
import { earlierChoiceFrom } from "./choice";

function ext(name: string): string {
  return (name.split(".").pop() ?? "").toUpperCase();
}

export function liveData(s: CheckSession, saved: SavedPart | null): PartData {
  const r = s.result;
  const cost = r?.cost ?? null;
  return {
    key: s.key,
    fileName: s.file.name,
    fileType: ext(s.file.name),
    source: "live",
    validation: s.validation ?? r?.validation ?? null,
    cost,
    costError: r?.costError ?? null,
    machines: r?.machines ?? saved?.machines ?? [],
    context: r?.partContext ?? saved?.context ?? null,
    runEnvironment: r ? r.serviceEnvironment ?? storedServiceEnvironment(r.partContext) : null,
    decisionId: cost?.saved?.id ?? null,
    decision: saved?.latest && cost?.saved?.id === saved.latest.id ? saved.latest : null,
    decisionError: null,
    identity: readIdentity(cost),
    checks: saved ? saved.decisions.length + (cost?.saved && !saved.decisions.some((d) => d.id === cost.saved!.id) ? 1 : 0) : null,
    createdAt: null,
    earlierChoice: saved ? earlierChoiceFrom(saved.decisions, cost?.saved?.id ?? null) : null,
  };
}

export function savedData(key: string, p: SavedPart): PartData {
  const d = p.latest;
  const fileName = d?.filename ?? p.catalog?.filename ?? p.decisions[0]?.filename ?? p.validation?.filename ?? "Part";
  return {
    key,
    fileName,
    fileType: (d?.file_type ?? p.catalog?.file_type ?? ext(fileName)).toUpperCase(),
    source: "saved",
    validation: p.validation,
    cost: d?.result ?? null,
    costError: null,
    machines: p.machines,
    context: p.context,
    // A saved record doesn't say which conditions it was costed under; the
    // stored ones are shown, and the Use lens says when they changed after it.
    runEnvironment: storedServiceEnvironment(p.context),
    decisionId: d?.id ?? null,
    decision: d,
    decisionError: p.latestError,
    identity: null,
    checks: p.decisions.length,
    createdAt: d?.created_at ?? null,
    earlierChoice: earlierChoiceFrom(p.decisions, d?.id ?? null),
  };
}
