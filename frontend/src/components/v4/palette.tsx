"use client";

/**
 * Search and commands (⌘K). Lists go-to destinations and actions, searches your
 * saved records and machines, and shows answers a page registers (the part page
 * registers answers drawn from that part's own results; nothing is generated).
 * No open/close animation: it's used many times a day.
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/ui/auth-provider";
import { API_BASE } from "@/lib/api-base";
import { R } from "./routes";
import { LEGACY_WORKBENCH } from "./workbench/cost-url";
import { cx } from "./ui";

export type PaletteItem = {
  id: string;
  group: string;
  label: string;
  sub?: string;
  href?: string;
  run?: () => void;
  key?: string;
  /** Extra words that should match the search. */
  words?: string;
  /** Other names typed for this item (older names); an exact one selects it like its label. */
  alias?: string[];
  /** Shown under the row when it's selected (an answer). */
  answer?: { text: string; source: string };
};

type Ctx = {
  open: boolean;
  setOpen: (v: boolean) => void;
  extra: PaletteItem[];
  setExtra: (owner: string, items: PaletteItem[]) => void;
  currentPart: { label: string; href: string } | null;
  setCurrentPart: (p: { label: string; href: string } | null) => void;
};

const PaletteContext = React.createContext<Ctx | null>(null);

export function PaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const [owned, setOwned] = React.useState<Record<string, PaletteItem[]>>({});
  const [currentPart, setCurrentPart] = React.useState<{ label: string; href: string } | null>(null);
  const setExtra = React.useCallback((owner: string, items: PaletteItem[]) => {
    setOwned((o) => ({ ...o, [owner]: items }));
  }, []);
  const extra = React.useMemo(() => Object.values(owned).flat(), [owned]);
  const value = React.useMemo(() => ({ open, setOpen, extra, setExtra, currentPart, setCurrentPart }), [open, extra, setExtra, currentPart]);
  return <PaletteContext.Provider value={value}>{children}</PaletteContext.Provider>;
}

export function usePalette(): Ctx {
  const c = React.useContext(PaletteContext);
  if (!c) throw new Error("usePalette outside PaletteProvider");
  return c;
}

/** Let a page add its own palette entries (for example, answers about the open part) while it's mounted. */
export function useRegisterPaletteItems(owner: string, items: PaletteItem[]) {
  const { setExtra } = usePalette();
  const sig = JSON.stringify(items.map((i) => [i.id, i.label, i.sub, i.href, i.answer?.text]));
  React.useEffect(() => {
    setExtra(owner, items);
    return () => setExtra(owner, []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owner, sig, setExtra]);
}

type Rec = { id: string; filename: string; created_at: string; approval_status?: string };
type Mach = { id: string; name: string; process?: string };

/** Go-to rows: label, detail, where, shortcut key, older names people may type. */
const GO: [string, string, string, string?, string[]?][] = [
  ["Home", "Needs you, recent parts, setup", R.home, "H"],
  ["Parts", "Every checked part", R.parts, "P"],
  ["Cost records", "Saved costs and decisions, with their sources", R.records, "R", ["records"]],
  ["DFM checks", "Every manufacturability check, newest first", R.analyses, undefined, ["analyses"]],
  ["Programs", "Parts by program and yearly volume", R.programs, "G"],
  ["Machines and printers", "Your shop", R.shop, "M"],
  ["Make or buy", "In-house, outside or invest, across parts", R.triage, "T", ["triage"]],
  ["Rates and actual costs", "Rates in effect, logged jobs, changes to review", R.rates, "C", ["real costs"]],
  ["RFQ packages", "Files and findings for supplier quotes", R.packages, undefined, ["supplier packages"]],
  ["Batch runs", "Many parts at once · Pilot", R.many],
  ["Imports", "SAP, Windchill or CSV, read only", R.imports],
  ["Cost breakdown", "Every cost line of a part, its source and rate, editable", LEGACY_WORKBENCH, undefined, ["workbench", "glass box", "should-cost"]],
  ["Organization", "Members and sign-in", R.org],
  ["API and keys", "For your own tools", R.api],
  ["Plan and billing", "Free checks, Pro, pilot", R.billing],
  ["Notifications", "Inbox", R.notifications],
];

export function Palette({ onPickFile, onShortcuts }: { onPickFile: () => void; onShortcuts: () => void }) {
  const { open, setOpen, extra, currentPart } = usePalette();
  const { signOut } = useAuth();
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  const [sel, setSel] = React.useState(-1);
  const [recs, setRecs] = React.useState<Rec[] | null>(null);
  const [machines, setMachines] = React.useState<Mach[] | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const returnTo = React.useRef<HTMLElement | null>(null);

  React.useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    setQuery("");
    setSel(-1);
    if (recs == null)
      fetch(`${API_BASE}/cost-decisions?limit=50`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((b) => setRecs(b?.cost_decisions ?? []))
        .catch(() => setRecs([]));
    if (machines == null)
      fetch(`${API_BASE}/machine-inventory`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((b) => setMachines(Array.isArray(b) ? b : (b?.machines ?? b?.items ?? [])))
        .catch(() => setMachines([]));
  }, [open, recs, machines]);

  const close = React.useCallback(() => {
    setOpen(false);
    returnTo.current?.focus?.();
  }, [setOpen]);

  const q = query.trim().toLowerCase();
  const hit = (...xs: (string | undefined)[]) => !q || xs.some((x) => x?.toLowerCase().includes(q));

  const actions: PaletteItem[] = [
    { id: "a-check", group: "Actions", label: "Check a part", sub: "Open a STEP, STL or IGES file", run: onPickFile, words: "upload verify cad file" },
    { id: "a-sample", group: "Actions", label: "Run the sample", sub: "Sample bracket · real engine output · no check used", href: `${R.check}?sample=1`, words: "example demo bracket" },
    { id: "a-setup", group: "Actions", label: "Set up your organization", sub: "Machines, rates, conditions, programs, team", href: R.setup, words: "guide checklist onboarding start here" },
    { id: "a-machine", group: "Actions", label: "Add a machine", sub: "Opens the add form", href: `${R.shop}?add=1`, words: "printer import floor" },
    { id: "a-program", group: "Actions", label: "Assign a program", sub: "Program and yearly volume for a part", href: R.programs, words: "volume lineage" },
    { id: "a-compare", group: "Actions", label: "Compare records", sub: "Two saved cost records side by side", href: R.compare, words: "diff a/b" },
    { id: "a-equip", group: "Actions", label: "Plan equipment", sub: "What to buy for parts you can't make in-house", href: R.triage, words: "capability acquisition invest" },
    { id: "a-studio", group: "Actions", label: "Open Design Studio", sub: "Plate, bracket or enclosure as real CAD", href: R.studio, words: "design create revision" },
    { id: "a-fit", group: "Actions", label: "Fit in assembly", sub: "Interference and clearance with the parts around it", href: R.fit, key: "F", words: "assembly collision gap interference clearance fit in context" },
    { id: "a-keys", group: "Actions", label: "Keyboard shortcuts", sub: "Every key", run: onShortcuts, key: "?", words: "hotkeys help" },
    { id: "a-out", group: "Actions", label: "Sign out", sub: "Signs you out on every device", run: () => void signOut(), words: "log out logout leave" },
  ];
  const go: PaletteItem[] = [
    ...(currentPart ? [{ id: "g-part", group: "Go to", label: "Part", sub: `${currentPart.label}, the part you have open`, href: currentPart.href, key: "V" }] : []),
    ...GO.map(([label, sub, href, key, alias]) => ({ id: `g-${href}`, group: "Go to", label, sub, href, key, alias, words: alias?.join(" ") })),
  ];
  const recItems: PaletteItem[] = q
    ? (recs ?? []).filter((r) => hit(r.filename, r.id)).slice(0, 4).map((r) => ({ id: `r-${r.id}`, group: "Cost records", label: r.filename, sub: `Cost record ${r.id.slice(0, 8)} · ${new Date(r.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}${r.approval_status === "approved" ? " · approved" : " · not reviewed"}`, href: R.record(r.id) }))
    : [];
  const machItems: PaletteItem[] = q
    ? (machines ?? []).filter((m) => hit(m.name, m.process)).slice(0, 3).map((m) => ({ id: `m-${m.id}`, group: "Your machines", label: m.name, sub: m.process ?? "", href: `${R.shop}?machine=${encodeURIComponent(m.id)}` }))
    : [];

  const groups: [string, PaletteItem[], number][] = [];
  const extraGroups = Array.from(new Set(extra.map((e) => e.group)));
  for (const g of extraGroups) groups.push([g, extra.filter((e) => e.group === g && hit(e.label, e.sub, e.words, e.answer?.text)), q ? 3 : 2]);
  groups.push(["Actions", actions.filter((a) => hit(a.label, a.sub, a.words)), q ? 4 : 5]);
  groups.push(["Cost records", recItems, 4]);
  groups.push(["Your machines", machItems, 3]);
  groups.push(["Go to", go.filter((g) => hit(g.label, g.sub, g.words)), q ? 5 : 8]);

  const flat: PaletteItem[] = [];
  const rendered = groups
    .filter(([, list]) => list.length)
    .map(([name, list, max]) => {
      const shown = list.slice(0, max);
      const start = flat.length;
      flat.push(...shown);
      return { name, items: shown, start };
    });
  // Until the user moves the selection, an exact name match is selected (so "Parts" ↵ opens Parts; an older name such as "records" works too).
  const exact = q ? flat.findIndex((f) => f.label.toLowerCase() === q || !!f.alias?.includes(q)) : -1;
  const cur = Math.min(sel < 0 ? Math.max(exact, 0) : sel, Math.max(0, flat.length - 1));

  const activate = (it: PaletteItem | undefined) => {
    if (!it) return;
    if (it.answer) {
      // Answers expand in place; a second Enter follows their link if they have one.
      if (it.href) router.push(it.href);
      close();
      return;
    }
    close();
    if (it.run) it.run();
    else if (it.href) router.push(it.href);
  };

  if (!open) return null;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 50 }}>
      <button type="button" tabIndex={-1} aria-hidden="true" onClick={close} style={{ position: "absolute", inset: 0, border: 0, padding: 0, background: "rgba(237,239,242,.55)", backdropFilter: "blur(2px)", cursor: "default" }} />
      <section role="dialog" aria-modal="true" aria-label="Search and commands" style={{ position: "absolute", left: "50%", top: 96, width: 680, maxWidth: "calc(100% - 32px)", transform: "translateX(-50%)", background: "#fff", borderRadius: 20, border: "1px solid var(--rule)", boxShadow: "0 30px 80px rgba(20,24,31,.20)", overflow: "hidden", display: "flex", flexDirection: "column", maxHeight: "min(780px, calc(100dvh - 140px))" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 16px", height: 60, borderBottom: "1px solid var(--rule)" }}>
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <circle cx="9" cy="9" r="5.5" stroke="currentColor" strokeWidth="1.7" />
            <path d="m13.5 13.5 3.5 3.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            autoFocus
            type="text"
            value={query}
            aria-label="Search parts, records, machines and tools, or ask"
            aria-controls="v4-pal-res"
            aria-activedescendant={flat.length ? `v4-pal-${cur}` : undefined}
            role="combobox"
            aria-expanded="true"
            placeholder="Search parts, records, machines and tools, or ask"
            onChange={(e) => {
              setQuery(e.target.value);
              setSel(-1);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel(Math.min(cur + 1, flat.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel(Math.max(cur - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                activate(flat[cur]);
              } else if (e.key === "Escape") {
                e.preventDefault();
                close();
              }
            }}
            style={{ flex: 1, height: 58, border: 0, outline: 0, fontSize: 17, background: "transparent" }}
          />
          <kbd style={{ fontFamily: "inherit", fontSize: 12, color: "var(--ink2)", border: "1px solid var(--rule2)", borderRadius: 6, padding: "1px 6px" }}>esc</kbd>
        </div>
        <div id="v4-pal-res" role="listbox" aria-label="Results" style={{ overflow: "auto", padding: "6px 8px 10px" }}>
          {rendered.map((g) => (
            <div key={g.name} role="group" aria-label={g.name}>
              <div style={{ padding: "10px 10px 4px", fontSize: 12.5, fontWeight: 600, color: "var(--ink3)" }}>{g.name}</div>
              {g.items.map((it, i) => {
                const idx = g.start + i;
                const on = idx === cur;
                return (
                  <React.Fragment key={it.id}>
                    <div
                      id={`v4-pal-${idx}`}
                      role="option"
                      aria-selected={on}
                      className={cx("mrow", on && "on")}
                      onMouseMove={() => setSel(idx)}
                      onClick={() => activate(it)}
                      style={{ minHeight: 44 }}
                    >
                      <span style={{ width: 28, height: 28, borderRadius: 8, background: "#F1F2F4", display: "grid", placeItems: "center", fontSize: 12, fontWeight: 700, color: "var(--ink2)", flex: "none" }} aria-hidden="true">
                        {it.answer ? "?" : it.group === "Go to" ? "→" : it.group === "Cost records" ? "R" : it.group === "Your machines" ? "M" : "+"}
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b style={{ fontSize: 14 }}>{it.label}</b>
                        {it.sub ? <small>{it.sub}</small> : null}
                      </span>
                      {it.key ? (
                        <kbd style={{ marginLeft: "auto", fontFamily: "inherit", fontSize: 12, color: "var(--ink2)", border: "1px solid var(--rule2)", borderRadius: 6, padding: "1px 6px", background: "#fff" }}>{it.key}</kbd>
                      ) : null}
                    </div>
                    {it.answer && on ? (
                      <div style={{ margin: "0 10px 6px 48px", padding: "10px 12px", borderRadius: 12, background: "#F6F7F8", fontSize: 14, display: "flex", flexDirection: "column", gap: 4 }}>
                        <b style={{ fontWeight: 600 }}>{it.answer.text}</b>
                        <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>Source: {it.answer.source}</span>
                      </div>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </div>
          ))}
          {flat.length === 0 ? <p style={{ padding: "24px 16px", color: "var(--ink3)", textAlign: "center", fontSize: 14 }}>No matches for “{query}”</p> : null}
        </div>
        <div style={{ display: "flex", gap: 16, padding: "10px 16px", borderTop: "1px solid var(--rule)", color: "var(--ink3)", fontSize: 12, flexWrap: "wrap" }}>
          <span>↑ ↓ move</span>
          <span>↵ open</span>
          <span>esc close</span>
          {extra.some((e) => e.answer) ? <span>Answers use this part&apos;s results only</span> : null}
        </div>
      </section>
    </div>
  );
}
