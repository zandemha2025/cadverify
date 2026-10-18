"use client";

/**
 * v4 shell: the one-line top bar (sections, search, Check a part, notifications,
 * account), the search-and-commands palette (⌘K) and keyboard shortcuts (?).
 * Pages render inside `.ob`, the scope every v4 style lives under.
 */
import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/components/ui/auth-provider";
import { API_BASE } from "@/lib/api-base";
import { ANALYTICS_CONSENT } from "@/lib/analytics";
import { NAV, R, GO_KEYS, sectionOf } from "./routes";
import { CAD_ACCEPT, setPendingFile } from "./pending-file";
import { Palette, PaletteProvider, usePalette } from "./palette";
import { cx } from "./ui";

type Usage = { plan: string; tier?: string; unlimited: boolean; used: number; cap: number; remaining: number };
type Org = { org_id: string; name: string; org_role: string; is_active: boolean };

const ShellContext = React.createContext<{
  pickFile: () => void;
  openShortcuts: () => void;
  usage: Usage | null;
  refreshUsage: () => void;
}>({ pickFile: () => {}, openShortcuts: () => {}, usage: null, refreshUsage: () => {} });

export function useShell() {
  return React.useContext(ShellContext);
}

function initials(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  const two = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return two.toUpperCase() || "?";
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function V4Shell({ children }: { children: React.ReactNode }) {
  return (
    <PaletteProvider>
      <ShellInner>{children}</ShellInner>
    </PaletteProvider>
  );
}

function ShellInner({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const palette = usePalette();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [shortcuts, setShortcuts] = React.useState(false);
  const [usage, setUsage] = React.useState<Usage | null>(null);

  const refreshUsage = React.useCallback(() => {
    fetch("/api/auth/me/usage")
      .then((r) => (r.ok ? r.json() : null))
      .then((u) => setUsage(u))
      .catch(() => setUsage(null));
  }, []);
  React.useEffect(() => {
    refreshUsage();
    window.addEventListener("proofshape:usage-changed", refreshUsage);
    return () => window.removeEventListener("proofshape:usage-changed", refreshUsage);
  }, [refreshUsage]);

  const pickFile = React.useCallback(() => fileRef.current?.click(), []);

  // Back from Stripe Checkout (?upgraded=1): say so once; the webhook may land a moment later.
  const [upgraded, setUpgraded] = React.useState(false);
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("upgraded") !== "1") return;
    setUpgraded(true);
    params.delete("upgraded");
    const rest = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}`);
    const t = window.setTimeout(() => window.dispatchEvent(new Event("proofshape:usage-changed")), 4000);
    return () => window.clearTimeout(t);
  }, []);

  // ⌘K / Ctrl K opens search from anywhere; ? and go-to letters only outside text fields and dialogs.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        palette.setOpen(!palette.open);
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (palette.open || shortcuts || document.querySelector(".ob [aria-modal='true']")) return;
      if (e.key === "?") {
        e.preventDefault();
        setShortcuts(true);
        return;
      }
      const href = e.key.toLowerCase() === "v" ? palette.currentPart?.href : GO_KEYS[e.key.toLowerCase()];
      if (href && e.key.length === 1) {
        e.preventDefault();
        router.push(href);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [palette, shortcuts, router]);

  const section = sectionOf(pathname);
  return (
    <ShellContext.Provider value={{ pickFile, openShortcuts: () => setShortcuts(true), usage, refreshUsage }}>
      <div className="ob" data-ui="v4">
        <header className="bar">
          <Link className="brand" href={R.home}>
            <svg width="20" height="20" viewBox="0 0 26 26" fill="none" aria-hidden="true">
              <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            ScaleCAD
          </Link>
          <nav aria-label="Main" style={{ display: "flex", flexWrap: "wrap" }}>
            {NAV.map((n) => (
              <Link key={n.key} className={cx("pl", section === n.key && "on")} href={n.href} aria-current={section === n.key ? "page" : undefined}>
                {n.label}
                {n.pilot ? <small>Pilot</small> : null}
              </Link>
            ))}
          </nav>
          <button className="find" type="button" onClick={() => palette.setOpen(true)} aria-keyshortcuts="Meta+K Control+K">
            Search parts and tools, or ask<span aria-hidden="true">⌘K</span>
          </button>
          <button className="btn go sm" type="button" style={{ marginLeft: 8 }} onClick={pickFile}>
            Check a part
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={CAD_ACCEPT}
            aria-label="Choose a CAD file to check"
            tabIndex={-1}
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              setPendingFile(f);
              router.push(R.check);
            }}
          />
          <Bell />
          <AccountMenu usage={usage} onShortcuts={() => setShortcuts(true)} />
        </header>
        {upgraded ? (
          <div className="toast" role="status" style={{ position: "absolute", right: 20, top: 66, zIndex: 20 }}>
            <span>
              <b style={{ fontWeight: 600 }}>You&apos;re on Pro.</b>{" "}
              {usage?.plan === "pro" && usage.cap ? `${usage.cap} checks a month.` : "Your monthly checks are ready."} Your receipt is on its way by email.
            </span>
            <Link href={R.billing} onClick={() => setUpgraded(false)}>
              Manage billing
            </Link>
            <button type="button" aria-label="Dismiss" onClick={() => setUpgraded(false)} style={{ border: 0, background: "transparent", color: "inherit", cursor: "pointer", fontSize: 16 }}>
              ✕
            </button>
          </div>
        ) : null}
        {children}
        <Palette onPickFile={pickFile} onShortcuts={() => setShortcuts(true)} />
        {shortcuts ? <Shortcuts onClose={() => setShortcuts(false)} /> : null}
      </div>
    </ShellContext.Provider>
  );
}

function Bell() {
  const pathname = usePathname();
  const [unread, setUnread] = React.useState<number | null>(null);
  React.useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/notifications?status=open&unread=true&dismissed=false&limit=100`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => {
        if (live) setUnread(p ? (p.notifications?.length ?? 0) : null);
      })
      .catch(() => live && setUnread(null));
    return () => {
      live = false;
    };
  }, [pathname]);
  const label = unread == null ? "Notifications" : `Notifications, ${unread >= 100 ? "100 or more" : unread} unread`;
  return (
    <Link className="btn bell sm" href={R.notifications} aria-label={label}>
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M5 8a5 5 0 0 1 10 0c0 4.2 1.6 5.6 1.6 5.6H3.4S5 12.2 5 8Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M8.3 16.2a1.9 1.9 0 0 0 3.4 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      {unread ? <span className="dot num" aria-hidden="true">{unread >= 100 ? "99+" : unread}</span> : null}
    </Link>
  );
}

function AccountMenu({ usage, onShortcuts }: { usage: Usage | null; onShortcuts: () => void }) {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [askOut, setAskOut] = React.useState(false);
  const [orgs, setOrgs] = React.useState<{ active: string | null; list: Org[] } | null>(null);
  const [switching, setSwitching] = React.useState(false);
  const [consent, setConsent] = React.useState<string | null>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);
  const buttonRef = React.useRef<HTMLButtonElement>(null);

  React.useEffect(() => {
    fetch(`${API_BASE}/orgs`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => b && setOrgs({ active: b.active_org_id ?? null, list: b.organizations ?? [] }))
      .catch(() => {});
    try {
      setConsent(localStorage.getItem(ANALYTICS_CONSENT));
    } catch {
      setConsent(null);
    }
  }, []);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setAskOut(false);
        buttonRef.current?.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (!panelRef.current?.contains(e.target as Node) && !buttonRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const active = orgs?.list.find((o) => o.org_id === orgs.active) ?? null;
  const email = user?.email ?? "";
  const who = initials(email);
  const role = active?.org_role ? active.org_role[0].toUpperCase() + active.org_role.slice(1) : user?.role ?? "";
  const pro = usage?.plan === "pro";
  const pct = usage && usage.cap ? Math.min(100, Math.round((usage.used / usage.cap) * 100)) : 0;

  const links: [string, string, string][] = [
    ["Organization", R.org, "members, roles"],
    ["Security", R.security, "sign-in, sessions"],
    ["API and keys", R.api, ""],
    ["Plan and billing", R.billing, pro ? "Pro" : usage?.unlimited ? "Pilot" : "Free trial"],
    ["Notifications", R.notifications, ""],
  ];

  return (
    <>
      <button
        ref={buttonRef}
        className="btn av sm"
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Account: ${email}${active ? `, ${active.name}` : ""}${role ? `, ${role}` : ""}`}
        onClick={() => setOpen((o) => !o)}
        style={open ? { background: "var(--ink)", color: "#fff", borderColor: "var(--ink)" } : undefined}
      >
        {who}
      </button>
      {open ? (
        <div
          ref={panelRef}
          className="swap"
          role="dialog"
          aria-label="Account"
          style={{
            position: "absolute",
            right: 14,
            top: 60,
            width: 324,
            zIndex: 30,
            background: "#fff",
            border: "1px solid rgba(20,24,31,.1)",
            borderRadius: 18,
            boxShadow: "0 18px 50px rgba(20,24,31,.16)",
            padding: 8,
            display: "flex",
            flexDirection: "column",
            gap: 2,
            fontSize: 13.5,
          }}
        >
          <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 10px 10px" }}>
            <span style={{ width: 36, height: 36, borderRadius: 999, background: "#141414", color: "#fff", display: "grid", placeItems: "center", fontWeight: 600, fontSize: 13 }} aria-hidden="true">
              {who}
            </span>
            <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <b style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{email}</b>
              <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{[role, active?.name].filter(Boolean).join(" · ")}</span>
            </span>
            <button className="btn sm ghost" type="button" aria-label="Close" onClick={() => setOpen(false)} style={{ marginLeft: "auto", width: 32, padding: 0 }}>
              ✕
            </button>
          </div>
          {orgs && orgs.list.length > 1 ? (
            <label className="field" style={{ padding: "0 10px 8px" }}>
              Organization
              <select
                aria-label="Active organization"
                value={orgs.active ?? ""}
                disabled={switching}
                onChange={async (e) => {
                  const id = e.target.value;
                  setSwitching(true);
                  try {
                    const r = await fetch(`${API_BASE}/orgs/switch`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ org_id: id }) });
                    if (r.ok) {
                      setOrgs({ ...orgs, active: id });
                      router.refresh();
                    }
                  } finally {
                    setSwitching(false);
                  }
                }}
              >
                {orgs.list.map((o) => (
                  <option key={o.org_id} value={o.org_id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {usage && !usage.unlimited ? (
            <div style={{ margin: "0 10px 8px", padding: "10px 12px", borderRadius: 12, background: "rgba(20,24,31,.04)", display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--ink2)" }}>{pro ? "Pro checks this month" : "Free checks"}</span>
                <b className="num" style={{ fontWeight: 600 }}>
                  {usage.used} of {usage.cap} used
                </b>
              </span>
              <span style={{ height: 6, borderRadius: 999, background: "rgba(20,24,31,.1)", overflow: "hidden" }} role="progressbar" aria-label="Checks used" aria-valuemin={0} aria-valuemax={usage.cap} aria-valuenow={usage.used}>
                <span style={{ display: "block", width: `${pct}%`, height: "100%", background: "#141414", borderRadius: 999 }} />
              </span>
              <span style={{ display: "flex", justifyContent: "space-between", color: "var(--ink3)", fontSize: 12.5 }}>
                <span>{pro ? "Resets monthly" : usage.tier === "work" ? "Work email · the sample uses 1 too" : "Personal email · the sample uses 1 too"}</span>
                <Link href={R.billing} onClick={() => setOpen(false)}>
                  {pro ? "Manage" : "Upgrade"}
                </Link>
              </span>
            </div>
          ) : null}
          <div style={{ height: 1, background: "var(--rule)", margin: "2px 10px 4px" }} />
          {links.map(([label, href, note]) => (
            <Link key={href} href={href} onClick={() => setOpen(false)} style={{ display: "flex", justifyContent: "space-between", padding: "7px 10px", borderRadius: 10, color: "var(--ink)", textDecoration: "none" }}>
              {label}
              <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{note}</span>
            </Link>
          ))}
          <div style={{ height: 1, background: "var(--rule)", margin: "4px 10px" }} />
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "6px 10px" }}>
            <span>
              Analytics{" "}
              <a href="/privacy" style={{ fontSize: 12.5 }}>
                Privacy details
              </a>
            </span>
            <span className="seg" role="group" aria-label="Analytics">
              {(["yes", "no"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  className={cx(consent === v && "on")}
                  aria-pressed={consent === v}
                  onClick={() => {
                    try {
                      localStorage.setItem(ANALYTICS_CONSENT, v);
                    } catch {
                      return;
                    }
                    setConsent(v);
                    if (v !== "yes") location.reload();
                  }}
                >
                  {v === "yes" ? "Allow" : "Off"}
                </button>
              ))}
            </span>
          </div>
          <div style={{ height: 1, background: "var(--rule)", margin: "4px 10px" }} />
          <Link href={R.setup} onClick={() => setOpen(false)} style={{ display: "flex", justifyContent: "space-between", padding: "7px 10px", borderRadius: 10, color: "var(--ink)", textDecoration: "none" }}>
            Start here<span style={{ color: "var(--ink3)", fontSize: 12.5 }}>setup steps</span>
          </Link>
          <button
            type="button"
            className="btn sm ghost"
            onClick={() => {
              setOpen(false);
              onShortcuts();
            }}
            style={{ justifyContent: "space-between", color: "var(--ink)", margin: "0 2px", fontWeight: 400, fontSize: 13.5 }}
          >
            Keyboard shortcuts<span style={{ color: "var(--ink3)", fontSize: 12.5 }}>?</span>
          </button>
          {askOut ? (
            <div className="swap" role="alertdialog" aria-label="Sign out" style={{ margin: "4px 6px 2px", padding: "10px 12px", borderRadius: 12, background: "var(--bad-bg)", display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ color: "var(--ink2)" }}>Sign out{active ? ` of ${active.name}` : ""}? You&apos;re signed out on every device. Saved parts and decisions stay.</span>
              <span style={{ display: "flex", gap: 6 }}>
                <button className="btn sm ink" type="button" onClick={() => void signOut()}>
                  Sign out
                </button>
                <button className="btn sm" type="button" onClick={() => setAskOut(false)}>
                  Cancel
                </button>
              </span>
            </div>
          ) : (
            <button className="btn sm ghost" type="button" onClick={() => setAskOut(true)} style={{ justifyContent: "flex-start", color: "var(--bad)", margin: "0 2px" }}>
              Sign out
            </button>
          )}
        </div>
      ) : null}
    </>
  );
}

const KEYS: [string, string[]][] = [
  ["Search and commands", ["⌘", "K"]],
  ["Same, on Windows and Linux", ["Ctrl", "K"]],
  ["These shortcuts", ["?"]],
  ["Close the sheet, dialog, menu or popover on top", ["Esc"]],
  ["Turn the part", ["←", "→"]],
  ["Home", ["H"]],
  ["The part you have open", ["V"]],
  ["Parts", ["P"]],
  ["Records", ["R"]],
  ["Programs", ["G"]],
  ["Machines and printers", ["M"]],
  ["Triage", ["T"]],
  ["Rates and real costs", ["C"]],
  ["Fit in context", ["F"]],
];

function Shortcuts({ onClose }: { onClose: () => void }) {
  const closeRef = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 40, display: "grid", placeItems: "start center", paddingTop: 96 }}>
      <button type="button" tabIndex={-1} aria-hidden="true" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "rgba(237,239,242,.55)", backdropFilter: "blur(2px)" }} />
      <section role="dialog" aria-modal="true" aria-labelledby="ks-title" style={{ position: "relative", width: 560, maxWidth: "calc(100% - 32px)", background: "#fff", borderRadius: 20, border: "1px solid var(--rule)", boxShadow: "0 30px 80px rgba(20,24,31,.2)", padding: "18px 20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 className="ptitle" id="ks-title">
              Keyboard shortcuts
            </h1>
            <p className="pmeta" style={{ marginTop: 6 }}>
              <span>Letter keys work outside text fields</span>
              <span>Esc closes whatever is on top</span>
            </p>
          </div>
          <button ref={closeRef} className="btn sm" type="button" onClick={onClose} aria-label="Close keyboard shortcuts">
            ✕
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: "8px 16px", marginTop: 14, fontSize: 13.5 }}>
          {KEYS.map(([what, keys]) => (
            <React.Fragment key={what}>
              <span>{what}</span>
              <span style={{ display: "flex", gap: 4 }}>
                {keys.map((k) => (
                  <kbd key={k} style={{ fontFamily: "inherit", fontSize: 12, border: "1px solid var(--rule2)", borderRadius: 6, padding: "1px 7px", background: "#fff" }}>
                    {k}
                  </kbd>
                ))}
              </span>
            </React.Fragment>
          ))}
        </div>
        <p className="smeta" style={{ marginTop: 14 }}>
          Go-to keys don&apos;t fire inside dialogs or while ⌘, Ctrl or Alt is held.
        </p>
      </section>
    </div>
  );
}
